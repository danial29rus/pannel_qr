import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ProviderRouteCreate, ProviderRouteUpdate
from app.dao.repositories import ProviderDAO, ProviderRouteDAO, ProjectDAO, TransactionDAO
from app.db.models import PaymentProvider, ProjectProviderRoute, TransactionState

SUCCESSFUL_STATES = (TransactionState.succeeded,)
MOSCOW = ZoneInfo("Europe/Moscow")


def start_of_day(now: datetime) -> datetime:
    return now.astimezone(MOSCOW).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def start_of_week(now: datetime) -> datetime:
    day = start_of_day(now)
    return day - timedelta(days=day.weekday())


def is_in_time_window(now: time, start: time | None, end: time | None) -> bool:
    if start is None or end is None:
        return True
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end  # window crosses midnight


@dataclass(frozen=True)
class RouteEvaluation:
    daily_amount: Decimal
    weekly_amount: Decimal
    daily_count: int
    weekly_count: int
    ten_minute_count: int
    hourly_count: int
    pending_count: int
    available: bool
    reason: str | None = None

    @property
    def utilization(self) -> Decimal:
        return Decimal("0")


class RoutingService:
    @staticmethod
    def _validate_route_bounds(payload: ProviderRouteCreate | ProviderRouteUpdate) -> None:
        if payload.min_amount is not None and payload.max_amount is not None and payload.min_amount > payload.max_amount:
            raise HTTPException(status_code=422, detail="min_amount cannot exceed max_amount")
        if (payload.available_from is None) != (payload.available_to is None):
            raise HTTPException(status_code=422, detail="Set both available_from and available_to, or neither")

    @staticmethod
    async def create_route(session: AsyncSession, project_id: uuid.UUID, payload: ProviderRouteCreate) -> ProjectProviderRoute:
        RoutingService._validate_route_bounds(payload)
        if not await ProjectDAO.get(session, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        provider = await ProviderDAO.get(session, payload.provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Payment provider not found")
        route = ProjectProviderRoute(project_id=project_id, **payload.model_dump())
        try:
            await ProviderRouteDAO.create(session, route)
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="A route with this provider and name already exists") from exc
        await session.refresh(route)
        return route

    @staticmethod
    async def list_routes(session: AsyncSession, project_id: uuid.UUID) -> list[ProjectProviderRoute]:
        return await ProviderRouteDAO.list_by_project(session, project_id)

    @staticmethod
    async def set_activation(session: AsyncSession, route_id: uuid.UUID, is_active: bool) -> ProjectProviderRoute:
        route = await ProviderRouteDAO.get(session, route_id)
        if not route:
            raise HTTPException(status_code=404, detail="Provider route not found")
        route.is_active = is_active
        await ProviderRouteDAO.save(session, route)
        await session.commit()
        await session.refresh(route)
        return route

    @staticmethod
    async def update_route(session: AsyncSession, route_id: uuid.UUID, payload: ProviderRouteUpdate) -> ProjectProviderRoute:
        RoutingService._validate_route_bounds(payload)
        route = await ProviderRouteDAO.get(session, route_id)
        if not route:
            raise HTTPException(status_code=404, detail="Provider route not found")
        for field, value in payload.model_dump().items():
            setattr(route, field, value)
        await ProviderRouteDAO.save(session, route)
        await session.commit()
        await session.refresh(route)
        return route

    @staticmethod
    async def evaluate(session: AsyncSession, route: ProjectProviderRoute, amount: Decimal | None = None) -> RouteEvaluation:
        now = datetime.now(UTC)
        # Financial capacity and economics only consume completed payments.
        # Rolling velocity remains independent and counts every accepted request.
        daily_amount, daily_count = await TransactionDAO.provider_usage(session, route.project_id, route.provider_id, start_of_day(now), SUCCESSFUL_STATES)
        weekly_amount, weekly_count = await TransactionDAO.provider_usage(session, route.project_id, route.provider_id, start_of_week(now), SUCCESSFUL_STATES)
        ten_minute_count = await TransactionDAO.count_created_since(session, route.project_id, now - timedelta(minutes=10), route.provider_id)
        hourly_count = await TransactionDAO.count_created_since(session, route.project_id, now - timedelta(hours=1), route.provider_id)
        pending_count = await TransactionDAO.count_pending(session, route.project_id, route.provider_id)
        # Route schedules are configured and displayed in Moscow time, the
        # same timezone used for daily and weekly limits.
        current_time = now.astimezone(MOSCOW).time().replace(tzinfo=None)
        if not route.is_active:
            return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Маршрут выключен")
        provider = await ProviderDAO.get(session, route.provider_id)
        if not provider or not provider.is_active:
            return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Платёжка выключена")
        if not is_in_time_window(current_time, route.available_from, route.available_to):
            return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Сейчас вне окна работы")
        if route.max_transactions_10m is not None and ten_minute_count >= route.max_transactions_10m:
            return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Лимит заявок за 10 минут исчерпан")
        if route.max_transactions_hour is not None and hourly_count >= route.max_transactions_hour:
            return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Лимит заявок за час исчерпан")
        if route.max_pending_transactions is not None and pending_count >= route.max_pending_transactions:
            return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Лимит ожидающих платежей исчерпан")
        if amount is not None:
            if route.min_amount is not None and amount < route.min_amount:
                return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Сумма ниже лимита маршрута")
            if route.max_amount is not None and amount > route.max_amount:
                return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Сумма выше лимита маршрута")
            if route.daily_amount_limit is not None and daily_amount + amount > route.daily_amount_limit:
                return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Дневной лимит суммы исчерпан")
            if route.weekly_amount_limit is not None and weekly_amount + amount > route.weekly_amount_limit:
                return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Недельный лимит суммы исчерпан")
            if route.daily_transactions_limit is not None and daily_count + 1 > route.daily_transactions_limit:
                return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Дневной лимит успешных платежей исчерпан")
            if route.weekly_transactions_limit is not None and weekly_count + 1 > route.weekly_transactions_limit:
                return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, False, "Недельный лимит успешных платежей исчерпан")
        return RouteEvaluation(daily_amount, weekly_amount, daily_count, weekly_count, ten_minute_count, hourly_count, pending_count, True)

    @staticmethod
    def balance_score(route: ProjectProviderRoute, evaluation: RouteEvaluation) -> tuple[int, Decimal, int]:
        ratios: list[Decimal] = []
        if route.daily_amount_limit:
            ratios.append(evaluation.daily_amount / route.daily_amount_limit)
        if route.weekly_amount_limit:
            ratios.append(evaluation.weekly_amount / route.weekly_amount_limit)
        if route.daily_transactions_limit:
            ratios.append(Decimal(evaluation.daily_count) / route.daily_transactions_limit)
        if route.weekly_transactions_limit:
            ratios.append(Decimal(evaluation.weekly_count) / route.weekly_transactions_limit)
        if route.max_transactions_10m:
            ratios.append(Decimal(evaluation.ten_minute_count) / route.max_transactions_10m)
        if route.max_transactions_hour:
            ratios.append(Decimal(evaluation.hourly_count) / route.max_transactions_hour)
        if route.max_pending_transactions:
            ratios.append(Decimal(evaluation.pending_count) / route.max_pending_transactions)
        return route.priority, max(ratios, default=Decimal("0")), -route.weight

    @classmethod
    async def resolve_provider(cls, session: AsyncSession, project_id: uuid.UUID, amount: Decimal, provider_code: str | None) -> PaymentProvider:
        routes = await ProviderRouteDAO.list_by_project(session, project_id, active_only=True)
        if not routes:
            if not provider_code:
                raise HTTPException(status_code=422, detail="No active payment route configured for this project")
            provider = await ProviderDAO.get_by_code(session, provider_code)
            if not provider or not provider.is_active:
                raise HTTPException(status_code=404, detail="Active payment provider not found")
            return provider
        candidates: list[tuple[ProjectProviderRoute, PaymentProvider, RouteEvaluation]] = []
        for route in routes:
            provider = await ProviderDAO.get(session, route.provider_id)
            if not provider:
                continue
            if provider_code and provider.code != provider_code:
                continue
            evaluation = await cls.evaluate(session, route, amount)
            if evaluation.available:
                candidates.append((route, provider, evaluation))
        if not candidates:
            raise HTTPException(status_code=422, detail="No enabled payment route can process this payment within its schedule and limits")
        route, provider, _ = min(candidates, key=lambda item: cls.balance_score(item[0], item[2]))
        return provider

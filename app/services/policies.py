import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import OperationalPolicyUpsert, TransactionCreate
from app.dao.repositories import OperationalPolicyDAO, ProjectDAO, TransactionDAO
from app.db.models import ProjectOperationalPolicy, TransactionState


class OperationalPolicyService:
    """Business guards for payment amount and request velocity."""

    @staticmethod
    async def get(session: AsyncSession, project_id: uuid.UUID) -> ProjectOperationalPolicy:
        policy = await OperationalPolicyDAO.get(session, project_id)
        if not policy:
            raise HTTPException(status_code=404, detail="Operational policy not found")
        return policy

    @staticmethod
    async def upsert(
        session: AsyncSession, project_id: uuid.UUID, payload: OperationalPolicyUpsert,
    ) -> ProjectOperationalPolicy:
        if not await ProjectDAO.get(session, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        policy = await OperationalPolicyDAO.get(session, project_id)
        if policy:
            for field, value in payload.model_dump().items():
                setattr(policy, field, value)
            await OperationalPolicyDAO.save(session, policy)
        else:
            policy = await OperationalPolicyDAO.create(session, ProjectOperationalPolicy(project_id=project_id, **payload.model_dump()))
        await session.commit()
        await session.refresh(policy)
        return policy

    @staticmethod
    async def assert_allows(session: AsyncSession, payload: TransactionCreate) -> None:
        policy = await OperationalPolicyDAO.get(session, payload.project_id)
        if not policy or not policy.is_active:
            return
        now = datetime.now(UTC)
        in_hour = await TransactionDAO.count_created_since(session, payload.project_id, now - timedelta(hours=1))
        if in_hour >= policy.max_transactions_hour:
            raise HTTPException(status_code=429, detail={"code": "frequency_limit_hour", "limit": policy.max_transactions_hour})
        moscow = ZoneInfo("Europe/Moscow")
        day_start = now.astimezone(moscow).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        in_day = await TransactionDAO.count_created_since(session, payload.project_id, day_start)
        if in_day >= policy.max_transactions_day:
            raise HTTPException(status_code=429, detail={"code": "frequency_limit_day", "limit": policy.max_transactions_day, "timezone": "Europe/Moscow"})
        used_amount = await TransactionDAO.amount_used(session, payload.project_id, payload.direction, payload.currency.upper(), day_start, (
            TransactionState.created, TransactionState.pending, TransactionState.processing, TransactionState.succeeded,
        ))
        if used_amount + payload.amount > policy.daily_amount_limit:
            raise HTTPException(status_code=422, detail={"code": "daily_amount_limit", "limit": str(policy.daily_amount_limit), "used": str(used_amount), "timezone": "Europe/Moscow"})
        if policy.cooldown_minutes:
            last_created = await TransactionDAO.latest_created_at(session, payload.project_id)
            cooldown = timedelta(minutes=policy.cooldown_minutes)
            if last_created and now - last_created < cooldown:
                retry_after = int((cooldown - (now - last_created)).total_seconds())
                raise HTTPException(status_code=429, detail={"code": "payment_cooldown", "retry_after_seconds": retry_after})

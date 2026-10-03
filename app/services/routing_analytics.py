from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ProjectRoutingAnalytics, ProviderRouteAnalytics, ProviderRouteRead
from app.dao.repositories import LimitDAO, OperationalPolicyDAO, ProjectDAO, ProviderDAO, ProviderRouteDAO
from app.services.routing import RoutingService


def percent_of(amount, rate):
    return amount * rate / 100


def commission_margin(amount, client_fee_percent, provider_fee_percent):
    """Commission income only; merchandise margin is outside this model."""
    return percent_of(amount, client_fee_percent) - percent_of(amount, provider_fee_percent)


class RoutingAnalyticsService:
    @staticmethod
    async def all_projects(session: AsyncSession) -> list[ProjectRoutingAnalytics]:
        result: list[ProjectRoutingAnalytics] = []
        for project in await ProjectDAO.list(session):
            route_rows: list[ProviderRouteAnalytics] = []
            for route in await ProviderRouteDAO.list_by_project(session, project.id):
                provider = await ProviderDAO.get(session, route.provider_id)
                if not provider:
                    continue
                evaluation = await RoutingService.evaluate(session, route)
                route_data = ProviderRouteRead.model_validate(route).model_dump()
                route_rows.append(ProviderRouteAnalytics(
                    **route_data,
                    provider_code=provider.code,
                    provider_name=provider.name,
                    daily_used_amount=evaluation.daily_amount,
                    weekly_used_amount=evaluation.weekly_amount,
                    daily_used_transactions=evaluation.daily_count,
                    weekly_used_transactions=evaluation.weekly_count,
                    ten_minute_used_transactions=evaluation.ten_minute_count,
                    hourly_used_transactions=evaluation.hourly_count,
                    pending_transactions=evaluation.pending_count,
                    is_available=evaluation.available,
                    unavailable_reason=evaluation.reason,
                    provider_fee_percent=provider.provider_fee_percent,
                    platform_fee_percent=project.default_platform_fee_percent,
                    daily_provider_cost=percent_of(evaluation.daily_amount, provider.provider_fee_percent),
                    daily_platform_revenue=percent_of(evaluation.daily_amount, project.default_platform_fee_percent),
                    daily_profit=commission_margin(
                        evaluation.daily_amount,
                        project.default_platform_fee_percent,
                        provider.provider_fee_percent,
                    ),
                    weekly_provider_cost=percent_of(evaluation.weekly_amount, provider.provider_fee_percent),
                    weekly_platform_revenue=percent_of(evaluation.weekly_amount, project.default_platform_fee_percent),
                    weekly_profit=commission_margin(
                        evaluation.weekly_amount,
                        project.default_platform_fee_percent,
                        provider.provider_fee_percent,
                    ),
                ))
            result.append(ProjectRoutingAnalytics(
                project=project,
                financial_limits=await LimitDAO.list_by_project(session, project.id),
                operational_policy=await OperationalPolicyDAO.get(session, project.id),
                provider_routes=route_rows,
            ))
        return result

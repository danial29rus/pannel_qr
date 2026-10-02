import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    CatalogSourceActivationUpdate, CatalogSourceCreate, CatalogSourceRead, CatalogSyncResult, DashboardSummary, ExternalOrderCreate, ExternalOrderResponse, ExternalPlatformConfigUpdate, LimitCreate, LimitRead, LoginRequest, LoginResponse, OperationalPolicyRead, OperationalPolicyUpsert, ProjectActivationUpdate, ProjectCommissionUpdate, ProjectCreate, ProjectRead, ProviderCommissionUpdate, ProviderCreate, ProviderRead, ProviderRouteActivationUpdate, ProviderRouteCreate, ProviderRouteRead, ProviderRouteUpdate, ProjectRoutingAnalytics,
    OrderCreate, OrderRead, ProductCreate, ProductRead, SupportConversationCreate, SupportConversationRead, SupportMessageCreate, SupportMessageRead, TransactionCreate, TransactionListItem, TransactionRead, TransactionTrace, UserCreate, UserRead,
)
from app.db.session import get_session
from app.db.models import ActorRole
from app.api.security import require_roles
from app.payments.service import PaymentService
from app.services.catalog import CatalogService
from app.services.dashboard import DashboardService
from app.services.support import SupportService
from app.services.policies import OperationalPolicyService
from app.services.routing import RoutingService
from app.services.routing_analytics import RoutingAnalyticsService
from app.services.orders import OrderService
from app.services.catalog_sync import CatalogSyncService
from app.services.external_platform import ExternalPlatformService
from app.api.auth import login

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
async def panel_login(payload: LoginRequest):
    return LoginResponse(access_token=login(payload.username, payload.password))


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin))])
async def add_user(payload: UserCreate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.create_user(session, payload)


@router.get("/users", response_model=list[UserRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def list_users(session: AsyncSession = Depends(get_session)):
    return await CatalogService.list_users(session)


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin))])
async def add_project(payload: ProjectCreate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.create_project(session, payload)


@router.get("/projects", response_model=list[ProjectRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def list_projects(session: AsyncSession = Depends(get_session)):
    return await CatalogService.list_projects(session)


@router.patch("/projects/{project_id}/activation", response_model=ProjectRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def set_project_activation(project_id: uuid.UUID, payload: ProjectActivationUpdate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.set_project_activation(session, project_id, payload.is_active)


@router.patch("/projects/{project_id}/commission", response_model=ProjectRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def set_project_commission(project_id: uuid.UUID, payload: ProjectCommissionUpdate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.set_project_commission(session, project_id, payload)


@router.put("/projects/{project_id}/external-platform", response_model=ProjectRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def set_external_platform(project_id: uuid.UUID, payload: ExternalPlatformConfigUpdate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.set_external_platform_config(session, project_id, payload)


@router.post("/providers", response_model=ProviderRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin))])
async def add_provider(payload: ProviderCreate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.create_provider(session, payload)


@router.get("/providers", response_model=list[ProviderRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def list_providers(session: AsyncSession = Depends(get_session)):
    return await CatalogService.list_providers(session)


@router.patch("/providers/{provider_id}/commission", response_model=ProviderRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def set_provider_commission(provider_id: uuid.UUID, payload: ProviderCommissionUpdate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.set_provider_commission(session, provider_id, payload)


@router.post("/limits", response_model=LimitRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin))])
async def add_limit(payload: LimitCreate, session: AsyncSession = Depends(get_session)):
    return await CatalogService.create_limit(session, payload)


@router.get("/limits", response_model=list[LimitRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def list_limits(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await CatalogService.list_limits(session, project_id)


@router.get("/projects/{project_id}/operational-policy", response_model=OperationalPolicyRead, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def get_operational_policy(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await OperationalPolicyService.get(session, project_id)


@router.put("/projects/{project_id}/operational-policy", response_model=OperationalPolicyRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def set_operational_policy(
    project_id: uuid.UUID, payload: OperationalPolicyUpsert, session: AsyncSession = Depends(get_session),
):
    return await OperationalPolicyService.upsert(session, project_id, payload)


@router.post("/projects/{project_id}/provider-routes", response_model=ProviderRouteRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin))])
async def create_provider_route(project_id: uuid.UUID, payload: ProviderRouteCreate, session: AsyncSession = Depends(get_session)):
    return await RoutingService.create_route(session, project_id, payload)


@router.get("/projects/{project_id}/provider-routes", response_model=list[ProviderRouteRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def list_provider_routes(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await RoutingService.list_routes(session, project_id)


@router.put("/provider-routes/{route_id}", response_model=ProviderRouteRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def update_provider_route(route_id: uuid.UUID, payload: ProviderRouteUpdate, session: AsyncSession = Depends(get_session)):
    return await RoutingService.update_route(session, route_id, payload)


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin))])
async def create_product(payload: ProductCreate, session: AsyncSession = Depends(get_session)):
    return await OrderService.create_product(session, payload)


@router.get("/products", response_model=list[ProductRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def list_products(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await OrderService.list_products(session, project_id)


@router.post("/catalog-sources", response_model=CatalogSourceRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin))])
async def create_catalog_source(payload: CatalogSourceCreate, session: AsyncSession = Depends(get_session)):
    return await CatalogSyncService.create_source(session, payload)


@router.get("/catalog-sources", response_model=list[CatalogSourceRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def list_catalog_sources(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await CatalogSyncService.list_sources(session, project_id)


@router.patch("/catalog-sources/{source_id}/activation", response_model=CatalogSourceRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def set_catalog_source_activation(source_id: uuid.UUID, payload: CatalogSourceActivationUpdate, session: AsyncSession = Depends(get_session)):
    return await CatalogSyncService.set_activation(session, source_id, payload.is_active)


@router.post("/catalog-sources/{source_id}/sync", response_model=CatalogSyncResult, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def sync_catalog_source(source_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await CatalogSyncService.sync(session, source_id)


@router.post("/orders", response_model=OrderRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def create_order(payload: OrderCreate, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), session: AsyncSession = Depends(get_session)):
    return await OrderService.create_order(session, payload, idempotency_key)


@router.post("/external/{project_key}/orders", response_model=ExternalOrderResponse, status_code=status.HTTP_201_CREATED)
async def accept_external_order(project_key: str, payload: ExternalOrderCreate, request: Request, session: AsyncSession = Depends(get_session)):
    """Public integration endpoint; only the configured platform token may call it."""
    token = request.headers.get("x-platform-token")
    authorization = request.headers.get("authorization", "")
    if not token and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    project = await ExternalPlatformService.project_for_request(session, project_key, token)
    request_payload = payload.model_dump(mode="json")
    try:
        order = await OrderService.create_external_order(session, project.id, payload)
        response = ExternalOrderResponse(
            external_order_id=payload.external_order_id, order_id=order.id, transaction_id=order.transaction_id,
            status=order.status, payment_url=order.payment_url,
        )
        await ExternalPlatformService.log_request(
            session, project.id, payload.external_order_id, request_payload, outcome="accepted", http_status=201,
            response_payload=response.model_dump(mode="json"),
        )
        return response
    except HTTPException as exc:
        await ExternalPlatformService.log_request(
            session, project.id, payload.external_order_id, request_payload, outcome="rejected", http_status=exc.status_code,
            response_payload={"detail": exc.detail} if isinstance(exc.detail, (str, dict)) else None, error=str(exc.detail),
        )
        raise


@router.patch("/provider-routes/{route_id}/activation", response_model=ProviderRouteRead, dependencies=[Depends(require_roles(ActorRole.admin))])
async def set_provider_route_activation(route_id: uuid.UUID, payload: ProviderRouteActivationUpdate, session: AsyncSession = Depends(get_session)):
    return await RoutingService.set_activation(session, route_id, payload.is_active)


@router.post("/transactions", response_model=TransactionRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def add_transaction(
    payload: TransactionCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    session: AsyncSession = Depends(get_session),
):
    return await PaymentService.create(session, payload, idempotency_key)


@router.get("/transactions", response_model=list[TransactionListItem], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def list_transactions(project_id: uuid.UUID, limit: int = 50, session: AsyncSession = Depends(get_session)):
    return await PaymentService.list(session, project_id, limit)


@router.get("/transactions/{transaction_id}/trace", response_model=TransactionTrace, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def transaction_trace(transaction_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """The complete read-only route: platform → provider → webhook → callback."""
    return await PaymentService.trace(session, transaction_id)


@router.get("/transactions/{transaction_id}/events", dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def transaction_events(transaction_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    events = await PaymentService.events(session, transaction_id)
    return [{"id": e.id, "event_type": e.event_type, "previous_state": e.previous_state, "state": e.state,
             "actor": e.actor, "payload": e.payload, "created_at": e.created_at} for e in events]


@router.post("/webhooks/{provider_code}", status_code=status.HTTP_204_NO_CONTENT)
async def provider_webhook(provider_code: str, request: Request, session: AsyncSession = Depends(get_session)):
    body = await request.body()
    await PaymentService.process_webhook(session, provider_code, body, {key.lower(): value for key, value in request.headers.items()})


@router.post("/support/conversations", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def create_conversation(payload: SupportConversationCreate, session: AsyncSession = Depends(get_session)):
    conversation = await SupportService.create_conversation(session, payload)
    return {"id": conversation.id, "status": conversation.status}


@router.get("/support/conversations", response_model=list[SupportConversationRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def list_support_conversations(session: AsyncSession = Depends(get_session)):
    return await SupportService.list_conversations(session)


@router.get("/support/conversations/{conversation_id}/messages", response_model=list[SupportMessageRead], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def list_support_messages(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await SupportService.list_messages(session, conversation_id)


@router.post("/support/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator))])
async def add_support_message(conversation_id: uuid.UUID, payload: SupportMessageCreate, session: AsyncSession = Depends(get_session)):
    message = await SupportService.add_message(session, conversation_id, payload)
    return {"id": message.id, "created_at": message.created_at}


@router.get("/dashboard/summary", response_model=DashboardSummary, dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def dashboard_summary(
    project_id: uuid.UUID, currency: str = "USDT", from_date: datetime | None = None,
    to_date: datetime | None = None, session: AsyncSession = Depends(get_session),
):
    return await DashboardService.summary(session, project_id, currency, from_date, to_date)


@router.get("/analytics/projects", response_model=list[ProjectRoutingAnalytics], dependencies=[Depends(require_roles(ActorRole.admin, ActorRole.operator, ActorRole.viewer))])
async def routing_analytics(session: AsyncSession = Depends(get_session)):
    return await RoutingAnalyticsService.all_projects(session)

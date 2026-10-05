import uuid
from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import LimitPeriod, TransactionDirection, TransactionState


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=512)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    phone: str | None = Field(default=None, max_length=40)
    telegram_username: str | None = Field(default=None, max_length=128)
    business_name: str = Field(min_length=1, max_length=255)


class UserRead(ORMModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    telegram_username: str | None
    business_name: str
    registered_at: datetime
    is_active: bool


class UserUpdate(UserCreate):
    is_active: bool = True


class UserPage(BaseModel):
    items: list[UserRead]
    total: int
    page: int
    page_size: int
    pages: int


class UserEmailImport(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=5_000)
    full_name_prefix: str = Field(default="Покупатель", min_length=1, max_length=180)
    business_name: str = Field(default="Импортированный покупатель", min_length=1, max_length=255)
    start_index: int = Field(default=1, ge=1)


class UserImportResult(BaseModel):
    created: int
    skipped: int
    total_received: int


class ProjectCreate(BaseModel):
    owner_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    external_key: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    default_platform_fee_percent: Decimal = Field(default=Decimal("13"), ge=0, le=100, max_digits=7, decimal_places=4)


class ProjectRead(ORMModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    external_key: str
    default_platform_fee_percent: Decimal
    external_callback_url: str | None
    status_check_interval_seconds: int
    payment_expiry_minutes: int
    is_active: bool
    created_at: datetime


class ProjectActivationUpdate(BaseModel):
    is_active: bool


class ProjectCommissionUpdate(BaseModel):
    default_platform_fee_percent: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class ExternalPlatformConfigUpdate(BaseModel):
    external_callback_url: str = Field(min_length=8, max_length=2048, pattern=r"^https://")
    external_incoming_token: str = Field(min_length=16, max_length=512)
    external_callback_secret: str = Field(min_length=16, max_length=512)
    status_check_interval_seconds: int = Field(default=30, ge=10, le=3600)
    payment_expiry_minutes: int = Field(default=30, ge=5, le=10_080)


class ProviderCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    adapter_type: str = Field(default="demo", max_length=100)
    credentials_encrypted: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)
    provider_fee_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=4)


class ProviderRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    adapter_type: str
    settings: dict
    provider_fee_percent: Decimal
    is_active: bool
    created_at: datetime


class ProviderCommissionUpdate(BaseModel):
    provider_fee_percent: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class CatalogSourceCreate(BaseModel):
    project_id: uuid.UUID
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    adapter_type: str = Field(default="workkit_http", max_length=100)
    settings: dict = Field(default_factory=dict, description="For workkit_http: base_url and optional api_path")
    credentials_encrypted: dict = Field(default_factory=dict, description="Optional API headers/tokens; never returned")


class CatalogSourceRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    adapter_type: str
    settings: dict
    is_active: bool
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class CatalogSourceActivationUpdate(BaseModel):
    is_active: bool


class CatalogSyncResult(BaseModel):
    source_id: uuid.UUID
    created: int
    updated: int
    skipped: int
    synced_at: datetime


class ProviderRouteCreate(BaseModel):
    provider_id: uuid.UUID
    name: str = Field(default="Основной маршрут", min_length=1, max_length=100)
    priority: int = Field(default=100, ge=0, le=100_000)
    weight: int = Field(default=100, ge=1, le=100_000)
    min_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    max_amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    daily_amount_limit: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    weekly_amount_limit: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    daily_transactions_limit: int | None = Field(default=None, gt=0)
    weekly_transactions_limit: int | None = Field(default=None, gt=0)
    max_transactions_10m: int | None = Field(default=None, gt=0)
    max_transactions_hour: int | None = Field(default=None, gt=0)
    max_all_transactions_hour: int | None = Field(default=None, gt=0)
    max_all_transactions_day: int | None = Field(default=None, gt=0)
    post_terminal_cooldown_seconds: int | None = Field(default=None, ge=0, le=86_400)
    post_terminal_cooldown_min_seconds: int | None = Field(default=None, ge=0, le=86_400)
    post_terminal_cooldown_max_seconds: int | None = Field(default=None, ge=0, le=86_400)
    max_pending_transactions: int | None = Field(default=None, gt=0)
    available_from: time | None = None
    available_to: time | None = None
    is_active: bool = True


class ProviderRouteRead(ProviderRouteCreate, ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ProviderRouteUpdate(BaseModel):
    """Operational settings of an existing project/provider connection."""
    name: str = Field(default="Основной маршрут", min_length=1, max_length=100)
    priority: int = Field(default=100, ge=0, le=100_000)
    weight: int = Field(default=100, ge=1, le=100_000)
    min_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    max_amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    daily_amount_limit: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    weekly_amount_limit: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    daily_transactions_limit: int | None = Field(default=None, gt=0)
    weekly_transactions_limit: int | None = Field(default=None, gt=0)
    max_transactions_10m: int | None = Field(default=None, gt=0)
    max_transactions_hour: int | None = Field(default=None, gt=0)
    max_all_transactions_hour: int | None = Field(default=None, gt=0)
    max_all_transactions_day: int | None = Field(default=None, gt=0)
    post_terminal_cooldown_seconds: int | None = Field(default=None, ge=0, le=86_400)
    post_terminal_cooldown_min_seconds: int | None = Field(default=None, ge=0, le=86_400)
    post_terminal_cooldown_max_seconds: int | None = Field(default=None, ge=0, le=86_400)
    max_pending_transactions: int | None = Field(default=None, gt=0)
    available_from: time | None = None
    available_to: time | None = None
    is_active: bool = True


class ProviderRouteActivationUpdate(BaseModel):
    is_active: bool


class ProviderRouteAnalytics(ProviderRouteRead):
    provider_code: str
    provider_name: str
    daily_used_amount: Decimal
    weekly_used_amount: Decimal
    daily_used_transactions: int
    weekly_used_transactions: int
    ten_minute_used_transactions: int
    hourly_used_transactions: int
    all_hour_used_transactions: int
    all_day_used_transactions: int
    pending_transactions: int
    is_available: bool
    unavailable_reason: str | None = None
    provider_fee_percent: Decimal
    platform_fee_percent: Decimal
    daily_provider_cost: Decimal
    daily_platform_revenue: Decimal
    daily_profit: Decimal
    weekly_provider_cost: Decimal
    weekly_platform_revenue: Decimal
    weekly_profit: Decimal
    all_time_used_amount: Decimal
    all_time_used_transactions: int
    all_time_provider_cost: Decimal
    all_time_platform_revenue: Decimal
    all_time_profit: Decimal


class LimitCreate(BaseModel):
    project_id: uuid.UUID
    direction: TransactionDirection
    period: LimitPeriod
    currency: str = Field(min_length=3, max_length=8)
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)


class LimitRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    direction: TransactionDirection
    period: LimitPeriod
    currency: str
    amount: Decimal
    is_active: bool
    created_at: datetime


class OperationalPolicyUpsert(BaseModel):
    max_transactions_10m: int = Field(default=15, ge=1, le=100_000)
    max_transactions_hour: int = Field(default=30, ge=1, le=100_000)
    max_transactions_day: int = Field(default=300, ge=1, le=1_000_000)
    max_all_transactions_hour: int | None = Field(default=None, ge=1, le=100_000)
    max_all_transactions_day: int | None = Field(default=None, ge=1, le=1_000_000)
    max_pending_transactions: int = Field(default=50, ge=1, le=1_000_000)
    daily_amount_limit: Decimal = Field(default=Decimal("100000"), gt=0, max_digits=20, decimal_places=4)
    cooldown_minutes: int = Field(default=0, ge=0, description="0 disables the pause; otherwise a project-selected number of minutes")
    is_active: bool = True


class OperationalPolicyRead(OperationalPolicyUpsert, ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    updated_at: datetime


class ProjectRoutingAnalytics(BaseModel):
    project: ProjectRead
    financial_limits: list[LimitRead]
    operational_policy: OperationalPolicyRead | None
    provider_routes: list[ProviderRouteAnalytics]


class TransactionCreate(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID | None = None
    provider_code: str | None = Field(default=None, min_length=2, max_length=64, description="Optional: the balancer selects an eligible route when omitted")
    direction: TransactionDirection = TransactionDirection.incoming
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field(min_length=3, max_length=8)
    description: str | None = Field(default=None, max_length=2000)
    extra: dict = Field(default_factory=dict)


class TransactionRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID | None
    provider_id: uuid.UUID
    external_id: str | None
    payment_url: str | None
    direction: TransactionDirection
    state: TransactionState
    amount: Decimal
    currency: str
    settled_amount: Decimal | None
    fee_amount: Decimal
    description: str | None
    created_at: datetime
    updated_at: datetime


class TransactionListItem(TransactionRead):
    """A payment row with enough context to be useful in the operations list."""
    provider_code: str
    provider_name: str
    order_id: uuid.UUID | None = None
    order_reference: str | None = None
    external_order_id: str | None = None
    merchant_transaction_id: str | None = None


class PaymentTraceEntry(BaseModel):
    """One immutable step in the life of a payment, ordered by occurrence."""
    id: str
    stage: str
    title: str
    outcome: str | None = None
    state: TransactionState | None = None
    previous_state: TransactionState | None = None
    actor: str | None = None
    attempt: int | None = None
    http_status: int | None = None
    payload: dict | None = None
    error: str | None = None
    created_at: datetime


class PaymentTraceCustomer(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None


class TransactionTrace(BaseModel):
    payment: TransactionListItem
    customer: PaymentTraceCustomer | None = None
    timeline: list[PaymentTraceEntry]


class ProductCreate(BaseModel):
    project_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    vat_code: int = Field(default=0, ge=0, le=7)
    payment_subject: int = Field(default=1, ge=1, le=26)
    payment_mode: int = Field(default=4, ge=1, le=7)
    measurement_unit: int = Field(default=0, ge=0, le=255)


class ProductRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    sku: str
    name: str
    description: str | None
    price: Decimal
    currency: str
    vat_code: int
    payment_subject: int
    payment_mode: int
    measurement_unit: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrderCreate(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int = Field(default=1, gt=0, le=10_000)
    provider_code: str | None = Field(default=None, min_length=2, max_length=64)
    website_url: str | None = Field(default=None, max_length=2048)
    language: str = Field(default="ru", min_length=2, max_length=10)


class OrderRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    product_id: uuid.UUID
    transaction_id: uuid.UUID | None
    payment_url: str | None
    external_order_id: str | None
    external_status_notified_at: datetime | None
    last_status_checked_at: datetime | None
    reference: str
    product_snapshot: dict
    quantity: int
    amount: Decimal
    currency: str
    status: str
    created_at: datetime
    updated_at: datetime


class ExternalOrderCreate(BaseModel):
    external_order_id: str = Field(min_length=1, max_length=128)
    user_id: uuid.UUID
    product_sku: str = Field(min_length=1, max_length=100)
    quantity: int = Field(default=1, gt=0, le=10_000)
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field(min_length=3, max_length=8)
    website_url: str | None = Field(default=None, max_length=2048)
    language: str = Field(default="ru", min_length=2, max_length=10)


class ExternalOrderResponse(BaseModel):
    external_order_id: str
    order_id: uuid.UUID
    transaction_id: uuid.UUID | None
    status: str
    payment_url: str | None


class MerchantQrPaymentCreate(BaseModel):
    """PayGateCore-compatible QR payment request from a merchant."""

    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field(min_length=3, max_length=8)
    merchant_transaction_id: str = Field(min_length=1, max_length=128)
    auto_amount_step: int | None = Field(default=None, ge=1)
    # PayGateCore sends 0 when automatic amount selection is explicitly
    # disabled. Positive values are the number of permitted selection steps.
    auto_amount_limit: int | None = Field(default=None, ge=0, le=20)
    # Optional MulenPay experiment. The value is forwarded as `holdTime`; its
    # provider-side meaning must be verified before using it in production.
    hold_time_seconds: int | None = Field(default=None, ge=1, le=86_400)
    currency_rate: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    webhook_url: str | None = Field(default=None, max_length=2048, pattern=r"^https://")
    return_url: str | None = Field(default=None, max_length=2048, pattern=r"^https?://")
    description: str | None = Field(default=None, min_length=1, max_length=512)


class MerchantQrPaymentResponse(BaseModel):
    id: uuid.UUID
    merchant_transaction_id: str
    expires_at: datetime
    amount: Decimal
    currency: str
    currency_rate: Decimal | None
    amount_in_usd: Decimal | None
    rate: Decimal
    commission: Decimal
    payment_url: str | None


class SupportConversationCreate(BaseModel):
    user_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=10000)


class SupportMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    author_type: str = Field(default="operator", pattern=r"^(user|operator|system)$")


class SupportConversationRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    subject: str
    status: str
    created_at: datetime
    closed_at: datetime | None
    user_full_name: str
    user_email: str | None
    user_telegram_username: str | None


class SupportMessageRead(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    author_type: str
    body: str
    created_at: datetime


class DashboardSummary(BaseModel):
    from_date: datetime
    to_date: datetime
    paid_by_clients: Decimal
    credited_by_payments: Decimal
    settlement_margin: Decimal
    payment_count: int
    success_count: int
    pending_count: int
    failed_count: int
    terminal_count: int

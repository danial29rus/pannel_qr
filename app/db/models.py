import enum
import uuid
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TransactionState(str, enum.Enum):
    created = "created"
    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    refunded = "refunded"


class TransactionDirection(str, enum.Enum):
    incoming = "incoming"
    outgoing = "outgoing"


class LimitPeriod(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    lifetime = "lifetime"


class ActorRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(200))
    # Nullable during the initial rollout so existing users remain valid.
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    telegram_username: Mapped[str | None] = mapped_column(String(128), unique=True)
    business_name: Mapped[str] = mapped_column(String(255))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    external_key: Mapped[str] = mapped_column(String(100), unique=True)
    # Mark-up charged by this project/platform. Provider cost lives on the
    # concrete provider connection; the difference is the projected profit.
    default_platform_fee_percent: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), default=Decimal("13"), server_default="13"
    )
    external_callback_url: Mapped[str | None] = mapped_column(Text)
    # Write-only secrets. They are never included in API responses.
    external_incoming_token: Mapped[str | None] = mapped_column(Text)
    external_callback_secret: Mapped[str | None] = mapped_column(Text)
    status_check_interval_seconds: Mapped[int] = mapped_column(default=30, server_default="30")
    payment_expiry_minutes: Mapped[int] = mapped_column(default=30, server_default="30")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentProvider(Base):
    __tablename__ = "payment_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    adapter_type: Mapped[str] = mapped_column(String(100))
    # Store encrypted values here in production; never return this column through API.
    credentials_encrypted: Mapped[dict] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Contractual processing cost for this particular key set / connection.
    provider_fee_percent: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), default=Decimal("0"), server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogSource(Base):
    """A project-scoped external catalogue connection.

    Product data is copied into the panel database, so creating an order never
    depends on the availability of the shop's database or HTTP API.
    """
    __tablename__ = "catalog_sources"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_catalog_source_project_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    adapter_type: Mapped[str] = mapped_column(String(100), default="workkit_http")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Never return this field from the API. Replace with KMS-backed encryption in production.
    credentials_encrypted: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Limit(Base):
    __tablename__ = "limits"
    __table_args__ = (
        UniqueConstraint("project_id", "direction", "period", "currency", name="uq_limit_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    direction: Mapped[TransactionDirection] = mapped_column(Enum(TransactionDirection))
    period: Mapped[LimitPeriod] = mapped_column(Enum(LimitPeriod))
    currency: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectOperationalPolicy(Base):
    """Configurable anti-abuse/payment-frequency guard for a project."""
    __tablename__ = "project_operational_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), unique=True, index=True)
    amount_min: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("1000"))
    amount_max: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("7000"))
    max_transactions_15m: Mapped[int] = mapped_column(default=15)
    # Rolling request-rate and queue limits. These protect payment creation;
    # completed-payment analytics remains based on succeeded transactions.
    max_transactions_10m: Mapped[int] = mapped_column(default=15, server_default="15")
    max_transactions_hour: Mapped[int] = mapped_column(default=30)
    max_transactions_day: Mapped[int] = mapped_column(default=300, server_default="300")
    # Hard request caps: every newly created payment attempt consumes these,
    # including payments later cancelled or rejected by the provider.
    max_all_transactions_hour: Mapped[int | None] = mapped_column()
    max_all_transactions_day: Mapped[int | None] = mapped_column()
    max_pending_transactions: Mapped[int] = mapped_column(default=50, server_default="50")
    daily_amount_limit: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("100000"), server_default="100000")
    # 0 means that the project does not impose a pause between payments.
    cooldown_minutes: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectProviderRoute(Base):
    """A provider enabled for a concrete project, with its own capacity and schedule."""
    __tablename__ = "project_provider_routes"
    __table_args__ = (
        UniqueConstraint("project_id", "provider_id", "name", name="uq_project_provider_route"),
        Index("ix_provider_routes_project_active", "project_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_providers.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="Основной маршрут")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    priority: Mapped[int] = mapped_column(default=100)
    weight: Mapped[int] = mapped_column(default=100)
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    daily_amount_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    weekly_amount_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    daily_transactions_limit: Mapped[int | None] = mapped_column()
    weekly_transactions_limit: Mapped[int | None] = mapped_column()
    max_transactions_10m: Mapped[int | None] = mapped_column()
    max_transactions_hour: Mapped[int | None] = mapped_column()
    max_all_transactions_hour: Mapped[int | None] = mapped_column()
    max_all_transactions_day: Mapped[int | None] = mapped_column()
    max_pending_transactions: Mapped[int | None] = mapped_column()
    available_from: Mapped[time | None] = mapped_column()
    available_to: Mapped[time | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_transaction_idempotency"),
        Index("ix_transactions_project_created", "project_id", "created_at"),
        Index("ix_transactions_provider_external", "provider_id", "external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_providers.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    # Hosted checkout / QR URL returned by an individual provider adapter.
    payment_url: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    direction: Mapped[TransactionDirection] = mapped_column(Enum(TransactionDirection))
    state: Mapped[TransactionState] = mapped_column(Enum(TransactionState), default=TransactionState.created)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(8))
    settled_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"), server_default="0")
    description: Mapped[str | None] = mapped_column(Text)
    raw_provider_payload: Mapped[dict | None] = mapped_column(JSONB)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Used by reconciliation for direct API payments that do not have an Order.
    last_status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last terminal state successfully delivered to the merchant callback.
    merchant_callback_status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TransactionEvent(Base):
    """Append-only audit log. Do not update or delete events in application code."""
    __tablename__ = "transaction_events"
    __table_args__ = (Index("ix_transaction_events_transaction_created", "transaction_id", "created_at"),)

    id: Mapped[BigInteger] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    previous_state: Mapped[TransactionState | None] = mapped_column(Enum(TransactionState))
    state: Mapped[TransactionState] = mapped_column(Enum(TransactionState))
    actor: Mapped[str] = mapped_column(String(100), default="system")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    """A sellable product kept locally; order creation snapshots its price and fiscal fields."""
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("project_id", "sku", name="uq_product_project_sku"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    sku: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    vat_code: Mapped[int] = mapped_column(default=0)
    payment_subject: Mapped[int] = mapped_column(default=1)
    payment_mode: Mapped[int] = mapped_column(default=4)
    measurement_unit: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Order(Base):
    """Idempotent customer checkout that points to its resulting payment transaction."""
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_order_idempotency"),
        UniqueConstraint("project_id", "external_order_id", name="uq_order_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"), unique=True)
    # Copied from the linked transaction for an idempotent order response.
    payment_url: Mapped[str | None] = mapped_column(Text)
    external_order_id: Mapped[str | None] = mapped_column(String(128))
    external_status_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    reference: Mapped[str] = mapped_column(String(100), unique=True)
    product_snapshot: Mapped[dict] = mapped_column(JSONB)
    quantity: Mapped[int] = mapped_column(default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(30), default="created", server_default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProviderRequestAttempt(Base):
    """Immutable record of every provider creation, status-check, or webhook-verification attempt."""
    __tablename__ = "provider_request_attempts"
    __table_args__ = (Index("ix_provider_attempts_transaction_created", "transaction_id", "created_at"),)

    id: Mapped[BigInteger] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    operation: Mapped[str] = mapped_column(String(50))
    attempt: Mapped[int] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(30))
    request_payload: Mapped[dict | None] = mapped_column(JSONB)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    http_status: Mapped[int | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationRequestLog(Base):
    """Immutable audit record of each valid external-platform order request."""
    __tablename__ = "integration_request_logs"
    id: Mapped[BigInteger] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    external_order_id: Mapped[str | None] = mapped_column(String(128), index=True)
    request_payload: Mapped[dict] = mapped_column(JSONB)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    http_status: Mapped[int] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalCallbackAttempt(Base):
    """Every final-status delivery attempt to the external platform."""
    __tablename__ = "external_callback_attempts"
    __table_args__ = (Index("ix_external_callback_order_created", "order_id", "created_at"),)
    id: Mapped[BigInteger] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    operation: Mapped[str] = mapped_column(String(50), default="payment_status")
    attempt: Mapped[int] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(30))
    request_payload: Mapped[dict] = mapped_column(JSONB)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    http_status: Mapped[int | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportConversation(Base):
    __tablename__ = "support_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_conversations.id"), index=True)
    author_type: Mapped[str] = mapped_column(String(30))  # user, operator, system
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

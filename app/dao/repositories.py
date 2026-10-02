"""DAO layer: only persistence operations and queries; no payment policy lives here."""
import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CatalogSource, ExternalCallbackAttempt, IntegrationRequestLog, Limit, Order, PaymentProvider, Product, Project, ProjectOperationalPolicy, ProjectProviderRoute, ProviderRequestAttempt,
    SupportConversation, SupportMessage, Transaction, TransactionDirection, TransactionEvent, TransactionState, User,
)


class UserDAO:
    @staticmethod
    async def create(session: AsyncSession, user: User) -> User:
        session.add(user)
        await session.flush()
        return user

    @staticmethod
    async def create_many(session: AsyncSession, users: list[User]) -> list[User]:
        """Persistence-only batch insert used by development fixtures."""
        session.add_all(users)
        await session.flush()
        return users

    @staticmethod
    async def get(session: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await session.get(User, user_id)

    @staticmethod
    async def list(session: AsyncSession) -> list[User]:
        return list((await session.scalars(select(User).order_by(User.registered_at.desc()))).all())

    @staticmethod
    async def page(session: AsyncSession, page: int, page_size: int, query: str | None = None) -> tuple[list[User], int]:
        statement = select(User)
        count_statement = select(func.count()).select_from(User)
        if query:
            term = f"%{query.strip()}%"
            filters = (
                User.full_name.ilike(term),
                User.email.ilike(term),
                User.business_name.ilike(term),
                User.phone.ilike(term),
                User.telegram_username.ilike(term),
            )
            statement = statement.where(or_(*filters))
            count_statement = count_statement.where(or_(*filters))
        total = await session.scalar(count_statement) or 0
        users = list((await session.scalars(
            statement.order_by(User.registered_at.desc(), User.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )).all())
        return users, total

    @staticmethod
    async def list_by_email_marker(session: AsyncSession, marker: str) -> Sequence[User]:
        return list((await session.scalars(select(User).where(User.email.ilike(f"%{marker}%")))).all())

    @staticmethod
    async def existing_email_values(session: AsyncSession, emails: Sequence[str]) -> set[str]:
        if not emails:
            return set()
        return set((await session.scalars(
            select(func.lower(User.email)).where(func.lower(User.email).in_(emails))
        )).all())

    @staticmethod
    async def save(session: AsyncSession, user: User) -> User:
        await session.flush()
        return user

    @staticmethod
    async def random_active_with_email(session: AsyncSession) -> User | None:
        """Return a buyer eligible for providers which require an email.

        The pool is intentionally global: it is a panel-owned pool of synthetic
        buyers and is not supplied by the merchant in a payment request.
        """
        return await session.scalar(
            select(User).where(
                User.is_active.is_(True),
                User.email.is_not(None),
                User.email != "",
            ).order_by(func.random()).limit(1)
        )


class ProjectDAO:
    @staticmethod
    async def create(session: AsyncSession, project: Project) -> Project:
        session.add(project)
        await session.flush()
        return project

    @staticmethod
    async def get(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
        return await session.get(Project, project_id)

    @staticmethod
    async def get_by_external_key(session: AsyncSession, external_key: str) -> Project | None:
        return await session.scalar(select(Project).where(Project.external_key == external_key))

    @staticmethod
    async def get_by_external_incoming_token(session: AsyncSession, token: str) -> Project | None:
        return await session.scalar(select(Project).where(Project.external_incoming_token == token))

    @staticmethod
    async def get_for_update(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
        return await session.scalar(select(Project).where(Project.id == project_id).with_for_update())

    @staticmethod
    async def list(session: AsyncSession) -> list[Project]:
        return list((await session.scalars(select(Project).order_by(Project.created_at.desc()))).all())

    @staticmethod
    async def save(session: AsyncSession, project: Project) -> Project:
        await session.flush()
        return project


class ProviderDAO:
    @staticmethod
    async def create(session: AsyncSession, provider: PaymentProvider) -> PaymentProvider:
        session.add(provider)
        await session.flush()
        return provider

    @staticmethod
    async def get_by_code(session: AsyncSession, code: str) -> PaymentProvider | None:
        return await session.scalar(select(PaymentProvider).where(PaymentProvider.code == code))

    @staticmethod
    async def get(session: AsyncSession, provider_id: uuid.UUID) -> PaymentProvider | None:
        return await session.get(PaymentProvider, provider_id)

    @staticmethod
    async def list(session: AsyncSession) -> list[PaymentProvider]:
        return list((await session.scalars(select(PaymentProvider).order_by(PaymentProvider.created_at.desc()))).all())

    @staticmethod
    async def save(session: AsyncSession, provider: PaymentProvider) -> PaymentProvider:
        await session.flush()
        return provider


class CatalogSourceDAO:
    @staticmethod
    async def create(session: AsyncSession, source: CatalogSource) -> CatalogSource:
        session.add(source)
        await session.flush()
        return source

    @staticmethod
    async def get(session: AsyncSession, source_id: uuid.UUID) -> CatalogSource | None:
        return await session.get(CatalogSource, source_id)

    @staticmethod
    async def list_by_project(session: AsyncSession, project_id: uuid.UUID) -> list[CatalogSource]:
        return list((await session.scalars(select(CatalogSource).where(
            CatalogSource.project_id == project_id,
        ).order_by(CatalogSource.created_at.desc()))).all())

    @staticmethod
    async def save(session: AsyncSession, source: CatalogSource) -> CatalogSource:
        await session.flush()
        return source


class LimitDAO:
    @staticmethod
    async def create(session: AsyncSession, limit: Limit) -> Limit:
        session.add(limit)
        await session.flush()
        return limit

    @staticmethod
    async def list_for_scope(
        session: AsyncSession, project_id: uuid.UUID, direction: TransactionDirection, currency: str,
    ) -> list[Limit]:
        return list((await session.scalars(select(Limit).where(
            Limit.project_id == project_id, Limit.direction == direction, Limit.currency == currency, Limit.is_active.is_(True),
        ))).all())

    @staticmethod
    async def list_by_project(session: AsyncSession, project_id: uuid.UUID) -> list[Limit]:
        return list((await session.scalars(select(Limit).where(Limit.project_id == project_id))).all())


class OperationalPolicyDAO:
    @staticmethod
    async def get(session: AsyncSession, project_id: uuid.UUID) -> ProjectOperationalPolicy | None:
        return await session.scalar(select(ProjectOperationalPolicy).where(ProjectOperationalPolicy.project_id == project_id))

    @staticmethod
    async def create(session: AsyncSession, policy: ProjectOperationalPolicy) -> ProjectOperationalPolicy:
        session.add(policy)
        await session.flush()
        return policy

    @staticmethod
    async def save(session: AsyncSession, policy: ProjectOperationalPolicy) -> ProjectOperationalPolicy:
        await session.flush()
        return policy


class ProviderRouteDAO:
    @staticmethod
    async def create(session: AsyncSession, route: ProjectProviderRoute) -> ProjectProviderRoute:
        session.add(route)
        await session.flush()
        return route

    @staticmethod
    async def get(session: AsyncSession, route_id: uuid.UUID) -> ProjectProviderRoute | None:
        return await session.get(ProjectProviderRoute, route_id)

    @staticmethod
    async def list_by_project(session: AsyncSession, project_id: uuid.UUID, *, active_only: bool = False) -> list[ProjectProviderRoute]:
        statement = select(ProjectProviderRoute).where(ProjectProviderRoute.project_id == project_id)
        if active_only:
            statement = statement.where(ProjectProviderRoute.is_active.is_(True))
        return list((await session.scalars(statement.order_by(ProjectProviderRoute.priority, ProjectProviderRoute.created_at))).all())

    @staticmethod
    async def save(session: AsyncSession, route: ProjectProviderRoute) -> ProjectProviderRoute:
        await session.flush()
        return route


class TransactionDAO:
    @staticmethod
    async def create(session: AsyncSession, transaction: Transaction) -> Transaction:
        session.add(transaction)
        await session.flush()
        return transaction

    @staticmethod
    async def get(session: AsyncSession, transaction_id: uuid.UUID) -> Transaction | None:
        return await session.get(Transaction, transaction_id)

    @staticmethod
    async def get_by_idempotency(session: AsyncSession, project_id: uuid.UUID, key: str) -> Transaction | None:
        return await session.scalar(select(Transaction).where(Transaction.project_id == project_id, Transaction.idempotency_key == key))

    @staticmethod
    async def get_by_provider_external_for_update(
        session: AsyncSession, provider_id: uuid.UUID, external_id: str,
    ) -> Transaction | None:
        return await session.scalar(select(Transaction).where(
            Transaction.provider_id == provider_id, Transaction.external_id == external_id,
        ).with_for_update())

    @staticmethod
    async def list_by_project(session: AsyncSession, project_id: uuid.UUID, limit: int) -> list[Transaction]:
        return list((await session.scalars(
            select(Transaction).where(Transaction.project_id == project_id).order_by(Transaction.created_at.desc()).limit(limit)
        )).all())

    @staticmethod
    async def list_operation_rows(session: AsyncSession, project_id: uuid.UUID, limit: int):
        """Payment rows together with the provider and optional originating order.

        Keeping this as one query prevents the panel from doing an N+1 lookup
        for every payment shown in the operations journal.
        """
        return (await session.execute(
            select(
                Transaction, PaymentProvider.code, PaymentProvider.name,
                Order.id, Order.reference, Order.external_order_id,
            )
            .join(PaymentProvider, PaymentProvider.id == Transaction.provider_id)
            .outerjoin(Order, Order.transaction_id == Transaction.id)
            .where(Transaction.project_id == project_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )).all()

    @staticmethod
    async def list_open_without_order(session: AsyncSession, limit: int = 200) -> list[uuid.UUID]:
        """Payments made through the direct API, without an Order wrapper."""
        return list((await session.scalars(
            select(Transaction.id)
            .outerjoin(Order, Order.transaction_id == Transaction.id)
            .where(
                Order.id.is_(None),
                Transaction.external_id.is_not(None),
                Transaction.state.in_((
                    TransactionState.created, TransactionState.pending, TransactionState.processing,
                )),
            )
            .order_by(Transaction.created_at)
            .limit(limit)
        )).all())

    @staticmethod
    async def amount_used(
        session: AsyncSession, project_id: uuid.UUID, direction: TransactionDirection, currency: str,
        since: datetime, counted_states: tuple[TransactionState, ...],
    ) -> Decimal:
        total = await session.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.project_id == project_id, Transaction.direction == direction, Transaction.currency == currency,
            Transaction.state.in_(counted_states), Transaction.created_at >= since,
        ))
        return Decimal(total)

    @staticmethod
    async def count_created_since(session: AsyncSession, project_id: uuid.UUID, since: datetime) -> int:
        return int(await session.scalar(select(func.count(Transaction.id)).where(
            Transaction.project_id == project_id, Transaction.created_at >= since,
        )) or 0)

    @staticmethod
    async def latest_created_at(session: AsyncSession, project_id: uuid.UUID) -> datetime | None:
        return await session.scalar(select(func.max(Transaction.created_at)).where(Transaction.project_id == project_id))

    @staticmethod
    async def provider_usage(
        session: AsyncSession, project_id: uuid.UUID, provider_id: uuid.UUID, since: datetime,
        counted_states: tuple[TransactionState, ...],
    ) -> tuple[Decimal, int]:
        amount, count = (await session.execute(select(
            func.coalesce(func.sum(Transaction.amount), 0), func.count(Transaction.id),
        ).where(
            Transaction.project_id == project_id, Transaction.provider_id == provider_id,
            Transaction.created_at >= since, Transaction.state.in_(counted_states),
        ))).one()
        return Decimal(amount), int(count)

    @staticmethod
    async def dashboard_totals(
        session: AsyncSession, project_id: uuid.UUID, currency: str, start: datetime, end: datetime,
    ) -> tuple[Decimal, Decimal, Decimal, int, int]:
        statement = select(
            func.coalesce(func.sum(Transaction.amount), 0),
            func.coalesce(func.sum(Transaction.settled_amount), 0),
            func.coalesce(func.sum(Transaction.settled_amount - Transaction.fee_amount), 0),
            func.count(Transaction.id),
            func.count(Transaction.id).filter(Transaction.state == TransactionState.succeeded),
        ).where(Transaction.project_id == project_id, Transaction.currency == currency,
                Transaction.created_at >= start, Transaction.created_at <= end)
        paid, credited, margin, count, success_count = (await session.execute(statement)).one()
        return Decimal(paid), Decimal(credited), Decimal(margin), count, success_count


class TransactionEventDAO:
    @staticmethod
    async def append(session: AsyncSession, event: TransactionEvent) -> TransactionEvent:
        session.add(event)
        await session.flush()
        return event

    @staticmethod
    async def list_by_transaction(session: AsyncSession, transaction_id: uuid.UUID) -> list[TransactionEvent]:
        return list((await session.scalars(select(TransactionEvent).where(
            TransactionEvent.transaction_id == transaction_id,
        ).order_by(TransactionEvent.created_at))).all())


class ProductDAO:
    @staticmethod
    async def create(session: AsyncSession, product: Product) -> Product:
        session.add(product)
        await session.flush()
        return product

    @staticmethod
    async def get(session: AsyncSession, product_id: uuid.UUID) -> Product | None:
        return await session.get(Product, product_id)

    @staticmethod
    async def get_by_project_sku(session: AsyncSession, project_id: uuid.UUID, sku: str) -> Product | None:
        return await session.scalar(select(Product).where(Product.project_id == project_id, Product.sku == sku))

    @staticmethod
    async def save(session: AsyncSession, product: Product) -> Product:
        await session.flush()
        return product

    @staticmethod
    async def list_by_project(session: AsyncSession, project_id: uuid.UUID) -> list[Product]:
        return list((await session.scalars(select(Product).where(
            Product.project_id == project_id,
        ).order_by(Product.created_at.desc()))).all())


class OrderDAO:
    @staticmethod
    async def create(session: AsyncSession, order: Order) -> Order:
        session.add(order)
        await session.flush()
        return order

    @staticmethod
    async def get_by_idempotency(session: AsyncSession, project_id: uuid.UUID, key: str) -> Order | None:
        return await session.scalar(select(Order).where(Order.project_id == project_id, Order.idempotency_key == key))

    @staticmethod
    async def get(session: AsyncSession, order_id: uuid.UUID) -> Order | None:
        return await session.get(Order, order_id)

    @staticmethod
    async def get_by_external_id(session: AsyncSession, project_id: uuid.UUID, external_order_id: str) -> Order | None:
        return await session.scalar(select(Order).where(Order.project_id == project_id, Order.external_order_id == external_order_id))

    @staticmethod
    async def get_by_transaction(session: AsyncSession, transaction_id: uuid.UUID) -> Order | None:
        return await session.scalar(select(Order).where(Order.transaction_id == transaction_id))

    @staticmethod
    async def list_open(session: AsyncSession, limit: int = 200) -> list[Order]:
        return list((await session.scalars(select(Order).where(
            Order.status.in_(("created", "pending", "processing")),
        ).order_by(Order.created_at).limit(limit))).all())

    @staticmethod
    async def list_requiring_callback(session: AsyncSession, limit: int = 200) -> list[Order]:
        return list((await session.scalars(select(Order).where(
            Order.external_order_id.is_not(None),
            Order.external_status_notified_at.is_(None),
            Order.status.in_(("succeeded", "failed", "cancelled", "refunded")),
        ).order_by(Order.updated_at).limit(limit))).all())

    @staticmethod
    async def save(session: AsyncSession, order: Order) -> Order:
        await session.flush()
        return order


class ProviderRequestAttemptDAO:
    @staticmethod
    async def append(session: AsyncSession, record: ProviderRequestAttempt) -> ProviderRequestAttempt:
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def list_by_transaction(session: AsyncSession, transaction_id: uuid.UUID) -> list[ProviderRequestAttempt]:
        return list((await session.scalars(select(ProviderRequestAttempt).where(
            ProviderRequestAttempt.transaction_id == transaction_id,
        ).order_by(ProviderRequestAttempt.created_at))).all())


class IntegrationRequestLogDAO:
    @staticmethod
    async def append(session: AsyncSession, record: IntegrationRequestLog) -> IntegrationRequestLog:
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def list_for_external_order(
        session: AsyncSession, project_id: uuid.UUID, external_order_id: str | None,
    ) -> list[IntegrationRequestLog]:
        if not external_order_id:
            return []
        return list((await session.scalars(select(IntegrationRequestLog).where(
            IntegrationRequestLog.project_id == project_id,
            IntegrationRequestLog.external_order_id == external_order_id,
        ).order_by(IntegrationRequestLog.created_at))).all())


class ExternalCallbackAttemptDAO:
    @staticmethod
    async def append(session: AsyncSession, record: ExternalCallbackAttempt) -> ExternalCallbackAttempt:
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def next_attempt_number(session: AsyncSession, order_id: uuid.UUID) -> int:
        value = await session.scalar(select(func.coalesce(func.max(ExternalCallbackAttempt.attempt), 0)).where(
            ExternalCallbackAttempt.order_id == order_id,
        ))
        return int(value or 0) + 1

    @staticmethod
    async def list_by_order(session: AsyncSession, order_id: uuid.UUID | None) -> list[ExternalCallbackAttempt]:
        if not order_id:
            return []
        return list((await session.scalars(select(ExternalCallbackAttempt).where(
            ExternalCallbackAttempt.order_id == order_id,
        ).order_by(ExternalCallbackAttempt.created_at))).all())


class SupportDAO:
    @staticmethod
    async def create_conversation(session: AsyncSession, conversation: SupportConversation) -> SupportConversation:
        session.add(conversation)
        await session.flush()
        return conversation

    @staticmethod
    async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> SupportConversation | None:
        return await session.get(SupportConversation, conversation_id)

    @staticmethod
    async def list_conversations(session: AsyncSession) -> list[SupportConversation]:
        return list((await session.scalars(select(SupportConversation).order_by(SupportConversation.created_at.desc()))).all())

    @staticmethod
    async def list_conversation_summaries(session: AsyncSession) -> list[dict]:
        rows = (await session.execute(
            select(SupportConversation, User.full_name, User.email, User.telegram_username)
            .join(User, User.id == SupportConversation.user_id)
            .order_by(SupportConversation.created_at.desc())
        )).all()
        return [
            {
                "id": conversation.id, "user_id": conversation.user_id, "subject": conversation.subject,
                "status": conversation.status, "created_at": conversation.created_at, "closed_at": conversation.closed_at,
                "user_full_name": full_name, "user_email": email, "user_telegram_username": telegram_username,
            }
            for conversation, full_name, email, telegram_username in rows
        ]

    @staticmethod
    async def create_message(session: AsyncSession, message: SupportMessage) -> SupportMessage:
        session.add(message)
        await session.flush()
        return message

    @staticmethod
    async def create_many(session: AsyncSession, records: list[SupportConversation | SupportMessage]) -> None:
        """Persistence-only batch insert used by development fixtures."""
        session.add_all(records)
        await session.flush()

    @staticmethod
    async def list_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[SupportMessage]:
        return list((await session.scalars(select(SupportMessage).where(
            SupportMessage.conversation_id == conversation_id,
        ).order_by(SupportMessage.created_at))).all())

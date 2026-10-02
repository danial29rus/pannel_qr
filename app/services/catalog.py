import re
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ExternalPlatformConfigUpdate, LimitCreate, ProjectCreate, ProviderCommissionUpdate, ProviderCreate, ProjectCommissionUpdate, UserCreate, UserEmailImport, UserImportResult, UserPage, UserUpdate
from app.dao.repositories import LimitDAO, OperationalPolicyDAO, ProjectDAO, ProviderDAO, UserDAO
from app.db.models import Limit, PaymentProvider, Project, ProjectOperationalPolicy, User
from app.payments.registry import registry


class CatalogService:
    @staticmethod
    async def _commit(session: AsyncSession) -> None:
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Record conflicts with an existing value") from exc

    @classmethod
    async def create_user(cls, session: AsyncSession, payload: UserCreate) -> User:
        user = await UserDAO.create(session, User(**payload.model_dump()))
        await cls._commit(session)
        await session.refresh(user)
        return user

    @staticmethod
    async def list_users(session: AsyncSession, page: int, page_size: int, query: str | None = None) -> UserPage:
        users, total = await UserDAO.page(session, page, page_size, query)
        return UserPage(items=users, total=total, page=page, page_size=page_size, pages=max(1, (total + page_size - 1) // page_size))

    @classmethod
    async def update_user(cls, session: AsyncSession, user_id: uuid.UUID, payload: UserUpdate) -> User:
        user = await UserDAO.get(session, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        for field, value in payload.model_dump().items():
            setattr(user, field, value)
        await UserDAO.save(session, user)
        await cls._commit(session)
        await session.refresh(user)
        return user

    @classmethod
    async def import_user_emails(cls, session: AsyncSession, payload: UserEmailImport) -> UserImportResult:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_email in payload.emails:
            email = raw_email.strip().lower()
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                continue
            if email not in seen:
                seen.add(email)
                normalized.append(email)
        existing = await UserDAO.existing_email_values(session, normalized)
        users = [
            User(
                full_name=f"{payload.full_name_prefix} {payload.start_index + index:06d}",
                email=email,
                business_name=payload.business_name,
            )
            for index, email in enumerate(normalized)
            if email not in existing
        ]
        if users:
            await UserDAO.create_many(session, users)
            await cls._commit(session)
        return UserImportResult(
            created=len(users),
            skipped=len(payload.emails) - len(users),
            total_received=len(payload.emails),
        )

    @classmethod
    async def create_project(cls, session: AsyncSession, payload: ProjectCreate) -> Project:
        if not await UserDAO.get(session, payload.owner_id):
            raise HTTPException(status_code=404, detail="User not found")
        project = await ProjectDAO.create(session, Project(**payload.model_dump()))
        await OperationalPolicyDAO.create(session, ProjectOperationalPolicy(project_id=project.id))
        await cls._commit(session)
        await session.refresh(project)
        return project

    @staticmethod
    async def list_projects(session: AsyncSession) -> list[Project]:
        return await ProjectDAO.list(session)

    @classmethod
    async def set_project_activation(cls, session: AsyncSession, project_id: uuid.UUID, is_active: bool) -> Project:
        project = await ProjectDAO.get(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project.is_active = is_active
        await ProjectDAO.save(session, project)
        await cls._commit(session)
        await session.refresh(project)
        return project

    @classmethod
    async def set_project_commission(cls, session: AsyncSession, project_id: uuid.UUID, payload: ProjectCommissionUpdate) -> Project:
        project = await ProjectDAO.get(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project.default_platform_fee_percent = payload.default_platform_fee_percent
        await ProjectDAO.save(session, project)
        await cls._commit(session)
        await session.refresh(project)
        return project

    @classmethod
    async def set_external_platform_config(cls, session: AsyncSession, project_id: uuid.UUID, payload: ExternalPlatformConfigUpdate) -> Project:
        project = await ProjectDAO.get(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project.external_callback_url = payload.external_callback_url
        project.external_incoming_token = payload.external_incoming_token
        project.external_callback_secret = payload.external_callback_secret
        project.status_check_interval_seconds = payload.status_check_interval_seconds
        project.payment_expiry_minutes = payload.payment_expiry_minutes
        await ProjectDAO.save(session, project)
        await cls._commit(session)
        await session.refresh(project)
        return project

    @classmethod
    async def create_provider(cls, session: AsyncSession, payload: ProviderCreate) -> PaymentProvider:
        try:
            registry.get(payload.adapter_type, {**payload.settings, **payload.credentials_encrypted})
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        provider = await ProviderDAO.create(session, PaymentProvider(**payload.model_dump()))
        await cls._commit(session)
        await session.refresh(provider)
        return provider

    @staticmethod
    async def list_providers(session: AsyncSession) -> list[PaymentProvider]:
        return await ProviderDAO.list(session)

    @classmethod
    async def set_provider_commission(cls, session: AsyncSession, provider_id: uuid.UUID, payload: ProviderCommissionUpdate) -> PaymentProvider:
        provider = await ProviderDAO.get(session, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Payment provider not found")
        provider.provider_fee_percent = payload.provider_fee_percent
        await ProviderDAO.save(session, provider)
        await cls._commit(session)
        await session.refresh(provider)
        return provider

    @classmethod
    async def create_limit(cls, session: AsyncSession, payload: LimitCreate) -> Limit:
        if not await ProjectDAO.get(session, payload.project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        data = payload.model_dump()
        data["currency"] = data["currency"].upper()
        limit = await LimitDAO.create(session, Limit(**data))
        await cls._commit(session)
        await session.refresh(limit)
        return limit

    @staticmethod
    async def list_limits(session: AsyncSession, project_id: uuid.UUID) -> list[Limit]:
        return await LimitDAO.list_by_project(session, project_id)

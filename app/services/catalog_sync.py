from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog_adapters.workkit_sqlite import CatalogAdapterError, WorkKitSqliteAdapter
from app.dao.repositories import CatalogSourceDAO, ProductDAO, ProjectDAO
from app.db.models import CatalogSource, Product


class CatalogSyncService:
    @staticmethod
    async def create_source(session: AsyncSession, payload) -> CatalogSource:
        if not await ProjectDAO.get(session, payload.project_id):
            raise HTTPException(404, "Project not found")
        if payload.adapter_type != "workkit_sqlite":
            raise HTTPException(422, "Only workkit_sqlite is currently supported")
        source = CatalogSource(**payload.model_dump())
        await CatalogSourceDAO.create(session, source)
        await session.commit()
        await session.refresh(source)
        return source

    @staticmethod
    async def list_sources(session: AsyncSession, project_id):
        return await CatalogSourceDAO.list_by_project(session, project_id)

    @staticmethod
    async def set_activation(session: AsyncSession, source_id, is_active: bool) -> CatalogSource:
        source = await CatalogSourceDAO.get(session, source_id)
        if not source:
            raise HTTPException(404, "Catalogue source not found")
        source.is_active = is_active
        await CatalogSourceDAO.save(session, source)
        await session.commit()
        await session.refresh(source)
        return source

    @staticmethod
    async def sync(session: AsyncSession, source_id):
        source = await CatalogSourceDAO.get(session, source_id)
        if not source:
            raise HTTPException(404, "Catalogue source not found")
        if not source.is_active:
            raise HTTPException(422, "Catalogue source is disabled")
        if source.adapter_type != "workkit_sqlite":
            raise HTTPException(422, "Unsupported catalogue source adapter")

        try:
            external_products = WorkKitSqliteAdapter(source.settings).fetch_products()
        except CatalogAdapterError as exc:
            source.last_error = str(exc)
            await CatalogSourceDAO.save(session, source)
            await session.commit()
            raise HTTPException(502, str(exc)) from exc

        created = updated = skipped = 0
        for item in external_products:
            product = await ProductDAO.get_by_project_sku(session, source.project_id, item.sku)
            if product is None:
                await ProductDAO.create(session, Product(
                    project_id=source.project_id, sku=item.sku, name=item.name,
                    description=item.description, price=item.price,
                    currency=str(source.settings.get("currency", "RUB")).upper(),
                    is_active=item.is_active,
                ))
                created += 1
                continue
            if (
                product.name != item.name or product.description != item.description
                or product.price != item.price or product.is_active != item.is_active
            ):
                product.name = item.name
                product.description = item.description
                product.price = item.price
                product.is_active = item.is_active
                await ProductDAO.save(session, product)
                updated += 1
            else:
                skipped += 1

        source.last_synced_at = datetime.now(timezone.utc)
        source.last_error = None
        await CatalogSourceDAO.save(session, source)
        await session.commit()
        return {"source_id": source.id, "created": created, "updated": updated, "skipped": skipped, "synced_at": source.last_synced_at}

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.schemas import UserEmailImport
from app.services.catalog import CatalogService
import app.services.catalog as catalog_service


@pytest.mark.asyncio
async def test_email_import_normalizes_addresses_and_skips_duplicates(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    create_many = AsyncMock()
    monkeypatch.setattr(catalog_service.UserDAO, "existing_email_values", AsyncMock(return_value={"already@example.com"}))
    monkeypatch.setattr(catalog_service.UserDAO, "create_many", create_many)

    result = await CatalogService.import_user_emails(
        session,
        UserEmailImport(
            emails=[" FIRST@example.com ", "first@example.com", "already@example.com", "not-an-email"],
            full_name_prefix="Покупатель",
            business_name="Импорт",
        ),
    )

    assert result.created == 1
    assert result.skipped == 3
    created = create_many.await_args.args[1]
    assert created[0].email == "first@example.com"
    assert created[0].full_name == "Покупатель 000001"
    session.commit.assert_awaited_once()

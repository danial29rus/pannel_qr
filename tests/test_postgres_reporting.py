"""Opt-in integration test. Use a disposable, migrated PostgreSQL database.

TEST_DATABASE_URL=postgresql+asyncpg://... .venv/bin/python -m pytest tests/test_postgres_reporting.py
All inserted fixtures are rolled back; no provider is contacted.
"""
import os
import uuid
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.schemas import TransactionState
from app.dao.repositories import ExternalPaymentRequestDAO, TransactionDAO
from app.db.models import ExternalPaymentRequest, Project, PaymentProvider, Transaction, TransactionDirection, User
from app.db.session import get_session
from app.main import app
from app.services.dashboard import DashboardService


@pytest.mark.asyncio
async def test_real_postgres_reporting_filters_and_api_validation():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable migrated PostgreSQL database")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tx = await connection.begin()
            async with AsyncSession(bind=connection) as session:
                key = uuid.uuid4().hex
                owner = User(full_name="Review owner", business_name="Test")
                session.add(owner)
                await session.flush()
                project = Project(name="Review", external_key=key, owner_id=owner.id)
                other = Project(name="Other", external_key=key + "2", owner_id=owner.id)
                provider = PaymentProvider(code=key, name="Review provider", adapter_type="demo")
                session.add_all([project, other, provider])
                await session.flush()
                start = datetime.fromisoformat("2026-11-16T00:00:00+03:00")
                end = datetime.fromisoformat("2026-11-23T00:00:00+03:00")
                def payment(at, amount, state, **extra):
                    return Transaction(project_id=extra.pop("project_id", project.id), provider_id=provider.id,
                        idempotency_key=uuid.uuid4().hex, direction=TransactionDirection.incoming,
                        created_at=at, amount=Decimal(amount), currency=extra.pop("currency", "RUB"), state=state, **extra)
                first = payment(start, "100", TransactionState.succeeded, external_id="provider-special_42", extra={"merchant_transaction_id":"merchant-123"})
                last = payment(datetime.fromisoformat("2026-11-22T23:59:59+03:00"), "200", TransactionState.succeeded)
                session.add_all([first, last,
                    payment(start, "50", TransactionState.pending),
                    payment(start, "70", TransactionState.failed),
                    payment(end, "900", TransactionState.succeeded),
                    payment(start, "800", TransactionState.succeeded, currency="USD"),
                    payment(start, "700", TransactionState.succeeded, project_id=other.id),
                ])
                await session.flush()
                report = await DashboardService.summary(session, project.id, "rub", start, end)
                assert report.paid_by_clients == Decimal("300")
                assert report.payment_count == 4
                assert (report.success_count, report.pending_count, report.failed_count) == (2, 1, 1)
                assert len(report.daily) == 7
                assert report.daily[0].amount == 100
                assert report.daily[-1].amount == 200
                assert sum(day.amount for day in report.daily) == report.paid_by_clients
                rows, total = await TransactionDAO.page_operation_rows(session, project.id, 1, 10,
                    amount_from=Decimal("100"), amount_to=Decimal("200"), created_from=start, created_to=end,
                    state=TransactionState.succeeded)
                assert total == 2
                assert {row[0].id for row in rows} == {first.id, last.id}
                for term in [str(first.id)[:12], "provider-special_42", "merchant-123"]:
                    rows, total = await TransactionDAO.page_operation_rows(session, project.id, 1, 10, transaction_id=term)
                    assert total == 1
                    assert rows[0][0].id == first.id
                rows, total = await TransactionDAO.page_operation_rows(session, project.id, 1, 10, transaction_id="%")
                assert total == 0  # Search wildcards are literal.
                rows, total = await TransactionDAO.page_operation_rows(session, project.id, 2, 10)
                assert not rows and total == 6
                async def override_session():
                    yield session
                app.dependency_overrides[get_session] = override_session
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        for params in [
                            {"created_from":"2026-11-16T00:00:00", "created_to":end.isoformat()},
                            {"amount_from":"200", "amount_to":"100"},
                            {"created_from":end.isoformat(), "created_to":start.isoformat()},
                        ]:
                            response = await client.get("/api/v1/transactions", params={"project_id":str(project.id), **params})
                            assert response.status_code == 422, response.text
                        response = await client.get("/api/v1/transactions", params={"project_id":str(project.id), "transaction_id":"merchant-123"})
                        assert response.status_code == 200, response.text
                        assert response.json()["total"] == 1
                finally:
                    app.dependency_overrides.clear()
                external_api_payment = payment(
                    start, "100", TransactionState.succeeded,
                    extra={"merchant_transaction_id": str(uuid.uuid4()), "_signed_external_api": True},
                )
                external_api_payment.idempotency_key = f"external-api:{uuid.uuid4()}"
                session.add(external_api_payment)
                await session.flush()
                callbacks = await TransactionDAO.list_requiring_merchant_callback(session)
                assert external_api_payment.id in callbacks
            await tx.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_honestplay_retry_after_rollback_keeps_remote_uuid(monkeypatch):
    """Simulate remote acceptance + lost response, then a fresh local POST."""
    from functools import partial
    from fastapi import HTTPException
    from app.api.schemas import TransactionCreate
    from app.payments.service import PaymentService
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable migrated PostgreSQL database")
    reference = str(uuid.uuid4())
    calls = []
    def handler(req):
        import json
        body = json.loads(req.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(502)  # Upstream may have created the order before failing.
        return httpx.Response(201, json={"uuid":body["uuid"], "amount":body["amount"],
            "status":"pending_payment", "payment_status":"pending", "payment_url":"https://checkout.example.test/pay"})
    original_client = httpx.AsyncClient
    monkeypatch.setattr("app.payments.adapters.honestplay.httpx.AsyncClient", partial(original_client, transport=httpx.MockTransport(handler)))
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
                owner = User(full_name="HonestPlay review", business_name="Test", email=f"{uuid.uuid4().hex}@example.test")
                session.add(owner)
                await session.flush()
                project = Project(owner_id=owner.id, name="HonestPlay test", external_key=uuid.uuid4().hex)
                provider = PaymentProvider(code=uuid.uuid4().hex, name="HonestPlay test", adapter_type="honestplay",
                    settings={"base_url":"https://honestplay.example.test", "max_attempts":1}, credentials_encrypted={"api_key":"test-key"})
                session.add_all([project, provider])
                await session.commit()
                payload = TransactionCreate(project_id=project.id, user_id=owner.id, provider_code=provider.code, amount="100.50", currency="RUB")
                with pytest.raises(HTTPException) as failure:
                    await PaymentService.create(session, payload, reference)
                assert failure.value.status_code == 503
                payment = await PaymentService.create(session, payload, reference)
                assert payment.external_id == reference
                assert payment.payment_url == "https://checkout.example.test/pay"
                assert [item["uuid"] for item in calls] == [reference, reference]
                assert [item["email"] for item in calls] == [owner.email, owner.email]
                await session.rollback()  # End the read scope opened by refresh().
                with pytest.raises(HTTPException) as conflict:
                    await PaymentService.create(session, payload.model_copy(update={"amount":Decimal("200")}), reference)
                assert conflict.value.status_code == 409
                with pytest.raises(HTTPException) as direct_qr:
                    await PaymentService.create(session, payload.model_copy(update={"extra":{"_require_direct_qr":True}}), str(uuid.uuid4()))
                assert direct_qr.value.status_code == 422
                assert len(calls) == 2
            await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_external_payment_reservation_persists_selected_user():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable migrated PostgreSQL database")
    engine = create_async_engine(url)
    project_id = uuid.uuid4()
    transaction_id = uuid.uuid4()
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
                owner = User(full_name="Reservation owner", business_name="Test")
                buyer = User(full_name="Pooled buyer", business_name="Test", email=f"{uuid.uuid4().hex}@example.test")
                session.add_all([owner, buyer])
                await session.flush()
                project = Project(id=project_id, owner_id=owner.id, name="Reservation", external_key=uuid.uuid4().hex)
                session.add(project)
                await session.flush()
                row = ExternalPaymentRequest(
                    project_id=project.id, transaction_id=transaction_id, user_id=buyer.id,
                    amount=Decimal("500"), currency="RUB",
                )
                await ExternalPaymentRequestDAO.create(session, row)
                await session.commit()
                loaded = await ExternalPaymentRequestDAO.get(session, project.id, transaction_id)
                assert loaded is not None
                assert loaded.user_id == buyer.id
                assert loaded.amount == Decimal("500")
                assert loaded.currency == "RUB"
                await session.rollback()
            await outer.rollback()
    finally:
        await engine.dispose()

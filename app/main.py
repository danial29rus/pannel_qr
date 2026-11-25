import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.router import router
from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.jobs.reconciliation import reconcile_open_orders

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Schema changes run only via `alembic upgrade head` before the API starts.
    # This keeps deploys ordered and never makes application startup mutate data.
    if not settings.run_reconciliation_worker:
        yield
        await engine.dispose()
        return
    stop_reconciliation = asyncio.Event()

    async def reconciliation_loop() -> None:
        while not stop_reconciliation.is_set():
            try:
                await reconcile_open_orders()
            except Exception:
                # Per-order failures are audited; this protects the API process
                # from a transient database/network problem in the worker loop.
                logging.getLogger(__name__).exception("Payment reconciliation failed")
            try:
                await asyncio.wait_for(stop_reconciliation.wait(), timeout=max(5, settings.reconciliation_poll_seconds))
            except TimeoutError:
                continue

    reconciliation_task = asyncio.create_task(reconciliation_loop(), name="payment-reconciliation")
    yield
    stop_reconciliation.set()
    await reconciliation_task
    await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix=settings.api_prefix)


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready", tags=["system"])
async def readiness_check():
    try:
        async with SessionLocal() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=5)
    except Exception:
        logging.getLogger(__name__).exception("Database readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}

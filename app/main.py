import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.core.config import get_settings
from app.db.session import engine
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
                pass
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

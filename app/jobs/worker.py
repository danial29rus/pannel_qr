"""Dedicated production worker entrypoint; it does not serve HTTP."""
import asyncio

from app.core.config import get_settings
from app.db.session import engine
from app.jobs.reconciliation import reconcile_open_orders


async def run() -> None:
    settings = get_settings()
    try:
        while True:
            try:
                await reconcile_open_orders()
            except Exception:
                # Individual request/provider errors are written to the audit
                # trail; keep the worker alive for the next pass.
                pass
            await asyncio.sleep(max(5, settings.reconciliation_poll_seconds))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())

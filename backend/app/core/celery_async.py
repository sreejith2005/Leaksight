"""
LeakSight V1 — Celery Async Utilities

Provides a safe way to run async coroutines from sync Celery tasks.
Handles event loop lifecycle and SQLAlchemy async engine disposal
to prevent stale asyncpg connections across task invocations.
"""

import asyncio

from backend.app.core.database import engine


def run_async(coro):
    """Run an async coroutine from a sync Celery task context.

    Creates a new event loop, sets it as current, runs the coroutine,
    disposes the engine's connection pool (to avoid stale connections
    tied to the closing loop), and then closes the loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        # Dispose the engine's connection pool so that stale connections
        # (bound to this loop) are not reused by a future event loop.
        try:
            loop.run_until_complete(engine.dispose())
        except Exception:
            pass
        loop.close()

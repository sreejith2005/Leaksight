"""
LeakSight V1 — FastAPI Application Entry Point

Source: docs/ARCHITECTURE.md, docs/CLAUDE.md, docs/API_CONTRACTS.md

Application startup sequence:
  1. Configure structured logging (structlog with PII sanitization)
  2. Create FastAPI app with metadata
  3. Mount middleware in correct order:
     - RequestLoggingMiddleware (outermost — logs all requests)
     - TenantContextMiddleware (sets tenant context for RLS)
  4. Include API v1 router
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from backend.app.api.router import api_v1_router
from backend.app.core.config import get_settings, validate_production_settings
from backend.app.core.logging import get_logger, setup_logging
from backend.app.core.middleware import (
    RequestLoggingMiddleware,
    TenantContextMiddleware,
)
from backend.app.tools.contract_structuring.router import router as structuring_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown events.

    Startup:
        - Initialize structured logging
        - Log application start

    Shutdown:
        - Log application shutdown
        - Dispose database engine

    Args:
        app: The FastAPI application instance.
    """
    # --- Startup ---
    setup_logging()
    settings = get_settings()
    validate_production_settings(settings)
    logger.info("application_startup", service="leaksight-api", phase="1")

    yield

    # --- Shutdown ---
    from backend.app.core.database import engine

    await engine.dispose()
    logger.info("application_shutdown", service="leaksight-api")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Fully configured FastAPI application with middleware and routes.
    """
    app = FastAPI(
        title="LeakSight V1",
        description=(
            "Post-facto financial verification engine that detects "
            "commercial leakage in vendor transactions."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # --- Middleware ---
    # Mount order matters: outermost middleware is added LAST with Starlette.
    # Starlette processes middleware in reverse-add order, so:
    #   add(TenantContext) first → runs second (inner)
    #   add(RequestLogging) second → runs first (outer)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # --- Routes ---
    app.include_router(api_v1_router)
    app.include_router(
        structuring_router,
        prefix="/api/v1/structuring",
        tags=["Contract Structuring"],
    )

    return app


# Application instance used by uvicorn
app = create_app()

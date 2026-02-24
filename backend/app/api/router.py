"""
LeakSight V1 — API v1 Router

Source: docs/API_CONTRACTS.md, docs/ARCHITECTURE.md, docs/CLAUDE.md

Central router that aggregates all v1 sub-routers under /api/v1/.
All Phase 6 endpoint modules are wired here.
"""

from typing import Any

from fastapi import APIRouter

from backend.app.api.endpoints.admin import router as admin_endpoint_router
from backend.app.api.endpoints.auth import router as auth_endpoint_router
from backend.app.api.endpoints.contracts import router as contracts_endpoint_router
from backend.app.api.endpoints.ingest import router as ingest_endpoint_router
from backend.app.api.endpoints.leakage import router as leakage_endpoint_router
from backend.app.api.endpoints.notifications import router as notifications_endpoint_router
from backend.app.api.endpoints.reports import router as reports_endpoint_router
from backend.app.api.endpoints.vendors import router as vendors_endpoint_router

# --- Master v1 router ---
api_v1_router = APIRouter(prefix="/api/v1")

# --- Health check (immediate, no auth required) ---
health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health_check() -> dict[str, Any]:
    """Application health check endpoint.

    Returns basic application status. Used by Docker health checks,
    load balancers, and monitoring systems. No authentication required.

    Returns:
        JSON with status "ok" and service name.
    """
    return {
        "status": "ok",
        "service": "leaksight-api",
        "version": "1.0.0",
    }


# --- Sub-routers (wired to real endpoint modules) ---
auth_router = APIRouter(prefix="/auth", tags=["auth"])
auth_router.include_router(auth_endpoint_router)

ingest_router = APIRouter(prefix="/ingest", tags=["ingest"])
ingest_router.include_router(ingest_endpoint_router)

leakage_router = APIRouter(prefix="/leakage", tags=["leakage"])
leakage_router.include_router(leakage_endpoint_router)

vendors_router = APIRouter(prefix="/vendors", tags=["vendors"])
vendors_router.include_router(vendors_endpoint_router)

contracts_router = APIRouter(prefix="/contracts", tags=["contracts"])
contracts_router.include_router(contracts_endpoint_router)

reports_router = APIRouter(prefix="/reports", tags=["reports"])
reports_router.include_router(reports_endpoint_router)

admin_router = APIRouter(prefix="/admin", tags=["admin"])
admin_router.include_router(admin_endpoint_router)

notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])
notifications_router.include_router(notifications_endpoint_router)

# --- Include all sub-routers into the master v1 router ---
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(ingest_router)
api_v1_router.include_router(leakage_router)
api_v1_router.include_router(vendors_router)
api_v1_router.include_router(contracts_router)
api_v1_router.include_router(reports_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(notifications_router)

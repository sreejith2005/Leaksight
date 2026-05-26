"""
LeakSight V1 — ASGI Middleware Stack

Source: docs/ARCHITECTURE.md, docs/DATABASE_SCHEMA.md (Section 5 — RLS),
       docs/CLAUDE.md (Logging Convention)

Mount order (outermost first):
  1. RequestLoggingMiddleware — wraps every request with structured logging
  2. TenantContextMiddleware — extracts tenant_id from JWT, sets RLS session var

This ensures all requests (including auth failures) are logged, and tenant
context is available before any DB operations.
"""

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration.

    This middleware wraps all requests and logs structured events using
    structlog. It runs as the outermost middleware so that even requests
    rejected by authentication or tenant validation are logged.

    Fields logged (all in PERMITTED_FIELDS):
        - event: "http_request"
        - method: HTTP method (GET, POST, etc.)
        - path: Request URL path
        - status_code: HTTP response status code
        - duration_ms: Request processing time in milliseconds
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the request and log structured event data.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response from downstream handlers.
        """
        start_time = time.perf_counter()
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            logger.info(
                "http_request",
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

            return response

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            logger.error(
                "http_request_error",
                method=method,
                path=path,
                status_code=500,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )
            raise


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Extract tenant_id from JWT and store it for downstream RLS use.

    This middleware decodes the JWT from the Authorization header,
    extracts tenant_id, and stores it in request.state for use by
    route handlers and database sessions.

    The actual SET LOCAL app.current_tenant_id is executed per-session
    in the database layer, not in middleware, because each DB session
    needs its own transaction-scoped setting.

    Public endpoints (health check, auth/login) are excluded from
    tenant extraction.
    """

    # Paths that do not require JWT / tenant context
    _PUBLIC_PATHS: frozenset[str] = frozenset({
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/token",
        "/docs",
        "/redoc",
        "/openapi.json",
    })

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Extract tenant context from JWT for non-public endpoints.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response from downstream handlers.
        """
        path = request.url.path

        # Skip tenant extraction for public endpoints
        if path in self._PUBLIC_PATHS:
            request.state.tenant_id = None
            request.state.user_id = None
            return await call_next(request)

        # For protected endpoints, extract tenant from JWT
        # Phase 1: tenant extraction is a no-op (JWT not implemented yet)
        # Phase 3 will populate these from decoded JWT payload
        request.state.tenant_id = None
        request.state.user_id = None

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply baseline security headers to every response."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._app_env = get_settings().app_env

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        is_api_route = path.startswith("/api/")

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if self._app_env == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        if is_api_route:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )

        return response

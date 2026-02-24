"""
LeakSight V1 — Authentication Dependencies

Source: docs/API_CONTRACTS.md (Section 1 — Authentication)
       docs/ARCHITECTURE.md (auth dependency injection pattern)

Re-exports get_current_user and CurrentUser for use across all endpoint files.
Provides the oauth2_scheme instance used by the security module.
"""

from backend.app.core.security import (  # noqa: F401
    CurrentUser,
    create_access_token,
    get_current_user,
    oauth2_scheme,
)

__all__ = [
    "CurrentUser",
    "create_access_token",
    "get_current_user",
    "oauth2_scheme",
]

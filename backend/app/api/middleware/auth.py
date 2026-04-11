"""Authentication middleware and tenant context resolver.

Current implementation: pass-through placeholder (no auth enforced).

TODO: implement resolve_tenant_context() for multi-tenant SaaS
---------------------------------------------------------------
This module must expose ``resolve_tenant_context(request) -> TenantContext``
which is called by ``api/middleware/context.py`` (TenantContextMiddleware).

Two modes, selected by ``settings.dev_mode``:

Dev mode (dev_mode=True)
    Read tenant identity directly from HTTP headers – no signature validation.
    This allows local development without an IdP.

    Headers (all optional, fall back to defaults):
        X-Tenant-Id     → TenantContext.tenant_id    (default: "dev")
        X-Workspace-Id  → TenantContext.workspace_id  (default: "ws_default")
        X-User-Id       → TenantContext.user_id       (default: "user_dev")
        X-Session-Id    → TenantContext.session_id    (default: None)

    Example curl::

        curl -H "X-Tenant-Id: acme" \
             -H "X-Workspace-Id: proj_rdkit" \
             -H "X-User-Id: alice" \
             http://localhost:8000/api/v1/chat/stream

Production mode (dev_mode=False)
    Validate ``Authorization: Bearer <token>`` via Microsoft MSAL / Azure AD B2C.
    Extract ``tid`` (tenant ID) and ``oid`` (user object ID) from the JWT claims.
    Look up or create the corresponding Tenant / User rows in PostgreSQL.

    Required configuration (environment variables)::

        AZURE_TENANT_ID      # Azure AD directory (tenant) ID
        AZURE_CLIENT_ID      # App registration client ID
        AZURE_AUTHORITY      # e.g. https://login.microsoftonline.com/{AZURE_TENANT_ID}

    Implementation sketch::

        from msal import ConfidentialClientApplication
        # or use a lightweight JWT validator (python-jose / PyJWT)
        # that fetches the JWKS from AZURE_AUTHORITY + /discovery/v2.0/keys

TODO: implementation steps
    1. Add ``pydantic-settings`` to pyproject.toml and create Settings in
       ``app/core/config/__init__.py`` with ``dev_mode: bool = True``.
    2. Implement ``resolve_tenant_context(request) -> TenantContext``.
    3. Remove / replace the ``auth_middleware`` pass-through below.
    4. Register ``TenantContextMiddleware`` in ``main.py``.

Dependencies (add when implementing):
    production: msal>=1.28 OR python-jose[cryptography]>=3.3
    dev: none (stdlib only)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import Response


async def auth_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Placeholder auth middleware hook for future request authentication."""
    return await call_next(request)
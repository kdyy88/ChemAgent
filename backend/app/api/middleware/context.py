"""TenantContextMiddleware – stamps every request with a TenantContext.

This middleware is the entry point of the multi-tenant isolation chain.
It runs on every HTTP request after CORS and before the route handler.

Request flow
------------
::

    Inbound request
        │
        ▼
    CORSMiddleware            (already registered in main.py)
        │
        ▼
    TenantContextMiddleware   (to be registered in main.py after CORS)
        │  1. calls auth.resolve_tenant_context(request)
        │     → dev_mode: reads X-Tenant-Id / X-Workspace-Id / X-User-Id headers
        │     → prod:     validates Bearer token via MSAL / Azure AD B2C
        │  2. calls set_context(ctx)
        │  3. forwards request
        │  4. calls reset_context(token) in finally block
        ▼
    Route handler / Agent / Store
        │  any code here can call get_current_context() / require_context()
        ▼
    Response

Registration in main.py
-----------------------
::

    from app.api.middleware.context import TenantContextMiddleware

    app.add_middleware(TenantContextMiddleware)   # add AFTER CORSMiddleware

    # Middleware execution in Starlette is LIFO (last added = first executed),
    # so add TenantContextMiddleware AFTER CORSMiddleware to run it BEFORE CORS.
    # Alternatively, add it BEFORE CORS in the source and rely on natural order.

TODO: implement this module
    Dependencies needed: none (stdlib only + app.core.context + app.api.middleware.auth)

    Implementation skeleton::

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from app.core.context import context_scope
        from app.api.middleware.auth import resolve_tenant_context


        class TenantContextMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                ctx = await resolve_tenant_context(request)
                async with context_scope(ctx):
                    return await call_next(request)

    Note: health / readiness endpoints (``/health``, ``/``) may be excluded
    from context injection to avoid failing before auth is wired up::

        EXEMPT_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}

        async def dispatch(self, request, call_next):
            if request.url.path in EXEMPT_PATHS:
                return await call_next(request)
            ctx = await resolve_tenant_context(request)
            async with context_scope(ctx):
                return await call_next(request)
"""

from __future__ import annotations

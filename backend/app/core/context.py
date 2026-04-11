"""Multi-tenant request context based on Python contextvars.

This is the soul of the SaaS isolation layer. Every inbound HTTP request
goes through ``api/middleware/context.py`` which calls ``set_context()`` to
stamp the current async task with a ``TenantContext``.  All downstream code
(stores, infrastructure adapters, workers) calls ``get_current_context()``
to retrieve the context without it being threaded explicitly through every
function signature.

Design overview
---------------
::

    HTTP Request
        │
        ▼
    TenantContextMiddleware          (api/middleware/context.py)
        │  calls auth.resolve_tenant_context()
        │  calls set_context(ctx)
        ▼
    route handler / agent / store    ← get_current_context() anywhere here
        │
        ▼
    infrastructure adapters          ← automatically namespaced by tenant/workspace


Isolation guarantees
--------------------
- Redis keys   : ``{tenant_id}:{workspace_id}:artifact:{id}``
- Local FS     : ``{UPLOAD_ROOT}/{tenant_id}/{workspace_id}/{category}/{id}``
- PostgreSQL   : ``workspace_id`` FK filters on every query
- LangGraph    : ``thread_id = "{tenant_id}:{workspace_id}:{session_id}"``

Worker context restoration
--------------------------
ARQ workers have no HTTP request.  The task payload must carry a
``_tenant_ctx`` dict (tenant_id, workspace_id, user_id, session_id).
``task_runner/worker.py`` calls ``set_context()`` at the start of each job
and ``reset_context()`` when it finishes.

TODO: implement this module
    1. Add dataclass ``TenantContext(tenant_id, workspace_id, user_id, session_id)``
    2. Add ``_ctx_var: ContextVar[TenantContext | None]``
    3. Implement ``get_current_context()``, ``require_context()``,
       ``set_context()``, ``reset_context()``, ``context_scope()``
    Dependencies needed: none (stdlib only – contextvars, dataclasses)
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable snapshot of the current request's tenant/workspace identity.

    Attributes
    ----------
    tenant_id:
        Top-level organisation identifier.  Maps to ``Tenant.id`` in the DB.
    workspace_id:
        Project/workspace within the tenant.  Maps to ``Workspace.id``.
    user_id:
        Authenticated user.  Maps to ``User.id``.
    session_id:
        Active chat session.  Maps to ``Session.id`` / LangGraph thread_id prefix.
        May be ``None`` for non-chat API calls (e.g. file upload).
    """

    tenant_id: str
    workspace_id: str
    user_id: str
    session_id: str | None = None


# ---------------------------------------------------------------------------
# Module-level ContextVar – one per async task / coroutine chain.
# Never share this across threads; asyncio and contextvars handle isolation.
# ---------------------------------------------------------------------------
_ctx_var: ContextVar[TenantContext | None] = ContextVar(
    "tenant_context", default=None
)


def get_current_context() -> TenantContext | None:
    """Return the current ``TenantContext``, or ``None`` if not set.

    Callers that need a guaranteed context should use :func:`require_context`.
    """
    return _ctx_var.get()


def require_context() -> TenantContext:
    """Return the current ``TenantContext``, raising ``RuntimeError`` if absent.

    Use this inside code paths that MUST run under a tenant context (e.g.
    stores, infrastructure adapters).  The middleware guarantees the context
    is set on all authenticated routes, so hitting this error in production
    is a programming mistake, not a user error.
    """
    ctx = _ctx_var.get()
    if ctx is None:
        raise RuntimeError(
            "No TenantContext in scope. "
            "Ensure TenantContextMiddleware is registered and the route is "
            "authenticated, or call set_context() manually in worker tasks."
        )
    return ctx


def set_context(ctx: TenantContext) -> Token:
    """Stamp the current async task with *ctx*.

    Returns the :class:`~contextvars.Token` returned by ``ContextVar.set()``.
    Pass it to :func:`reset_context` to restore the previous value.

    .. code-block:: python

        token = set_context(TenantContext("t1", "ws1", "u1"))
        try:
            ...
        finally:
            reset_context(token)
    """
    return _ctx_var.set(ctx)


def reset_context(token: Token) -> None:
    """Restore the ContextVar to its value before the matching :func:`set_context`."""
    _ctx_var.reset(token)


class context_scope:
    """Async context manager that sets and resets a ``TenantContext``.

    Intended for use in ARQ workers where there is no HTTP middleware::

        async with context_scope(TenantContext("t1", "ws1", "u1")):
            await run_chem_task(...)

    Also usable as a regular ``async with`` in tests.
    """

    def __init__(self, ctx: TenantContext) -> None:
        self._ctx = ctx
        self._token: Token | None = None

    async def __aenter__(self) -> "context_scope":
        self._token = set_context(self._ctx)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._token is not None:
            reset_context(self._token)
            self._token = None

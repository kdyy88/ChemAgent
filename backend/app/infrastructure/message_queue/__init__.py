"""Message queue sub-package – ARQ task queue re-export.

Re-exports the ARQ pool helpers from ``app.core.task_queue`` so new code
imports from a stable infrastructure path::

    # Preferred (new code)
    from app.infrastructure.message_queue import enqueue_task

    # Legacy (still works)
    from app.core.task_queue import enqueue_task

Responsibility: TenantContext serialisation into task payloads
--------------------------------------------------------------
ARQ serialises task kwargs to Redis as JSON.  ``TenantContext`` must be
included so the worker can restore it before running the job.

TODO: implement ``enqueue_task()`` wrapper
    When this module is implemented, replace direct ``arq_pool.enqueue_job()``
    calls with::

        await enqueue_task(
            "run_chem_task",
            task_name=...,
            kwargs=...,
            task_id=...,
            # TenantContext automatically injected from current context:
        )

    The wrapper should:
    1. Call ``get_current_context()`` and serialise it as ``_tenant_ctx`` dict.
    2. Pass it as part of the task kwargs so ``task_runner/worker.py`` can
       reconstruct the context via ``context_scope(TenantContext(**_tenant_ctx))``.

See also: ``services/task_runner/worker.py`` for the consumer side.
"""

from __future__ import annotations

# TODO: uncomment and extend once TenantContext integration is ready
# from app.core.task_queue import enqueue_task as _enqueue_task_raw
# from app.core.context import get_current_context
#
# __all__ = ["enqueue_task"]
#
# async def enqueue_task(task_name: str, **kwargs) -> str:
#     ctx = get_current_context()
#     if ctx is not None:
#         kwargs["_tenant_ctx"] = {
#             "tenant_id": ctx.tenant_id,
#             "workspace_id": ctx.workspace_id,
#             "user_id": ctx.user_id,
#             "session_id": ctx.session_id,
#         }
#     return await _enqueue_task_raw(task_name, **kwargs)

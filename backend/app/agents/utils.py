"""
Backward-compatibility shim.

``app.agents.utils`` has been refactored into focused middleware modules.
All symbols are re-exported from their new homes.

Prefer importing directly from:
  app.agents.middleware.sanitization      — sanitize_messages_for_state,
                                            normalize_messages_for_api,
                                            strip_binary_fields
  app.agents.middleware.workspace         — molecule workspace, task management,
                                            apply_active_smiles_update
  app.core.config                         — build_llm
"""
from __future__ import annotations

from app.agents.middleware.sanitization import (  # noqa: F401
    _OMITTED_TOOL_RESULT,
    _OMITTED_TOOL_RESULT_COMPACT,
    _STRIP_LLM_FIELDS,
    _strip_binary_fields_recursive,
    normalize_messages_for_api,
    sanitize_message_for_state,
    sanitize_messages_for_state,
    strip_binary_fields,
    strip_binary_fields_with_report,
    ToolPostprocessor,
    ToolResult,
)

from app.agents.middleware.workspace import (  # noqa: F401
    _ACTIVE_SMILES_UPDATES,
    _as_string_list,
    _compact_smiles,
    _condense_task_description,
    _TASK_ID_PREFIX_RE,
    _TASK_MAX_LENGTH,
    _TASK_SPLIT_RE,
    _unique_nonempty,
    _workspace_identity,
    apply_active_smiles_update,
    current_smiles_text,
    dispatch_task_update,
    format_molecule_workspace_for_prompt,
    format_tasks_for_prompt,
    merge_molecule_workspace,
    normalize_task_id_reference,
    normalize_tasks,
    parse_tool_output,
    refresh_result,
    resolve_task_id,
    tool_result_to_text,
    update_molecule_workspace,
    update_tasks,
)

from app.core.config import build_llm  # noqa: F401

from app.domain.stores.artifacts import (  # noqa: F401
    get_engine_artifact,
    store_engine_artifact,
)

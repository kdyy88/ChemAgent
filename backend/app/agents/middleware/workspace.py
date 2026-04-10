"""
Molecule workspace and task management utilities for ChemAgent.

Manages the structured ``MoleculeWorkspaceEntry`` dictionary, active SMILES
resolution, and planner-generated task lifecycle (normalize, update, format).
Also contains helpers for tool result parsing and active-SMILES inference.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Sequence, cast
from uuid import uuid4

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig

from app.agents.state import MoleculeWorkspaceEntry, PlannedTaskItem, Task, TaskStatus

logger = logging.getLogger(__name__)

_STRIP_LLM_FIELDS: frozenset[str] = frozenset({
    "image", "structure_image", "highlighted_image",
    "molecule_image", "scaffold_image",
    "sdf_content", "pdbqt_content", "zip_bytes", "atoms",
})

_ACTIVE_SMILES_UPDATES: dict[str, tuple[str, str]] = {
    "tool_strip_salts": ("is_valid", "cleaned_smiles"),
    "tool_pubchem_lookup": ("found", "canonical_smiles"),
    "tool_validate_smiles": ("is_valid", "canonical_smiles"),
    "tool_evaluate_molecule": ("is_valid", "smiles"),
    "tool_murcko_scaffold": ("is_valid", "scaffold_smiles"),
}

_TASK_MAX_LENGTH = 16
_TASK_SPLIT_RE = re.compile(r"[，,；;。:：(（\[]")
_TASK_ID_PREFIX_RE = re.compile(r"^\s*(\d+)\s*(?:[\.．、:：\-\)]\s*.*)?$")

def _condense_task_description(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" -•\t\r\n'\"“”‘’")
    if not cleaned:
        return ""

    condensed = _TASK_SPLIT_RE.split(cleaned, maxsplit=1)[0].strip()
    condensed = re.sub(r"^(步骤\s*\d+|第\s*\d+\s*步)\s*[:：.-]?\s*", "", condensed)
    condensed = condensed.strip(" -•\t\r\n'\"“”‘’")

    if len(condensed) > _TASK_MAX_LENGTH:
        condensed = condensed[:_TASK_MAX_LENGTH].rstrip() + "…"

    return condensed


def _strip_binary_fields_recursive(data: Any, *, path: str = "") -> tuple[Any, list[str]]:
    removed_paths: list[str] = []

    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            next_path = f"{path}.{key}" if path else str(key)
            if key in _STRIP_LLM_FIELDS:
                removed_paths.append(next_path)
                continue
            cleaned_value, nested_removed = _strip_binary_fields_recursive(value, path=next_path)
            cleaned[key] = cleaned_value
            removed_paths.extend(nested_removed)
        return cleaned, removed_paths

    if isinstance(data, list):
        cleaned_list: list[Any] = []
        for index, value in enumerate(data):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            cleaned_value, nested_removed = _strip_binary_fields_recursive(value, path=next_path)
            cleaned_list.append(cleaned_value)
            removed_paths.extend(nested_removed)
        return cleaned_list, removed_paths

    if isinstance(data, tuple):
        cleaned_items: list[Any] = []
        for index, value in enumerate(data):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            cleaned_value, nested_removed = _strip_binary_fields_recursive(value, path=next_path)
            cleaned_items.append(cleaned_value)
            removed_paths.extend(nested_removed)
        return tuple(cleaned_items), removed_paths

    return data, removed_paths


def strip_binary_fields(data: dict) -> dict:
    cleaned, _ = _strip_binary_fields_recursive(data)
    return cast(dict[str, Any], cleaned)


def strip_binary_fields_with_report(data: dict) -> tuple[dict[str, Any], list[str]]:
    cleaned, removed_paths = _strip_binary_fields_recursive(data)
    return cast(dict[str, Any], cleaned), removed_paths


def tool_result_to_text(result: dict) -> str:
    cleaned = strip_binary_fields(result)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


def parse_tool_output(output: Any) -> dict[str, Any] | None:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def current_smiles_text(active_smiles: str | None) -> str:
    return active_smiles or "（无）"


def _compact_smiles(smiles: str, limit: int = 60) -> str:
    normalized = (smiles or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _unique_nonempty(values: Sequence[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _as_string_list(values: Any) -> list[str]:
    return _unique_nonempty(values) if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else []


def _workspace_identity(*, canonical_smiles: str = "", primary_name: str = "", aliases: Sequence[str] | None = None) -> str:
    smiles = canonical_smiles.strip()
    if smiles:
        return f"smiles:{smiles}"

    for candidate in [primary_name, *(aliases or [])]:
        normalized = str(candidate or "").strip().lower()
        if normalized:
            return f"name:{normalized}"

    return ""


def merge_molecule_workspace(
    existing: Sequence[MoleculeWorkspaceEntry] | None,
    incoming: Sequence[MoleculeWorkspaceEntry] | None,
) -> list[MoleculeWorkspaceEntry]:
    merged: list[MoleculeWorkspaceEntry] = [cast(MoleculeWorkspaceEntry, dict(entry)) for entry in (existing or []) if isinstance(entry, dict)]

    for raw_entry in incoming or []:
        if not isinstance(raw_entry, dict):
            continue

        candidate = dict(raw_entry)
        aliases = _as_string_list(candidate.get("aliases"))
        artifact_ids = _as_string_list(candidate.get("artifact_ids"))
        parent_artifact_ids = _as_string_list(candidate.get("parent_artifact_ids"))
        source_tools = _as_string_list(candidate.get("source_tools"))
        primary_name = str(candidate.get("primary_name") or "").strip()
        canonical_smiles = str(candidate.get("canonical_smiles") or "").strip()
        identity = _workspace_identity(
            canonical_smiles=canonical_smiles,
            primary_name=primary_name,
            aliases=aliases,
        )
        if not identity:
            continue

        match_index = next(
            (
                index
                for index, entry in enumerate(merged)
                if _workspace_identity(
                    canonical_smiles=str(entry.get("canonical_smiles") or "").strip(),
                    primary_name=str(entry.get("primary_name") or "").strip(),
                    aliases=entry.get("aliases") or [],
                )
                == identity
            ),
            None,
        )

        base_any: dict[str, Any] = dict(merged.pop(match_index)) if match_index is not None else {"key": identity}
        base_any["key"] = identity
        if primary_name:
            base_any["primary_name"] = primary_name
        if aliases or base_any.get("aliases"):
            base_any["aliases"] = _unique_nonempty([*_as_string_list(base_any.get("aliases")), primary_name, *aliases])
        if canonical_smiles:
            base_any["canonical_smiles"] = canonical_smiles
        for field_name in (
            "isomeric_smiles",
            "formula",
            "molecular_weight",
            "iupac_name",
            "scaffold_smiles",
            "generic_scaffold_smiles",
            "descriptors",
            "lipinski",
            "validation",
        ):
            field_value = candidate.get(field_name)
            if field_value not in (None, "", [], {}):
                base_any[field_name] = field_value
        if artifact_ids or base_any.get("artifact_ids"):
            base_any["artifact_ids"] = _unique_nonempty([*_as_string_list(base_any.get("artifact_ids")), *artifact_ids])
        if parent_artifact_ids or base_any.get("parent_artifact_ids"):
            base_any["parent_artifact_ids"] = _unique_nonempty([*_as_string_list(base_any.get("parent_artifact_ids")), *parent_artifact_ids])
        if source_tools or base_any.get("source_tools"):
            base_any["source_tools"] = _unique_nonempty([*_as_string_list(base_any.get("source_tools")), *source_tools])
        merged.append(cast(MoleculeWorkspaceEntry, base_any))

    return merged


def update_molecule_workspace(
    workspace: Sequence[MoleculeWorkspaceEntry] | None,
    tool_name: str,
    parsed: dict[str, Any] | None,
    args: dict[str, Any] | None = None,
) -> list[MoleculeWorkspaceEntry]:
    if parsed is None:
        return [cast(MoleculeWorkspaceEntry, dict(entry)) for entry in (workspace or []) if isinstance(entry, dict)]

    args = args or {}
    candidate: MoleculeWorkspaceEntry | None = None

    if tool_name == "tool_pubchem_lookup" and parsed.get("found"):
        candidate = cast(MoleculeWorkspaceEntry, {
            "key": "",
            "primary_name": str(parsed.get("name") or args.get("name") or "").strip(),
            "aliases": [str(parsed.get("name") or args.get("name") or "").strip()],
            "canonical_smiles": str(parsed.get("canonical_smiles") or "").strip(),
            "isomeric_smiles": str(parsed.get("isomeric_smiles") or "").strip(),
            "formula": str(parsed.get("formula") or "").strip(),
            "molecular_weight": parsed.get("molecular_weight"),
            "iupac_name": str(parsed.get("iupac_name") or "").strip(),
            "source_tools": [tool_name],
        })
    elif tool_name == "tool_validate_smiles" and parsed.get("is_valid"):
        candidate = cast(MoleculeWorkspaceEntry, {
            "key": "",
            "canonical_smiles": str(parsed.get("canonical_smiles") or "").strip(),
            "formula": str(parsed.get("formula") or "").strip(),
            "validation": {
                "atom_count": parsed.get("atom_count"),
                "heavy_atom_count": parsed.get("heavy_atom_count"),
                "bond_count": parsed.get("bond_count"),
                "ring_count": parsed.get("ring_count"),
                "is_canonical": parsed.get("is_canonical"),
            },
            "source_tools": [tool_name],
        })
    elif tool_name in {"tool_evaluate_molecule", "tool_compute_descriptors"} and parsed.get("is_valid"):
        candidate = cast(MoleculeWorkspaceEntry, {
            "key": "",
            "primary_name": str(parsed.get("name") or args.get("name") or "").strip(),
            "aliases": [str(parsed.get("name") or args.get("name") or "").strip()],
            "canonical_smiles": str(parsed.get("smiles") or "").strip(),
            "formula": str(parsed.get("formula") or "").strip(),
            "artifact_ids": [str(parsed.get("artifact_id") or "").strip()],
            "parent_artifact_ids": [str(parsed.get("parent_artifact_id") or "").strip()],
            "descriptors": parsed.get("descriptors") if isinstance(parsed.get("descriptors"), dict) else None,
            "lipinski": parsed.get("lipinski") if isinstance(parsed.get("lipinski"), dict) else None,
            "validation": parsed.get("validation") if isinstance(parsed.get("validation"), dict) else None,
            "source_tools": [tool_name],
        })
    elif tool_name == "tool_murcko_scaffold" and parsed.get("is_valid"):
        candidate = cast(MoleculeWorkspaceEntry, {
            "key": "",
            "canonical_smiles": str(parsed.get("smiles") or "").strip(),
            "scaffold_smiles": str(parsed.get("scaffold_smiles") or "").strip(),
            "generic_scaffold_smiles": str(parsed.get("generic_scaffold_smiles") or "").strip(),
            "source_tools": [tool_name],
        })
    elif tool_name == "tool_strip_salts" and parsed.get("is_valid"):
        candidate = cast(MoleculeWorkspaceEntry, {
            "key": "",
            "canonical_smiles": str(parsed.get("cleaned_smiles") or "").strip(),
            "formula": str(parsed.get("parent_formula") or "").strip(),
            "validation": {
                "heavy_atom_count": parsed.get("parent_heavy_atoms"),
                "had_salts": parsed.get("had_salts"),
                "charge_neutralized": parsed.get("charge_neutralized"),
            },
            "source_tools": [tool_name],
        })

    if candidate is None:
        return [cast(MoleculeWorkspaceEntry, dict(entry)) for entry in (workspace or []) if isinstance(entry, dict)]

    return merge_molecule_workspace(workspace, [candidate])


def format_molecule_workspace_for_prompt(
    workspace: Sequence[MoleculeWorkspaceEntry] | None,
    active_smiles: str | None,
    limit: int = 6,
) -> str:
    entries: list[MoleculeWorkspaceEntry] = [cast(MoleculeWorkspaceEntry, dict(entry)) for entry in (workspace or []) if isinstance(entry, dict)]
    if not entries:
        return "- 当前没有结构化分子工作集；如涉及多分子比较，请优先把关键工具结果沉淀到状态。"

    def _sort_key(entry: MoleculeWorkspaceEntry) -> tuple[int, int]:
        smiles = str(entry.get("canonical_smiles") or "").strip()
        is_active = int(bool(active_smiles and smiles and smiles == active_smiles))
        return (is_active, len(entry.get("artifact_ids") or []))

    lines = [
        "- 以下为当前结构化分子工作集；当旧工具消息因 history limit 被裁剪时，优先以此表为准。",
    ]
    for entry in sorted(entries, key=_sort_key, reverse=True)[:limit]:
        label = str(entry.get("primary_name") or "").strip() or str(entry.get("canonical_smiles") or "").strip() or "未命名分子"
        parts = [label]
        smiles = str(entry.get("canonical_smiles") or "").strip()
        if smiles:
            prefix = "active_smiles" if active_smiles and smiles == active_smiles else "smiles"
            parts.append(f"{prefix}={_compact_smiles(smiles)}")
        formula = str(entry.get("formula") or "").strip()
        if formula:
            parts.append(f"formula={formula}")
        molecular_weight = entry.get("molecular_weight")
        if molecular_weight not in (None, ""):
            parts.append(f"MW={molecular_weight}")
        scaffold = str(entry.get("scaffold_smiles") or "").strip()
        if scaffold:
            parts.append(f"scaffold={_compact_smiles(scaffold, limit=48)}")
        descriptors = entry.get("descriptors") if isinstance(entry.get("descriptors"), dict) else {}
        if descriptors:
            descriptor_bits = []
            for key in ("log_p", "tpsa", "qed", "sa_score"):
                value = descriptors.get(key)
                if value not in (None, ""):
                    descriptor_bits.append(f"{key}={value}")
            if descriptor_bits:
                parts.append(", ".join(descriptor_bits))
        artifact_ids = entry.get("artifact_ids") or []
        if artifact_ids:
            parts.append(f"artifacts={','.join(artifact_ids[:3])}")
        lines.append("- " + " | ".join(parts))

    if len(entries) > limit:
        lines.append(f"- 其余 {len(entries) - limit} 个分子已省略，请按需要重新查询。")
    return "\n".join(lines)


def format_tasks_for_prompt(tasks: list[Task] | None) -> str:
    if not tasks:
        return "- 当前没有显式任务清单；直接根据用户请求执行即可，无需调用 `tool_update_task_status`。"

    lines = [
        "- 你必须按顺序执行以下任务。",
        "- 调用 `tool_update_task_status` 时，优先直接使用任务列表里的纯数字 `task_id`（例如 `1`、`2`），不要拼接描述文本。",
        "- 如果某项任务会跨多轮推进、需要向前端显示长耗时阶段，开始前再调用 `tool_update_task_status(task_id, \"in_progress\")`。",
        "- 如果你会在当前工作跨度内直接完成该任务，可跳过单独的 `in_progress` 调用，完成后直接标记 `completed` 或 `failed`。",
        "- 完成某项任务后，立即调用 `tool_update_task_status(task_id, \"completed\")`；若已有明确阶段结论，请附带一句 `summary` 记录本阶段产物。",
        "- 如果某项任务无法完成，调用 `tool_update_task_status(task_id, \"failed\")` 并说明原因。",
        "- 已完成任务默认视为锁定；只有在新工具证据、用户补充信息或新的实验结果出现后，才允许重新打开。",
    ]
    for task in tasks:
        lines.append(f"- [{task['status']}] {task['id']}. {task['description']}")
        summary = (task.get("summary") or "").strip()
        if summary:
            lines.append(f"  最近产出: {summary}")
    return "\n".join(lines)


def normalize_tasks(raw_tasks: list[PlannedTaskItem]) -> list[Task]:
    descriptions = []
    for item in raw_tasks:
        condensed = _condense_task_description(item.description)
        if condensed:
            descriptions.append(condensed)

    normalized = descriptions[:5]
    if not normalized:
        normalized = ["分析请求"]
    return [
        {
            "id": str(index),
            "description": description,
            "status": "pending",
        }
        for index, description in enumerate(normalized, start=1)
    ]


def normalize_task_id_reference(task_id: str) -> str:
    normalized = str(task_id or "").strip()
    if not normalized:
        return ""
    matched = _TASK_ID_PREFIX_RE.match(normalized)
    if matched:
        return matched.group(1)
    return normalized


def resolve_task_id(tasks: list[Task], task_id: str) -> str:
    requested = normalize_task_id_reference(task_id)
    if not requested:
        return ""

    task_ids = {str(task["id"]).strip() for task in tasks}
    if requested in task_ids:
        return requested

    raw_requested = str(task_id or "").strip()
    if raw_requested in task_ids:
        return raw_requested

    return requested


def update_tasks(
    tasks: list[Task],
    task_id: str,
    status: TaskStatus,
    evidence_revision: int,
    summary: str | None = None,
) -> tuple[list[Task], Task | None, str | None]:
    resolved_task_id = resolve_task_id(tasks, task_id)
    updated: list[Task] = []
    matched_task: Task | None = None
    ignored_reason: str | None = None
    normalized_summary = (summary or "").strip()

    for task in tasks:
        next_task = dict(task)
        if status == "in_progress" and next_task["status"] == "in_progress" and next_task["id"] != resolved_task_id:
            next_task["status"] = "pending"

        if next_task["id"] == resolved_task_id:
            completion_revision = int(cast(int | str | None, next_task.get("completion_revision")) or -1)
            if (
                next_task["status"] == "completed"
                and status == "in_progress"
                and completion_revision >= evidence_revision
            ):
                matched_task = cast(Task, next_task)
                ignored_reason = "task_already_completed_without_new_evidence"
                updated.append(cast(Task, next_task))
                continue
            next_task["status"] = status
            if status == "completed":
                next_task["completion_revision"] = evidence_revision
                if normalized_summary:
                    next_task["summary"] = normalized_summary
            elif status == "failed" and normalized_summary:
                next_task["summary"] = normalized_summary
            matched_task = cast(Task, next_task)

        updated.append(cast(Task, next_task))

    return updated, matched_task, ignored_reason


async def dispatch_task_update(tasks: list[Task], config: RunnableConfig, source: str) -> None:
    await adispatch_custom_event(
        "task_update",
        {
            "tasks": tasks,
            "source": source,
        },
        config=config,
    )


def refresh_result(
    parsed: ToolResult,
    *,
    required_key: str,
    loader: Callable[[], ToolResult],
) -> ToolResult:
    return parsed if parsed.get(required_key) else loader()


def apply_active_smiles_update(
    tool_name: str,
    parsed: ToolResult,
    current_smiles: str | None,
) -> str | None:
    update_rule = _ACTIVE_SMILES_UPDATES.get(tool_name)
    if update_rule is None:
        return current_smiles

    status_key, smiles_key = update_rule
    return parsed.get(smiles_key) or current_smiles if parsed.get(status_key) else current_smiles



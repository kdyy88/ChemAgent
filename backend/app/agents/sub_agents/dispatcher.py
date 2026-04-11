"""run_sub_agent — Root-Agent Tool for Sub-Agent Delegation
===========================================================

Implements the ``tool_run_sub_agent`` LangChain tool that the root agent uses
to delegate a focused sub-task to an isolated LangGraph sub-graph.

Architecture
------------
Execution model:
  - The tool is called by ``tools_executor_node`` exactly like any other tool.
  - Internally it compiles a fresh ``StateGraph`` for the requested mode,
    sharing the parent's ``AsyncSqliteSaver`` checkpointer.
  - The sub-graph runs under a **deterministic** ``sub_thread_id`` derived from
    the parent thread and the task description.  Determinism is essential for
    HITL resume: the same inputs will find the same checkpoint on re-invocation.

HITL / interrupt propagation:
  - ``explore`` / ``plan`` modes set ``bypass_hitl=True`` → guaranteed zero
    interrupts, so ``ainvoke()`` always returns a terminal state.
  - ``general`` / ``custom`` modes can trigger HEAVY_TOOLS approval gates
    inside the sub-graph.  When ``ainvoke()`` returns with ``"__interrupt__"``
    in the result dict, the tool calls LangGraph's ``interrupt()`` to bubble
    the approval request up to the **parent** graph.  The parent checkpoints
    (SQLite) and surfaces the interrupt to the frontend.
  - On user approval, the parent engine resumes via ``Command(resume=...)``.
    The root ``tools_executor_node`` re-invokes this tool with identical args.
    The deterministic ``sub_thread_id`` finds the persisted sub-graph checkpoint.
    The tool calls ``interrupt()`` again — this time LangGraph's scratchpad
    returns the resume value instead of raising.  That value is forwarded to
    the sub-graph as ``Command(resume=resume_value)``.

Free streaming:
  - The parent ``engine.py`` calls ``graph.astream_events(version="v2")``.
  - This call sets up a ``CallbackManager`` in a contextvar.
  - ``langgraph.config.get_config()`` (called inside the tool) retrieves that
    config, including the active callbacks.
  - Those callbacks are forwarded verbatim to ``sub_graph.ainvoke(config=...)``.
  - LangGraph's ``CallbackManager`` tree then automatically propagates every
    ``on_chat_model_stream`` event from the sub-graph up through the parent's
    event stream.  The frontend sees sub-agent tokens with no additional code.

Timeout:
  - Each sub-graph invocation is bounded by ``_SUB_AGENT_TIMEOUT`` seconds
    (default 120 s) via ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from enum import Enum
from typing import Annotated, Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents.execution_context import extract_execution_context_block, extract_plan_tasks
from app.agents.sub_agents.graph import build_sub_agent_graph, extract_sub_agent_outcome
from app.agents.sub_agents.protocol import (
    AgentToolResult,
    ExitPlanModePayload,
    ReportFailurePayload,
    ScratchpadKind,
    SubAgentDelegation,
    TaskCompletePayload,
    TaskStopPayload,
    format_delegation_prompt,
)
from app.skills.manager import format_skill_listing, load_required_skill_markdown
from app.tools.registry import SubAgentMode, get_tools_for_mode
from app.domain.stores.scratchpad import create_scratchpad_entry

logger = logging.getLogger(__name__)

_INTERRUPT_KEY = "__interrupt__"
_MAX_INLINE_CONTEXT_CHARS = 1_200
_SUB_AGENT_TIMEOUT = 2400.0
_MAX_INHERITED_ARTIFACTS = 10
_GENERAL_MODE_KEYWORDS = re.compile(r"\b(conformer|3d|pdbqt|docking|partial[_ -]?charge|babel|convert)\b", re.IGNORECASE)
_EXPLORE_MODE_KEYWORDS = re.compile(r"\b(scaffold|descriptor|similarity|validate|smiles)\b", re.IGNORECASE)
_DESIGN_TASK_KEYWORDS = re.compile(
    r"\b(design|propose|candidate|scaffold[ _-]?hop|new scaffold|new core|novel|de novo|invent)\b",
    re.IGNORECASE,
)
_FACT_ONLY_TASK_HINTS = re.compile(
    r"(仅做事实调研|只做事实调研|不做任何新分子设计|不设计新分子|不生成任何候选\s*SMILES|不输出任何候选\s*SMILES|仅总结|仅总结与抽取特征|fact[- ]only|facts only|do not design|no new molecules|no candidate smiles)",
    re.IGNORECASE,
)


class SubAgentTaskKind(str, Enum):
    extract_facts = "extract_facts"
    compare_scaffolds = "compare_scaffolds"
    propose_scaffold = "propose_scaffold"
    validate_candidate = "validate_candidate"


class SubAgentOutputContract(str, Enum):
    bullet_summary = "bullet_summary"
    json_findings = "json_findings"
    candidate_package = "candidate_package"


class SubAgentSmilesPolicy(str, Enum):
    forbid_new = "forbid_new"
    allow_verified_only = "allow_verified_only"
    allow_propose_then_validate = "allow_propose_then_validate"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_runtime_ids(*, mode: str, configurable: dict[str, Any]) -> tuple[str, str | None, str | None]:
    if mode == SubAgentMode.plan.value:
        plan_id = str(configurable.get("plan_id") or uuid.uuid4()).strip()
        return f"plan_{plan_id}", plan_id, None

    execution_task_id = str(configurable.get("execution_task_id") or uuid.uuid4()).strip()
    return f"exec_{execution_task_id}", None, execution_task_id


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_SUB_AGENT_VERBOSE_LOGS = _env_truthy("CHEMAGENT_SUB_AGENT_VERBOSE_LOGS", False)


def _infer_required_mode(task: str) -> SubAgentMode | None:
    """Infer a minimum viable sub-agent mode from task semantics."""
    if _GENERAL_MODE_KEYWORDS.search(task):
        return SubAgentMode.general
    if _EXPLORE_MODE_KEYWORDS.search(task):
        return SubAgentMode.explore
    return None


def _mode_rank(mode: SubAgentMode) -> int:
    return {
        SubAgentMode.plan: 0,
        SubAgentMode.explore: 1,
        SubAgentMode.general: 2,
        SubAgentMode.custom: 2,
    }[mode]


def _compact_smiles_for_log(smiles: str, limit: int = 80) -> str:
    normalized = (smiles or "").strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _preview_text(value: str, limit: int = 400) -> str:
    compact = re.sub(r"\s+", " ", (value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + " ...[truncated]"


_EMPTY_SUB_AGENT_REPORT = "子智能体已完成任务，但未产生文本输出。"


def _uses_empty_report_placeholder(text: str) -> bool:
    return not str(text or "").strip() or str(text).strip() == _EMPTY_SUB_AGENT_REPORT


def _format_metrics_block(metrics: dict[str, Any] | None) -> list[str]:
    if not isinstance(metrics, dict) or not metrics:
        return []
    lines = ["Structured results:"]
    for key, value in metrics.items():
        serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        lines.append(f"- {key}: {serialized}")
    return lines


def _build_report_content(
    *,
    final_response: str,
    completion_payload: dict[str, Any] | None,
    produced_artifacts: list[dict],
    advisory_active_smiles: str,
) -> str:
    payload = completion_payload or {}
    status = str(payload.get("status") or "").strip().lower()
    summary = str(payload.get("summary") or "").strip()
    base_text = final_response.strip()
    lines: list[str] = []

    if summary:
        lines.append(summary)
    elif not _uses_empty_report_placeholder(base_text):
        lines.append(base_text)
    elif status == "plan_pending_approval":
        raw_plan = payload.get("plan")
        plan: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
        plan_id = str(plan.get("plan_id") or "").strip()
        lines.append("子智能体已生成待审批计划。")
        if plan_id:
            lines.append(f"plan_id: {plan_id}")
    elif status == "failed":
        lines.append(summary or str(payload.get("error") or "子智能体执行失败。"))
    elif status == "stopped":
        lines.append(summary or str(payload.get("reason") or "子智能体已停止。"))
    else:
        lines.append("子智能体已完成结构化任务。")

    metrics_block = _format_metrics_block(payload.get("metrics") if isinstance(payload.get("metrics"), dict) else None)
    if metrics_block:
        lines.extend(["", *metrics_block])

    artifact_ids = [
        str(artifact_id).strip()
        for artifact_id in list(payload.get("produced_artifact_ids") or [])
        if str(artifact_id).strip()
    ]
    if not artifact_ids:
        artifact_ids = [
            str((artifact or {}).get("artifact_id") or "").strip()
            for artifact in produced_artifacts
            if isinstance(artifact, dict) and str((artifact or {}).get("artifact_id") or "").strip()
        ]
    if artifact_ids:
        lines.extend(["", "Produced artifacts:", *[f"- {artifact_id}" for artifact_id in artifact_ids]])

    if advisory_active_smiles:
        lines.extend(["", f"Suggested active SMILES: {advisory_active_smiles}"])

    return "\n".join(line for line in lines if line is not None).strip() or _EMPTY_SUB_AGENT_REPORT


def _infer_task_kind(task: str) -> SubAgentTaskKind:
    text = task.lower()
    if any(keyword in text for keyword in ("validate", "lipinski", "qed", "descriptors", "评估")):
        return SubAgentTaskKind.validate_candidate
    if any(keyword in text for keyword in ("propose", "design", "scaffold hop", "骨架跃迁", "候选")):
        return SubAgentTaskKind.propose_scaffold
    if any(keyword in text for keyword in ("murcko", "scaffold", "共性", "compare")):
        return SubAgentTaskKind.compare_scaffolds
    return SubAgentTaskKind.extract_facts


def _normalize_enum(value: str | None, enum_cls: type[Enum], default: Enum) -> Enum:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return enum_cls(raw)  # type: ignore[misc]
    except ValueError:
        return default


def _preflight_sub_agent_request(
    *,
    mode: SubAgentMode,
    task: str,
    task_kind: SubAgentTaskKind,
    output_contract: SubAgentOutputContract,
    smiles_policy: SubAgentSmilesPolicy,
) -> tuple[SubAgentMode, dict | None]:
    text = task
    lower_text = text.lower()
    fact_only_request = bool(_FACT_ONLY_TASK_HINTS.search(text))
    explicit_candidate_output = output_contract == SubAgentOutputContract.candidate_package
    explicit_design_task = task_kind == SubAgentTaskKind.propose_scaffold
    validation_requires_candidate = task_kind == SubAgentTaskKind.validate_candidate and not fact_only_request
    asks_for_design = (
        explicit_candidate_output
        or explicit_design_task
        or validation_requires_candidate
        or bool(_DESIGN_TASK_KEYWORDS.search(lower_text))
    ) and not fact_only_request

    if mode == SubAgentMode.explore and asks_for_design:
        if smiles_policy == SubAgentSmilesPolicy.forbid_new:
            return mode, {
                "status": "policy_conflict",
                "mode": mode.value,
                "task_kind": task_kind.value,
                "output_contract": output_contract.value,
                "smiles_policy": smiles_policy.value,
                "summary": "子智能体任务存在策略冲突：当前为 explore 模式，但任务要求设计/候选输出，同时 smiles_policy=forbid_new。",
                "result": "子智能体任务存在策略冲突：当前为 explore 模式，但任务要求设计/候选输出，同时 smiles_policy=forbid_new。",
                "response": "子智能体任务存在策略冲突：当前为 explore 模式，但任务要求设计/候选输出，同时 smiles_policy=forbid_new。",
                "policy_conflicts": [
                    "explore 模式不应承担新骨架设计或候选 SMILES 生成",
                    "smiles_policy=forbid_new 时，不能要求子智能体输出新的候选 SMILES",
                ],
                "needs_followup": True,
                "recommended_mode": SubAgentMode.general.value,
                "recommended_task_kind": SubAgentTaskKind.propose_scaffold.value,
                "produced_artifacts": [],
                "suggested_active_smiles": None,
            }
        return SubAgentMode.general, None

    return mode, None


def _normalize_artifact_pointers(
    requested_artifact_ids: list[str] | None,
    parent_artifact_ids: list[str],
    parent_active_artifact_id: str,
) -> list[str]:
    normalized: list[str] = []
    for artifact_id in requested_artifact_ids or []:
        candidate = str(artifact_id or "").strip()
        if candidate and candidate not in normalized:
            normalized.append(candidate)
    if not normalized:
        for artifact_id in parent_artifact_ids:
            if artifact_id and artifact_id not in normalized:
                normalized.append(artifact_id)
            if len(normalized) >= _MAX_INHERITED_ARTIFACTS:
                break
    if not normalized and parent_active_artifact_id:
        normalized.append(parent_active_artifact_id)
    return normalized[:_MAX_INHERITED_ARTIFACTS]


def _serialize_agent_result(agent_result: AgentToolResult, extras: dict[str, Any] | None = None) -> str:
    payload = agent_result.model_dump(mode="json")
    payload["result"] = agent_result.summary
    payload["response"] = agent_result.summary
    payload["suggested_active_smiles"] = agent_result.advisory_active_smiles
    if extras:
        payload.update(extras)
    return json.dumps(payload, ensure_ascii=False)


def _normalize_delegation_payload(
    *,
    mode: str,
    task: str,
    requested_artifact_ids: list[str] | None,
    parent_thread_id: str,
    sub_thread_id: str,
    parent_active_smiles: str,
    parent_active_artifact_id: str,
    parent_artifact_ids: list[str],
    parent_molecule_workspace_summary: str,
    provided_delegation: dict[str, Any] | SubAgentDelegation | None,
) -> SubAgentDelegation:
    if provided_delegation is not None:
        delegation = (
            provided_delegation
            if isinstance(provided_delegation, SubAgentDelegation)
            else SubAgentDelegation.model_validate(provided_delegation)
        )
        return delegation

    artifact_pointers = _normalize_artifact_pointers(
        requested_artifact_ids,
        parent_artifact_ids,
        parent_active_artifact_id,
    )

    scratchpad_refs: list = []
    inline_context = ""

    return SubAgentDelegation(
        subagent_type=mode,
        task_directive=task,
        artifact_pointers=artifact_pointers,
        scratchpad_refs=scratchpad_refs,
        active_smiles=parent_active_smiles,
        active_artifact_id=parent_active_artifact_id,
        molecule_workspace_summary=parent_molecule_workspace_summary,
        inline_context=inline_context,
    )


# ── Args schema ───────────────────────────────────────────────────────────────


class RunSubAgentArgs(BaseModel):
    delegation: SubAgentDelegation | None = Field(
        default=None,
        description="强类型委派载荷。新调用方应优先提供该字段，而不是继续使用长文本 context。",
    )
    mode: str = Field(
        description=(
            "子智能体工作模式：\n"
            "- explore: 深度调研与特征提取（分子性质、骨架分析、PubChem、联网搜索），不产生需要持久化到 3D 画布的复杂计算中间体\n"
            "- plan:    纯 LLM 推理，生成结构化 Markdown 计划\n"
            "- general: 完整生化计算执行（全量 RDKit + Open Babel 工具）\n"
            "- custom:  使用 custom_tools 白名单和 custom_instructions 自定义指令"
        )
    )
    task: str = Field(
        description="分配给子智能体的明确任务描述。应包含具体目标、分子信息、预期输出格式。",
        min_length=5,
        max_length=1_000,
    )
    artifact_ids: list[str] = Field(
        default_factory=list,
        description="父智能体已生成的工件 ID 列表，子智能体可直接使用其数据，无需重新查询。",
        max_length=_MAX_INHERITED_ARTIFACTS,
    )
    custom_instructions: str = Field(
        default="",
        description="仅 mode=custom 有效：自定义系统指令，完全替换默认 Persona。",
        max_length=2_000,
    )
    custom_tools: list[str] = Field(
        default_factory=list,
        description=(
            "仅 mode=custom 有效：工具名称白名单（如 ['tool_validate_smiles', 'tool_pubchem_lookup']）。"
            "non existent 或被永久禁用的工具会报错。"
        ),
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description=(
            "仅 mode=custom 有效：按需加载的本地 Skill Markdown 名称列表（不带 .md 后缀），"
            "例如 ['rdkit']。"
        ),
    )
    task_kind: str = Field(
        default=SubAgentTaskKind.extract_facts.value,
        description="结构化任务类型：extract_facts / compare_scaffolds / propose_scaffold / validate_candidate。",
    )
    output_contract: str = Field(
        default=SubAgentOutputContract.bullet_summary.value,
        description="期望输出契约：bullet_summary / json_findings / candidate_package。",
    )
    smiles_policy: str = Field(
        default=SubAgentSmilesPolicy.forbid_new.value,
        description="SMILES 生成策略：forbid_new / allow_verified_only / allow_propose_then_validate。",
    )


# ── Tool implementation ────────────────────────────────────────────────────────


@tool(args_schema=RunSubAgentArgs)
async def tool_run_sub_agent(
    mode: str,
    task: str,
    delegation: dict[str, Any] | SubAgentDelegation | None = None,
    artifact_ids: list[str] | None = None,
    custom_instructions: str = "",
    custom_tools: list[str] | None = None,
    required_skills: list[str] | None = None,
    task_kind: str = SubAgentTaskKind.extract_facts.value,
    output_contract: str = SubAgentOutputContract.bullet_summary.value,
    smiles_policy: str = SubAgentSmilesPolicy.forbid_new.value,
) -> str:
    """委派一个明确的子任务给隔离的专项子智能体执行。

    子智能体运行在独立的 LangGraph 线程中，拥有专属工具集和 Persona System Prompt。
    子智能体的 Token 流式输出会实时透传到当前对话气泡中（免费流式传输）。

    **适用场景**
    - mode="explore"：深度调研与特征提取（分子 Lipinski、骨架分析、PubChem 数据、机制文献），不生成需要持久化到 3D 画布的复杂中间体
    - mode="plan"：将复杂实验任务分解为步骤清单（纯 LLM，无工具调用）
    - mode="general"：独立执行多步化学计算（如：净化 → 3D 构象 → PDBQT 全流程）
    - mode="custom"：使用自定义工具集和指令集的专项子智能体

    **约束**
    1. 不要将单工具调用委派给子智能体——直接调用那个工具更高效
    2. 子智能体不能访问当前对话历史；请优先使用 delegation 与 scratchpad refs 传递必要信息
    3. 子智能体不能再委派子任务（depth=1 强制限制）
    """
    # ── Retrieve parent context via LangGraph config ──────────────────────────
    try:
        from langgraph.config import get_config as _lg_get_config  # noqa: PLC0415
        lg_config = _lg_get_config()
    except Exception:
        lg_config = {}

    configurable = lg_config.get("configurable") or {}
    parent_thread_id: str = configurable.get("thread_id", "default")
    callbacks = lg_config.get("callbacks")
    parent_active_smiles = str(configurable.get("parent_active_smiles") or "").strip()
    parent_active_artifact_id = str(configurable.get("parent_active_artifact_id") or "").strip()
    parent_artifact_ids = [
        str(artifact_id).strip()
        for artifact_id in configurable.get("parent_artifact_ids", [])
        if str(artifact_id).strip()
    ]
    parent_molecule_workspace_summary = str(configurable.get("parent_molecule_workspace_summary") or "").strip()

    # ── Resolve mode and filtered tool set ───────────────────────────────────
    try:
        sub_agent_mode = SubAgentMode(mode)
    except ValueError:
        return json.dumps(
            {"status": "error", "error": f"Unknown sub-agent mode: '{mode}'"},
            ensure_ascii=False,
        )

    resolved_task_kind = cast(
        SubAgentTaskKind,
        _normalize_enum(task_kind, SubAgentTaskKind, SubAgentTaskKind.extract_facts),
    )
    resolved_output_contract = cast(
        SubAgentOutputContract,
        _normalize_enum(
        output_contract,
        SubAgentOutputContract,
        SubAgentOutputContract.bullet_summary,
        ),
    )
    resolved_smiles_policy = cast(
        SubAgentSmilesPolicy,
        _normalize_enum(
        smiles_policy,
        SubAgentSmilesPolicy,
        SubAgentSmilesPolicy.forbid_new,
        ),
    )

    inferred_task_kind = _infer_task_kind(task)
    if resolved_task_kind == SubAgentTaskKind.extract_facts and inferred_task_kind != SubAgentTaskKind.extract_facts:
        resolved_task_kind = inferred_task_kind

    sub_agent_mode, preflight_payload = _preflight_sub_agent_request(
        mode=sub_agent_mode,
        task=task,
        task_kind=resolved_task_kind,
        output_contract=resolved_output_contract,
        smiles_policy=resolved_smiles_policy,
    )
    mode = sub_agent_mode.value
    if preflight_payload is not None:
        return json.dumps(preflight_payload, ensure_ascii=False)

    inferred_mode = _infer_required_mode(task)
    if inferred_mode is not None and _mode_rank(inferred_mode) > _mode_rank(sub_agent_mode):
        logger.warning(
            "mode_mismatch suggested=%s used=%s task=%.80s",
            inferred_mode.value,
            sub_agent_mode.value,
            task,
        )
        if _env_truthy("AUTO_UPGRADE_MODE", True):
            sub_agent_mode = inferred_mode
            mode = inferred_mode.value

    # ── Soft preflight: warn if delegation lacks SMILES/artifact context ──────
    _delegation_text = task
    if isinstance(delegation, dict):
        _delegation_text += " " + str(delegation.get("task_directive") or "")
    elif isinstance(delegation, SubAgentDelegation):
        _delegation_text += " " + delegation.task_directive
    _has_smiles_ref = bool(re.search(r"[A-Za-z0-9@+\-\[\]\\/(=#$)]{5,}", _delegation_text))
    _has_artifact_ref = bool(re.search(r"art_[a-f0-9]", _delegation_text))
    if (
        sub_agent_mode in (SubAgentMode.explore, SubAgentMode.general)
        and not _has_smiles_ref
        and not _has_artifact_ref
        and parent_active_smiles
    ):
        logger.warning(
            "Sub-agent delegation lacks SMILES/artifact reference despite parent active_smiles=%s. "
            "Consider including concrete molecular identifiers in task_directive. task=%.120s",
            _compact_smiles_for_log(parent_active_smiles),
            task,
        )

    try:
        filtered_tools = get_tools_for_mode(sub_agent_mode, custom_tools or None)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    skill_markdown = ""
    skill_listing = ""
    if sub_agent_mode == SubAgentMode.custom:
        try:
            skill_markdown = load_required_skill_markdown(required_skills or None)
        except (FileNotFoundError, ValueError) as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    else:
        skill_listing = format_skill_listing(modes=[sub_agent_mode.value])

    # ── Shared checkpointer (MUST be the SQLite instance) ─────────────────────
    try:
        from app.agents.runtime import get_checkpointer  # noqa: PLC0415
        checkpointer = get_checkpointer()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    # ── Build sub-graph ───────────────────────────────────────────────────────
    sub_graph = build_sub_agent_graph(
        sub_agent_mode,
        filtered_tools,
        checkpointer,
        custom_instructions=custom_instructions or "",
        skill_markdown=skill_markdown,
        skill_listing=skill_listing,
    )

    # ── UUID-backed thread isolation ─────────────────────────────────────────
    sub_thread_id, plan_id, execution_task_id = _resolve_runtime_ids(
        mode=mode,
        configurable=configurable,
    )

    normalized_delegation = _normalize_delegation_payload(
        mode=mode,
        task=task,
        requested_artifact_ids=artifact_ids,
        parent_thread_id=parent_thread_id,
        sub_thread_id=sub_thread_id,
        parent_active_smiles=parent_active_smiles,
        parent_active_artifact_id=parent_active_artifact_id,
        parent_artifact_ids=parent_artifact_ids,
        parent_molecule_workspace_summary=parent_molecule_workspace_summary,
        provided_delegation=delegation,
    )

    # Forward parent callbacks for free streaming (LangGraph propagates
    # on_chat_model_stream events from the sub-graph up through astream_events).
    sub_config: dict = {
        "configurable": {
            "thread_id": sub_thread_id,
            "parent_thread_id": parent_thread_id,
            "scratchpad_session_id": parent_thread_id,
            "subagent_phase": "plan" if mode == SubAgentMode.plan.value else "execution",
        },
        "recursion_limit": 256,
    }
    if plan_id is not None:
        sub_config["configurable"]["plan_id"] = plan_id
    if execution_task_id is not None:
        sub_config["configurable"]["execution_task_id"] = execution_task_id
    if callbacks is not None:
        sub_config["callbacks"] = callbacks

    # ── HITL resume detection ─────────────────────────────────────────────────
    # Check whether the sub-graph already has a persisted checkpoint with a
    # pending interrupt.  This is the "second invocation" branch triggered when
    # the parent resumes after the user clicked Approve / Reject / Modify.
    sub_snapshot = await sub_graph.aget_state(
        {"configurable": {"thread_id": sub_thread_id}}
    )
    has_pending_interrupt = bool(sub_snapshot and sub_snapshot.interrupts)

    if has_pending_interrupt:
        # Re-surface the sub-graph's interrupt payload to get the parent's
        # resume decision.  On this (second) invocation, LangGraph's scratchpad
        # returns the resume value instead of raising GraphInterrupt.
        pending = sub_snapshot.interrupts[0]
        pending_payload = pending.value if isinstance(pending.value, dict) else {}
        resume_value = interrupt(
            {
                "type": "sub_agent_approval",
                "sub_thread_id": sub_thread_id,
                **pending_payload,
            }
        )
        # resume_value = {"action": "approve" | "reject" | "modify", "args": {...}}
        sub_input: dict | Command = Command(resume=resume_value)
        if _SUB_AGENT_VERBOSE_LOGS:
            logger.debug(
                "Sub-agent resuming: sub_thread_id=%s action=%s",
                sub_thread_id,
                (resume_value or {}).get("action"),
            )
    else:
        # Fresh run — build initial state for the sub-graph.
        if _SUB_AGENT_VERBOSE_LOGS:
            logger.debug(
                "Sub-agent delegation payload: sub_thread_id=%s mode=%s artifact_pointers=%s parent_active_artifact_id=%s parent_artifact_ids=%s parent_active_smiles=%s inline_context_chars=%d scratchpad_refs=%s task_len=%d",
                sub_thread_id,
                mode,
                normalized_delegation.artifact_pointers,
                parent_active_artifact_id or "",
                [str(artifact_id or "").strip() for artifact_id in (parent_artifact_ids or []) if str(artifact_id or "").strip()],
                _compact_smiles_for_log(parent_active_smiles),
                len(normalized_delegation.inline_context),
                [ref.scratchpad_id for ref in normalized_delegation.scratchpad_refs],
                len(task or ""),
            )
        if _SUB_AGENT_VERBOSE_LOGS:
            logger.debug(
                "Sub-agent normalized delegation: sub_thread_id=%s active_smiles_present=%s scratchpad_refs=%s inline_context_preview=%s workspace_preview=%s",
                sub_thread_id,
                bool(parent_active_smiles),
                [ref.scratchpad_id for ref in normalized_delegation.scratchpad_refs],
                _preview_text(normalized_delegation.inline_context),
                _preview_text(parent_molecule_workspace_summary),
            )
        execution_context = extract_execution_context_block(normalized_delegation.inline_context)
        sub_input = {
            "messages": [HumanMessage(content=format_delegation_prompt(normalized_delegation))],
            "active_smiles": parent_active_smiles or None,
            "artifacts": [],
            "molecule_workspace": [],
            "tasks": extract_plan_tasks(normalized_delegation.inline_context),
            "is_complex": False,
            "sub_agent_result": None,
            "active_subtasks": {},
            "active_subtask_id": None,
            "subtask_control": {"strict_execution": bool(execution_context)},
        }
        if execution_context:
            sub_input["messages"] = [
                SystemMessage(content=execution_context),
                *sub_input["messages"],
            ]
        logger.info(
            "Sub-agent starting: mode=%s sub_thread_id=%s",
            mode,
            sub_thread_id,
        )

    # ── Execute sub-graph ─────────────────────────────────────────────────────
    try:
        result = await asyncio.wait_for(
            sub_graph.ainvoke(sub_input, config=sub_config),  # type: ignore[arg-type]
            timeout=_SUB_AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return _serialize_agent_result(
            AgentToolResult(
                status="timeout",
                mode=mode,
                sub_thread_id=sub_thread_id,
                delegation=normalized_delegation,
                summary=f"子智能体超时（>{_SUB_AGENT_TIMEOUT:.0f}s），任务未完成。",
                error=f"子智能体超时（>{_SUB_AGENT_TIMEOUT:.0f}s），任务未完成。",
            ),
            extras={
                "task_kind": resolved_task_kind.value,
                "output_contract": resolved_output_contract.value,
                "smiles_policy": resolved_smiles_policy.value,
                "needs_followup": True,
            },
        )
    except Exception as exc:
        logger.exception("Sub-agent execution error: sub_thread_id=%s", sub_thread_id)
        return _serialize_agent_result(
            AgentToolResult(
                status="error",
                mode=mode,
                sub_thread_id=sub_thread_id,
                delegation=normalized_delegation,
                summary=str(exc),
                error=str(exc),
            ),
            extras={
                "task_kind": resolved_task_kind.value,
                "output_contract": resolved_output_contract.value,
                "smiles_policy": resolved_smiles_policy.value,
                "needs_followup": True,
            },
        )

    # ── HITL bubble-up (general/custom only; explore/plan bypass_hitl=True) ──
    # If the sub-graph was interrupted by a HEAVY_TOOLS approval gate, delegate
    # the decision to the parent by calling interrupt() here.
    # On the FIRST call: LangGraph raises GraphInterrupt → parent pauses.
    # On RESUME call   : this branch is not reached (has_pending_interrupt=True
    #                    above handles the re-invocation instead).
    if isinstance(result, dict):
        sub_interrupts = result.get(_INTERRUPT_KEY)
        if sub_interrupts:
            pending_int = sub_interrupts[0]
            pending_payload = pending_int.value if isinstance(pending_int.value, dict) else {}
            if _SUB_AGENT_VERBOSE_LOGS:
                logger.debug(
                    "Sub-agent interrupted: sub_thread_id=%s payload=%s",
                    sub_thread_id,
                    pending_payload,
                )
            # This call raises GraphInterrupt on first encounter (parent pauses).
            interrupt(
                {
                    "type": "sub_agent_approval",
                    "sub_thread_id": sub_thread_id,
                    **pending_payload,
                }
            )
            # Unreachable — interrupt() raises. Needed only for static analysis.
            return ""  # type: ignore[return-value]

    # ── Extract and return final response ─────────────────────────────────────
    final_response, produced_artifacts, final_active_smiles, completion_payload = extract_sub_agent_outcome(
        result if isinstance(result, dict) else None
    )
    completion: TaskCompletePayload | None = None
    terminal_status = str((completion_payload or {}).get("status") or "").strip().lower()
    if terminal_status == "completed" and completion_payload is not None:
        completion = TaskCompletePayload.model_validate(
            {
                key: value
                for key, value in completion_payload.items()
                if key in {"summary", "produced_artifact_ids", "metrics", "advisory_active_smiles", "xml_report"}
            }
        )

    advisory_active_smiles = ""
    if completion and completion.advisory_active_smiles.strip():
        advisory_active_smiles = completion.advisory_active_smiles.strip()
    elif final_active_smiles and final_active_smiles != parent_active_smiles:
        advisory_active_smiles = final_active_smiles

    report_content = _build_report_content(
        final_response=final_response,
        completion_payload=completion_payload,
        produced_artifacts=produced_artifacts if isinstance(produced_artifacts, list) else [],
        advisory_active_smiles=advisory_active_smiles,
    )
    report_ref = create_scratchpad_entry(
        session_id=parent_thread_id,
        sub_thread_id=sub_thread_id,
        kind=ScratchpadKind.report,
        content=report_content,
        created_by="sub_agent",
        summary=_preview_text(report_content, limit=160),
        extension="md",
    )

    if _SUB_AGENT_VERBOSE_LOGS:
        logger.debug(
            "Sub-agent outcome payload: sub_thread_id=%s produced_artifacts=%d advisory_active_smiles_present=%s completion_present=%s report_ref=%s response_preview=%s",
            sub_thread_id,
            len(produced_artifacts),
            bool(advisory_active_smiles),
            completion_payload is not None,
            report_ref.scratchpad_id,
            _preview_text(report_content),
        )

    if terminal_status == "plan_pending_approval":
        plan_payload = ExitPlanModePayload.model_validate(completion_payload or {})
        return _serialize_agent_result(
            AgentToolResult(
                status="plan_pending_approval",
                mode=mode,
                sub_thread_id=sub_thread_id,
                execution_task_id=execution_task_id,
                delegation=normalized_delegation,
                plan_pointer=plan_payload.plan,
                scratchpad_report_ref=report_ref,
                summary=plan_payload.summary or report_ref.summary or "子智能体已生成待审批计划。",
            ),
            extras={
                "task_kind": resolved_task_kind.value,
                "output_contract": resolved_output_contract.value,
                "smiles_policy": resolved_smiles_policy.value,
                "needs_followup": True,
            },
        )

    if terminal_status == "failed":
        failure_payload = ReportFailurePayload.model_validate(completion_payload or {})
        return _serialize_agent_result(
            AgentToolResult(
                status="failed",
                mode=mode,
                sub_thread_id=sub_thread_id,
                execution_task_id=execution_task_id,
                delegation=normalized_delegation,
                produced_artifacts=produced_artifacts if isinstance(produced_artifacts, list) else [],
                scratchpad_report_ref=report_ref,
                summary=failure_payload.summary or report_ref.summary or "子智能体执行失败。",
                advisory_active_smiles=advisory_active_smiles or None,
                error=failure_payload.error or failure_payload.summary,
                failure=failure_payload,
            ),
            extras={
                "task_kind": resolved_task_kind.value,
                "output_contract": resolved_output_contract.value,
                "smiles_policy": resolved_smiles_policy.value,
                "needs_followup": True,
            },
        )

    if terminal_status == "stopped":
        stop_payload = TaskStopPayload.model_validate(completion_payload or {})
        return _serialize_agent_result(
            AgentToolResult(
                status="stopped",
                mode=mode,
                sub_thread_id=sub_thread_id,
                execution_task_id=execution_task_id,
                delegation=normalized_delegation,
                produced_artifacts=produced_artifacts if isinstance(produced_artifacts, list) else [],
                scratchpad_report_ref=report_ref,
                summary=stop_payload.summary or report_ref.summary or "子智能体已停止。",
                advisory_active_smiles=advisory_active_smiles or None,
                error=stop_payload.reason,
                failure=stop_payload,
            ),
            extras={
                "task_kind": resolved_task_kind.value,
                "output_contract": resolved_output_contract.value,
                "smiles_policy": resolved_smiles_policy.value,
                "needs_followup": True,
            },
        )

    if completion is None:
        logger.warning(
            "[PROTOCOL ERROR] sub_thread_id=%s mode=%s — sub-agent did not call a terminal protocol tool; report_ref=%s response_len=%d",
            sub_thread_id,
            mode,
            report_ref.scratchpad_id,
            len(final_response),
        )
        return _serialize_agent_result(
            AgentToolResult(
                status="protocol_error",
                mode=mode,
                sub_thread_id=sub_thread_id,
                execution_task_id=execution_task_id,
                delegation=normalized_delegation,
                produced_artifacts=produced_artifacts if isinstance(produced_artifacts, list) else [],
                scratchpad_report_ref=report_ref,
                summary="子智能体未调用终结协议工具，结果未通过强类型终结协议。",
                advisory_active_smiles=advisory_active_smiles or None,
                error="子智能体未调用终结协议工具，结果未通过强类型终结协议。",
            ),
            extras={
                "task_kind": resolved_task_kind.value,
                "output_contract": resolved_output_contract.value,
                "smiles_policy": resolved_smiles_policy.value,
                "needs_followup": True,
            },
        )

    logger.info(
        "Sub-agent complete: sub_thread_id=%s response_len=%d produced_artifacts=%d report_ref=%s advisory_active_smiles=%s",
        sub_thread_id,
        len(final_response),
        len(produced_artifacts),
        report_ref.scratchpad_id,
        _compact_smiles_for_log(advisory_active_smiles),
    )

    return _serialize_agent_result(
        AgentToolResult(
            status="ok",
            mode=mode,
            sub_thread_id=sub_thread_id,
            execution_task_id=execution_task_id,
            delegation=normalized_delegation,
            completion=completion,
            produced_artifacts=produced_artifacts if isinstance(produced_artifacts, list) else [],
            scratchpad_report_ref=report_ref,
            summary=completion.summary or report_ref.summary or "子智能体已完成任务。",
            advisory_active_smiles=advisory_active_smiles or None,
        ),
        extras={
            "task_kind": resolved_task_kind.value,
            "output_contract": resolved_output_contract.value,
            "smiles_policy": resolved_smiles_policy.value,
            "needs_followup": False,
        },
    )

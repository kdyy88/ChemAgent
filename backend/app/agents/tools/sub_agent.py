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
import hashlib
import json
import logging
import os
import re
from enum import Enum
from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents.sub_graph import build_sub_agent_graph, extract_sub_agent_outcome
from app.agents.tool_registry import SubAgentMode, get_tools_for_mode
from app.core.artifact_store import get_engine_artifact

logger = logging.getLogger(__name__)

_INTERRUPT_KEY = "__interrupt__"
_MAX_CONTEXT_CHARS = 8_000
_SUB_AGENT_TIMEOUT = 240.0
_MAX_INHERITED_ARTIFACTS = 10
_GENERAL_MODE_KEYWORDS = re.compile(r"\b(conformer|3d|pdbqt|docking|partial[_ -]?charge|babel|convert)\b", re.IGNORECASE)
_EXPLORE_MODE_KEYWORDS = re.compile(r"\b(scaffold|descriptor|similarity|validate|smiles)\b", re.IGNORECASE)
_MAX_RETURN_RESPONSE_CHARS = 900
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


def _truncate_context(context: str) -> str:
    """Hard-cap context at ``_MAX_CONTEXT_CHARS`` with a visible snip marker."""
    if len(context) <= _MAX_CONTEXT_CHARS:
        return context
    half = _MAX_CONTEXT_CHARS // 2
    snipped = len(context) - _MAX_CONTEXT_CHARS
    return (
        context[:half]
        + f"\n…[上下文已截断，略去 {snipped} 字符]…\n"
        + context[-half:]
    )


def _deterministic_sub_thread_id(parent_thread_id: str, mode: str, task: str) -> str:
    """Hash (parent_thread, mode, task) → stable 16-hex sub_thread_id.

    Determinism ensures that re-invocation after parent HITL resume finds the
    **same** sub-graph checkpoint (same sub_thread_id → same SQLite row).
    """
    key = f"{parent_thread_id}|{mode}|{task}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"sub_{digest}"


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


def _condense_sub_agent_response(response: str, limit: int = _MAX_RETURN_RESPONSE_CHARS) -> str:
    """Reduce verbose sub-agent output to a compact, high-signal summary.

    This condensed text is returned to the parent agent and stored in the main
    conversation history. The full token stream is still shown live to the
    frontend during sub-agent execution, so this step focuses on preserving only
    the stable conclusions needed for downstream reasoning.
    """
    compact = (response or "").strip()
    if not compact:
        return compact

    lines = [line.strip() for line in compact.splitlines() if line.strip()]
    selected: list[str] = []
    saw_heading = False

    for line in lines:
        normalized = re.sub(r"\s+", " ", line)
        if normalized.startswith(("#", "##", "###")):
            saw_heading = True
            selected.append(normalized)
            continue
        if normalized.startswith(("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ")):
            selected.append(normalized)
            continue
        if not saw_heading and len(selected) < 2:
            selected.append(normalized)

    if not selected:
        selected = lines[:6]

    condensed = "\n".join(selected)
    condensed = re.sub(r"\n{3,}", "\n\n", condensed).strip()
    if len(condensed) <= limit:
        return condensed

    truncated = condensed[:limit].rstrip()
    if "\n" in truncated:
        truncated = truncated.rsplit("\n", 1)[0].rstrip()
    return truncated + "\n- 其余细节已省略；如需展开，请查看子智能体流式输出。"


def _infer_task_kind(task: str, context: str) -> SubAgentTaskKind:
    text = f"{task}\n{context}".lower()
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
    context: str,
    task_kind: SubAgentTaskKind,
    output_contract: SubAgentOutputContract,
    smiles_policy: SubAgentSmilesPolicy,
) -> tuple[SubAgentMode, dict | None]:
    text = f"{task}\n{context}"
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
                "result": "子智能体任务存在策略冲突：当前为 explore 模式，但任务要求设计/候选输出，同时 smiles_policy=forbid_new。",
                "response": "子智能体任务存在策略冲突：当前为 explore 模式，但任务要求设计/候选输出，同时 smiles_policy=forbid_new。",
                "findings": [],
                "policy_conflicts": [
                    "explore 模式不应承担新骨架设计或候选 SMILES 生成",
                    "smiles_policy=forbid_new 时，不能要求子智能体输出新的候选 SMILES",
                ],
                "needs_followup": True,
                "recommended_mode": SubAgentMode.general.value,
                "recommended_task_kind": SubAgentTaskKind.propose_scaffold.value,
                "produced_artifacts": [],
                "suggested_active_smiles": None,
                "molecule_workspace": [],
            }
        return SubAgentMode.general, None

    return mode, None


def _build_result_payload(
    *,
    status: str,
    mode: str,
    sub_thread_id: str | None = None,
    task_kind: str,
    output_contract: str,
    smiles_policy: str,
    result_text: str,
    findings: list[str] | None = None,
    candidate_cores: list[dict] | None = None,
    candidate_smiles: list[dict] | None = None,
    policy_conflicts: list[str] | None = None,
    produced_artifacts: list[dict] | None = None,
    suggested_active_smiles: str | None = None,
    molecule_workspace: list[dict] | None = None,
    needs_followup: bool = False,
    error: str | None = None,
    recommended_mode: str | None = None,
    recommended_task_kind: str | None = None,
) -> dict:
    return {
        "status": status,
        "mode": mode,
        "sub_thread_id": sub_thread_id,
        "task_kind": task_kind,
        "output_contract": output_contract,
        "smiles_policy": smiles_policy,
        "result": result_text,
        "response": result_text,
        "findings": findings or [],
        "candidate_cores": candidate_cores or [],
        "candidate_smiles": candidate_smiles or [],
        "policy_conflicts": policy_conflicts or [],
        "needs_followup": needs_followup,
        "recommended_mode": recommended_mode,
        "recommended_task_kind": recommended_task_kind,
        "produced_artifacts": produced_artifacts or [],
        "suggested_active_smiles": suggested_active_smiles,
        "molecule_workspace": molecule_workspace or [],
        "error": error,
    }


def _extract_structured_findings(response: str) -> tuple[list[str], list[dict], list[dict]]:
    findings: list[str] = []
    candidate_cores: list[dict] = []
    candidate_smiles: list[dict] = []

    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            bullet = line[2:].strip()
            findings.append(bullet)
            if "核建议" in bullet or "hinge" in bullet or "喹唑啉" in bullet or "嘧啶" in bullet:
                candidate_cores.append({"label": bullet, "status": "suggested"})
            if "SMILES" in bullet:
                candidate_smiles.append({"label": bullet, "status": "mentioned"})

    return findings[:8], candidate_cores[:4], candidate_smiles[:4]


async def _build_inherited_context_block(
    artifact_ids: list[str],
    parent_active_smiles: str,
    parent_active_artifact_id: str,
    parent_artifact_ids: list[str] | None = None,
    parent_molecule_workspace_summary: str = "",
) -> str:
    """Build a deterministic inherited-context block for the sub-agent."""
    lines: list[str] = ["--- Inherited Artifacts ---"]
    lines.append(f"active_smiles: {parent_active_smiles or 'N/A'}")
    lines.append("artifact_ids:")

    normalized_ids: list[str] = []
    for artifact_id in artifact_ids[:_MAX_INHERITED_ARTIFACTS]:
        normalized = str(artifact_id or "").strip()
        if normalized and normalized not in normalized_ids:
            normalized_ids.append(normalized)

    if not normalized_ids:
        for artifact_id in parent_artifact_ids or []:
            normalized = str(artifact_id or "").strip()
            if normalized and normalized not in normalized_ids:
                normalized_ids.append(normalized)
                if len(normalized_ids) >= _MAX_INHERITED_ARTIFACTS:
                    break

    if not normalized_ids and parent_active_artifact_id:
        normalized_ids.append(parent_active_artifact_id)

    for artifact_id in normalized_ids:
        try:
            record = await get_engine_artifact(artifact_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to resolve inherited artifact %s: %s", artifact_id, exc)
            lines.append(f"  - {artifact_id} (Error: Artifact not found or expired. Please re-compute.)")
            continue

        if not isinstance(record, dict):
            lines.append(f"  - {artifact_id} (Error: Artifact not found or expired. Please re-compute.)")
            continue

        name = str(record.get("name") or record.get("title") or "").strip() or "unnamed"
        canonical_smiles = str(record.get("canonical_smiles") or record.get("smiles") or "").strip()
        if canonical_smiles:
            lines.append(f"  - {artifact_id} ({name}, canonical_smiles: {canonical_smiles})")
        else:
            lines.append(f"  - {artifact_id} ({name}, canonical_smiles: unavailable)")

    if not normalized_ids:
        lines.append("  - (none)")

    if parent_active_smiles and not artifact_ids:
        lines.append(
            f"[System Auto-Inject]: 当前全局活跃分子的 SMILES 为 {parent_active_smiles}，请优先围绕此分子进行操作。"
        )

    if parent_molecule_workspace_summary.strip():
        lines.append("--- Structured Molecule Workspace ---")
        lines.append(parent_molecule_workspace_summary.strip())

    lines.append("注意：以上数据已由父智能体工具调用验证，请直接使用；若已存在可用 SMILES / artifact_id，禁止重复调用 tool_pubchem_lookup。")
    return "\n".join(lines)


# ── Args schema ───────────────────────────────────────────────────────────────


class RunSubAgentArgs(BaseModel):
    mode: str = Field(
        description=(
            "子智能体工作模式：\n"
            "- explore: 深度调研与特征提取（分子性质、骨架分析、PubChem、联网搜索），不产生需要持久化到 3D 画布的复杂计算中间体\n"
            "- plan:    纯 LLM 推理，生成结构化 Markdown 计划，无工具调用\n"
            "- general: 完整生化计算执行（全量 RDKit + Open Babel 工具）\n"
            "- custom:  使用 custom_tools 白名单和 custom_instructions 自定义指令"
        )
    )
    task: str = Field(
        description="分配给子智能体的明确任务描述。应包含具体目标、分子信息、预期输出格式。",
        min_length=5,
        max_length=1_000,
    )
    context: str = Field(
        default="",
        description=(
            "传递给子智能体的背景信息（当前 SMILES、已知实验数据、前置步骤结果等）。"
            "子智能体无法访问当前对话历史——所有必要信息必须在此传入。上限 8000 字符。"
        ),
        max_length=10_000,
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
    context: str = "",
    artifact_ids: list[str] | None = None,
    custom_instructions: str = "",
    custom_tools: list[str] | None = None,
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
    2. 子智能体不能访问当前对话历史，必须在 context 中传入所有必要信息
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

    resolved_task_kind = _normalize_enum(task_kind, SubAgentTaskKind, SubAgentTaskKind.extract_facts)
    resolved_output_contract = _normalize_enum(
        output_contract,
        SubAgentOutputContract,
        SubAgentOutputContract.bullet_summary,
    )
    resolved_smiles_policy = _normalize_enum(
        smiles_policy,
        SubAgentSmilesPolicy,
        SubAgentSmilesPolicy.forbid_new,
    )

    inferred_task_kind = _infer_task_kind(task, context)
    if resolved_task_kind == SubAgentTaskKind.extract_facts and inferred_task_kind != SubAgentTaskKind.extract_facts:
        resolved_task_kind = inferred_task_kind

    sub_agent_mode, preflight_payload = _preflight_sub_agent_request(
        mode=sub_agent_mode,
        task=task,
        context=context,
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

    try:
        filtered_tools = get_tools_for_mode(sub_agent_mode, custom_tools or None)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

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
    )

    # ── Deterministic thread isolation ────────────────────────────────────────
    sub_thread_id = _deterministic_sub_thread_id(parent_thread_id, mode, task)

    # Forward parent callbacks for free streaming (LangGraph propagates
    # on_chat_model_stream events from the sub-graph up through astream_events).
    sub_config: dict = {
        "configurable": {"thread_id": sub_thread_id},
        "recursion_limit": 25,
    }
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
        safe_context = _truncate_context(context or "")
        if _SUB_AGENT_VERBOSE_LOGS:
            logger.debug(
                "Sub-agent delegation payload: sub_thread_id=%s mode=%s explicit_artifact_ids=%s parent_active_artifact_id=%s parent_artifact_ids=%s parent_active_smiles=%s context_len=%d task_len=%d",
                sub_thread_id,
                mode,
                [str(artifact_id or "").strip() for artifact_id in (artifact_ids or []) if str(artifact_id or "").strip()],
                parent_active_artifact_id or "",
                [str(artifact_id or "").strip() for artifact_id in (parent_artifact_ids or []) if str(artifact_id or "").strip()],
                _compact_smiles_for_log(parent_active_smiles),
                len(context or ""),
                len(task or ""),
            )
        inherited_context = await _build_inherited_context_block(
            artifact_ids or [],
            parent_active_smiles,
            parent_active_artifact_id,
            parent_artifact_ids,
            parent_molecule_workspace_summary,
        )
        task_msg = task
        inherited_sections: list[str] = []
        if inherited_context:
            inherited_sections.append(inherited_context)
        if safe_context:
            inherited_sections.append(f"上下文:\n{safe_context}")
        if inherited_sections:
            task_msg = f"{task}\n\n" + "\n\n".join(inherited_sections)
        if _SUB_AGENT_VERBOSE_LOGS:
            logger.debug(
                "Sub-agent inherited state: sub_thread_id=%s requested_artifact_ids=%s parent_active_artifact_id=%s parent_artifact_ids=%s active_smiles_present=%s inherited_context_chars=%d context_chars=%d inherited_context_preview=%s context_preview=%s",
                sub_thread_id,
                artifact_ids or [],
                parent_active_artifact_id or "",
                parent_artifact_ids or [],
                bool(parent_active_smiles),
                len(inherited_context),
                len(safe_context),
                _preview_text(inherited_context),
                _preview_text(safe_context),
            )
        sub_input = {
            "messages": [HumanMessage(content=task_msg)],
            "active_smiles": parent_active_smiles or None,
            "artifacts": [],
            "molecule_workspace": [],
            "tasks": [],
            "is_complex": False,
        }
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
        return json.dumps(
            _build_result_payload(
                status="timeout",
                mode=mode,
                task_kind=resolved_task_kind.value,
                output_contract=resolved_output_contract.value,
                smiles_policy=resolved_smiles_policy.value,
                result_text=f"子智能体超时（>{_SUB_AGENT_TIMEOUT:.0f}s），任务未完成。",
                needs_followup=True,
                error=f"子智能体超时（>{_SUB_AGENT_TIMEOUT:.0f}s），任务未完成。",
            ),
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("Sub-agent execution error: sub_thread_id=%s", sub_thread_id)
        return json.dumps(
            _build_result_payload(
                status="error",
                mode=mode,
                sub_thread_id=sub_thread_id,
                task_kind=resolved_task_kind.value,
                output_contract=resolved_output_contract.value,
                smiles_policy=resolved_smiles_policy.value,
                result_text=str(exc),
                needs_followup=True,
                error=str(exc),
            ),
            ensure_ascii=False,
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
    final_response, produced_artifacts, final_active_smiles, molecule_workspace = extract_sub_agent_outcome(
        result if isinstance(result, dict) else None
    )
    condensed_response = _condense_sub_agent_response(final_response)
    findings, candidate_cores, candidate_smiles = _extract_structured_findings(condensed_response)
    suggested_active_smiles = None
    if final_active_smiles and final_active_smiles != parent_active_smiles:
        suggested_active_smiles = final_active_smiles

    if _SUB_AGENT_VERBOSE_LOGS:
        logger.debug(
            "Sub-agent outcome payload: sub_thread_id=%s produced_artifacts=%d suggested_active_smiles_present=%s final_active_smiles_changed=%s response_preview=%s",
            sub_thread_id,
            len(produced_artifacts),
            bool(suggested_active_smiles),
            final_active_smiles != parent_active_smiles,
            _preview_text(condensed_response),
        )

    logger.info(
        "Sub-agent complete: sub_thread_id=%s response_len=%d produced_artifacts=%d suggested_active_smiles=%s",
        sub_thread_id,
        len(condensed_response),
        len(produced_artifacts),
        _compact_smiles_for_log(suggested_active_smiles or ""),
    )

    return json.dumps(
        _build_result_payload(
            status="ok",
            mode=mode,
            sub_thread_id=sub_thread_id,
            task_kind=resolved_task_kind.value,
            output_contract=resolved_output_contract.value,
            smiles_policy=resolved_smiles_policy.value,
            result_text=condensed_response,
            findings=findings,
            candidate_cores=candidate_cores,
            candidate_smiles=candidate_smiles,
            produced_artifacts=produced_artifacts if isinstance(produced_artifacts, list) else [],
            suggested_active_smiles=suggested_active_smiles,
            molecule_workspace=molecule_workspace if isinstance(molecule_workspace, list) else [],
            needs_followup=False,
        ),
        ensure_ascii=False,
    )

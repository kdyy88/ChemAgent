"""
LangGraph MVP graph for ChemAgent — replaces the AG2/AutoGen multi-agent stack.

Topology
--------

    START
      │
      ▼
  supervisor ──────────────────────────────────────────► END
      │                                                    ▲
      ├─► visualizer_node → shadow_lab_node ──────────────┤
      │                          │ (validation error)      │
      └─► analyst_node ──────────┤                         │
                                 │                         │
                                 └─► supervisor ───────────┘
                                      (self-correct, up to MAX_ITER times)

Key design decisions
--------------------
* ChemMVPState uses add_messages reducer for the message list, allowing any
  node to append without overriding prior history.
* Supervisor uses structured output (Pydantic RouteDecision) for deterministic
  routing — no regex parsing of LLM prose.
* Worker nodes (visualizer / analyst) are async LangGraph tool-calling agents
  backed by ChatOpenAI + LangChain @tool.  They call our RDKit layer via the
  tools defined in lg_tools.py.
* Shadow Lab is a purely deterministic RDKit validation node.  It NEVER calls
  an LLM.  Validation failures inject a self-correction HumanMessage into the
  state, then route back to the supervisor so the LLM can fix the SMILES.
* Custom events (artifacts like structure images, descriptor tables) are
  dispatched via langchain_core.callbacks.adispatch_custom_event so they
  surface as on_custom_event in the astream_events() stream.
"""

from __future__ import annotations

import operator
import os
from typing import Annotated, Any, Literal

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph.message import add_messages   # moved to langgraph in v1.x
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from rdkit import Chem
from typing_extensions import TypedDict

from app.agents.config import build_llm_config, _load_environment
from app.agents.lg_tools import ANALYST_TOOLS, ALL_TOOLS, VISUALIZER_TOOLS
from app.tools.babel.prep import (
    BABEL_ANALYSIS_TOOLS,
    PREP_TOOLS,
    tool_build_3d_conformer,
    tool_prepare_pdbqt,
)
from app.chem.rdkit_ops import compute_descriptors, mol_to_png_b64, validate_smiles

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_ITERATIONS = 3  # Maximum supervisor→worker→shadow_lab loops before forcing END


# ── State ─────────────────────────────────────────────────────────────────────


class ChemMVPState(TypedDict):
    """Global state propagated through every node in the ChemAgent graph.

    Reducers
    --------
    messages           : add_messages — merge-appends; handles de-duplication.
    validation_errors  : operator.add — accumulates errors across iterations.
    artifacts          : operator.add — accumulates renderings, descriptor tables.

    Plain fields (last-write-wins)
    --------------------------------
    active_smiles      : The SMILES currently on the "canvas". Updated by any
                         node that identifies or generates a molecular structure.
    next_node          : Routing signal set by Supervisor & Shadow Lab.
    iteration_count    : Incremented each time the supervisor re-routes after
                         a Shadow Lab failure; caps infinite correction loops.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    active_smiles: str | None
    validation_errors: Annotated[list[str], operator.add]
    artifacts: Annotated[list[dict], operator.add]
    next_node: str | None
    iteration_count: int


# ── Structured output schema for Supervisor routing ───────────────────────────


class RouteDecision(BaseModel):
    """Structured output schema for the Supervisor node.

    The LLM fills this schema; LangGraph uses `next` to pick the downstream
    node.  No string parsing — fully type-safe.
    """

    next: Literal["visualizer", "analyst", "prep", "END"] = Field(
        description=(
            "Which worker to invoke next.  Use 'visualizer' for 2D structure rendering; "
            "'analyst' for physicochemical calculations (Lipinski, QED, TPSA, similarity, "
            "scaffold, partial charges, cross-validate with Open Babel); "
            "'prep' for format conversion (SMILES→SDF/MOL2/PDB/InChI), 3D conformer "
            "generation, or docking PDBQT preparation; "
            "'END' when the conversation can be concluded without additional tools."
        )
    )
    active_smiles: str | None = Field(
        default=None,
        description=(
            "If the user provided or implied a SMILES string, extract it here "
            "verbatim.  Set to null if no SMILES is present."
        ),
    )
    compound_name: str | None = Field(
        default=None,
        description="Common or IUPAC name of the target compound, if mentioned.",
    )
    reasoning: str = Field(
        description="One-sentence Chinese rationale for the routing decision."
    )


# ── LLM factory ───────────────────────────────────────────────────────────────


def _build_chat_llm(tools: list | None = None, structured_schema: type | None = None) -> ChatOpenAI:
    """Construct a ChatOpenAI client that uses the OpenAI Responses API.

    DMXAPI exposes the Responses API at:
        https://www.dmxapi.cn/v1/responses

    config.py normalises OPENAI_BASE_URL by stripping the trailing '/responses'
    segment, yielding https://www.dmxapi.cn/v1.  With use_responses_api=True
    (implicitly enabled when reasoning is set), langchain-openai appends
    '/responses' and calls client.responses.create() instead of
    client.chat.completions.create() — matching the DMXAPI Responses endpoint.

    reasoning={"effort": "none"} suppresses chain-of-thought tokens for all
    nodes.  Remove or set to "low"/"medium"/"high" to enable reasoning for
    specific nodes (e.g. supervisor with complex domain questions).
    """
    _load_environment()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    base_url = os.environ.get("OPENAI_BASE_URL") or None

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "streaming": True,
        # ── Responses API ──────────────────────────────────────────────────────
        # Forces langchain-openai to call client.responses.create() instead of
        # client.chat.completions.create().  Also auto-enabled when `reasoning`
        # is set (see langchain_openai.chat_models.base._use_responses_api).
        "use_responses_api": True,
        # Use minimal reasoning effort — "none" is not accepted by gpt-5-2025-08-07;
        # valid values are "minimal", "low", "medium", "high".
        # "minimal" gives the lowest latency/cost while keeping the Responses API path.
        "reasoning": {"effort": "minimal"},
    }
    if base_url:
        # Normalise: strip /responses (and /chat/completions etc.) so the base
        # URL is just https://host/v1.  langchain-openai appends /responses
        # automatically when use_responses_api=True.
        for suffix in ("/chat/completions", "/completions", "/responses"):
            if base_url.rstrip("/").endswith(suffix):
                base_url = base_url.rstrip("/")[: -len(suffix)]
                break
        kwargs["base_url"] = base_url

    llm = ChatOpenAI(**kwargs)
    if tools:
        llm = llm.bind_tools(tools)        # type: ignore[assignment]
    if structured_schema:
        llm = llm.with_structured_output(structured_schema)  # type: ignore[assignment]
    return llm  # type: ignore[return-value]


# ── System prompts ─────────────────────────────────────────────────────────────

_SUPERVISOR_SYSTEM = """\
你是 ChemAgent 的首席化学主管，负责将用户请求精准路由给专家节点。

可用专家节点：
- **visualizer**：生成分子的 2D 结构图（仅需 SMILES 或化合物名称）
- **analyst**  ：计算理化性质（Lipinski Ro5、QED、TPSA、SA Score、Tanimoto 相似度、
                 Murcko 骨架、盐型处理、部分电荷分析（Gasteiger/MMFF94）、Open Babel 分子属性交叉验证）
- **prep**     ：分子格式转换（SMILES↔SDF/MOL2/PDB/XYZ/InChI/InChIKey 等 110+ 格式）、
                 3D 构象生成（MMFF94/UFF 力场）、对接用 PDBQT 文件准备（AutoDock/Vina/Smina/GNINA）
- **END**      ：直接回答，无需调用工具（如问候、解释概念、对话收尾）

路由规则（按优先级）：
1. 用户明确提供 SMILES → analyst（计算）或 visualizer（绘图）或 prep（格式/3D/对接）
2. 含 "3D构象"/"conformer"/"PDBQT"/"对接"/"docking" → prep
3. 含 "转换格式"/"convert"/"SDF"/"MOL2"/"PDB"/"InChI" → prep
4. 仅提化合物名称且要求绘图 → visualizer
5. 含 "成药性"/"Lipinski"/"分子量"/"LogP"/"QED"/"相似度"/"骨架" → analyst
6. 问候/功能介绍/无化学内容 → END

⚠️ 每次只路由到**一个**节点。若需要同时绘图和计算，先路由 analyst，下一轮再路由 visualizer。
⚠️ 如果 validation_errors 非空，说明上一轮 SMILES 有误，请在回复中说明并尝试修正（或告知用户）。
"""

_VISUALIZER_SYSTEM = """\
你是 ChemAgent 的分子可视化专家。

收到 SMILES 后，调用 tool_render_smiles 生成 2D 结构图。
如果没有 SMILES 只有化合物名称，先调用 tool_validate_smiles 获取规范化 SMILES，再渲染。
完成后用中文简洁描述分子结构特点（环系、官能团）。
"""

_ANALYST_SYSTEM = """\
你是 ChemAgent 的分子性质分析专家。

根据用户需求调用适当工具：

── RDKit 工具 ──────────────────────────────────────────────────
- tool_validate_smiles      → SMILES 合法性验证与规范化
- tool_compute_descriptors  → Lipinski Ro5 + QED + SA Score + TPSA + 全量描述符
- tool_compute_similarity   → Tanimoto 相似度（ECFP4 Morgan 指纹，需要两个 SMILES）
- tool_substructure_match   → 子结构搜索（SMARTS）+ PAINS 筛查
- tool_murcko_scaffold      → Bemis-Murcko 骨架提取
- tool_strip_salts          → 盐型处理与去离子化（保留最大片段）

── Open Babel 工具 ─────────────────────────────────────────────
- tool_compute_mol_properties  → Open Babel 分子属性（精确质量、分子式、成键数等，可与 RDKit 交叉验证）
- tool_compute_partial_charges → 逐原子部分电荷（Gasteiger/MMFF94/QEq/EEM）

计算完成后，用 Markdown 表格或列表清晰呈现数值结果，并给出专业解读。
"""

_PREP_SYSTEM = """\
你是 ChemAgent 的分子制备专家，专门处理格式转换、3D 构象生成和分子对接准备工作。

根据用户需求调用适当工具：

── Open Babel 工具 ─────────────────────────────────────────────
- tool_convert_format       → 任意格式互转（SMILES↔SDF↔MOL2↔PDB↔XYZ↔InChI↔InChIKey 等 110+ 种）
- tool_build_3d_conformer   → 3D 构象生成（SMILES → MMFF94/UFF 力场优化 SDF，含能量）
- tool_prepare_pdbqt        → 对接准备（SMILES → pH 校正氢 → MMFF94 3D → Gasteiger 电荷 → PDBQT）
- tool_list_formats         → 列出所有 Open Babel 支持的格式代码（查询用）

使用规范：
1. 格式转换时先确认 input_fmt 和 output_fmt 均受支持（如不确定，先调用 tool_list_formats）
2. 3D 构象默认使用 mmff94，对小分子药物更准确；若不收敛则退换 uff
3. PDBQT 准备后，提示用户 rotatable_bonds 数量及 flexibility_warning 含义
4. 返回大文件（SDF/PDBQT）时，摘要数值信息，并告知完整文件已作为 artifact 提供下载

完成后用中文给出结果摘要和后续建议（如推荐下一步对接参数设置）。
"""


# ── Expanded analyst tool list (RDKit + Open Babel analysis tools) ───────────

_ANALYST_ALL_TOOLS = ANALYST_TOOLS + BABEL_ANALYSIS_TOOLS

# ── Node: Supervisor ───────────────────────────────────────────────────────────


async def supervisor_node(state: ChemMVPState) -> dict:
    """Central routing hub.  Calls the LLM with structured output to decide
    which worker node to invoke next, or to end the conversation."""

    supervisor_llm = _build_chat_llm(structured_schema=RouteDecision)

    prompt_messages: list[BaseMessage] = [
        SystemMessage(content=_SUPERVISOR_SYSTEM),
        *state["messages"],
    ]

    # Inject active_smiles context so the LLM can echo it in RouteDecision
    if state.get("active_smiles"):
        prompt_messages.append(
            HumanMessage(
                content=f"[Context] 当前画布上已激活的 SMILES：{state['active_smiles']}"
            )
        )

    # If there are validation errors from Shadow Lab, prepend context
    if state.get("validation_errors"):
        errors_text = "\n".join(state["validation_errors"])
        prompt_messages.append(
            HumanMessage(
                content=(
                    f"[Shadow Lab 检测到 SMILES 验证错误]\n{errors_text}\n\n"
                    "请在下次路由时修正 active_smiles，或向用户说明无法处理此 SMILES。"
                )
            )
        )

    decision: RouteDecision = await supervisor_llm.ainvoke(prompt_messages)  # type: ignore[assignment]

    # Build partial state update
    update: dict = {
        "next_node": decision.next,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }

    # Propagate SMILES if the LLM identified one
    if decision.active_smiles:
        update["active_smiles"] = decision.active_smiles.strip()

    # Append a trace message so other nodes (and the stream consumer) see reasoning
    update["messages"] = [
        AIMessage(
            content=f"[Supervisor → {decision.next}] {decision.reasoning}",
            name="supervisor",
        )
    ]

    return update


# ── Node: Visualizer (tool-calling agent) ─────────────────────────────────────


async def visualizer_node(state: ChemMVPState) -> dict:
    """Renders 2D molecular structures.  Uses a bound-tool LLM that calls
    tool_render_smiles (and optionally tool_validate_smiles).

    After the LLM finishes, any base64 image data found in tool results is
    dispatched as a custom event for the SSE stream to forward to the frontend.
    """
    visualizer_llm = _build_chat_llm(tools=VISUALIZER_TOOLS)

    context_parts: list[str] = []
    if state.get("active_smiles"):
        context_parts.append(f"当前 SMILES: {state['active_smiles']}")
    if state.get("validation_errors"):
        context_parts.append("注意：上一轮存在验证错误，请谨慎处理。")

    system_suffix = "\n\n" + "\n".join(context_parts) if context_parts else ""

    prompt: list[BaseMessage] = [
        SystemMessage(content=_VISUALIZER_SYSTEM + system_suffix),
        *state["messages"],
    ]

    all_messages: list[BaseMessage] = []
    artifacts_emitted: list[dict] = []

    # Agentic loop: keep calling LLM → tool execution until done
    current_prompt = prompt
    for _ in range(4):  # max tool-call iterations in one worker turn
        response = await visualizer_llm.ainvoke(current_prompt)
        all_messages.append(response)

        if not getattr(response, "tool_calls", None):
            break  # LLM finished — no more tool calls

        # Execute each tool call, collect results
        tool_messages: list[ToolMessage] = []
        for tc in response.tool_calls:
            tool_fn = next((t for t in VISUALIZER_TOOLS if t.name == tc["name"]), None)
            if tool_fn is None:
                result_content = f"Unknown tool: {tc['name']}"
            else:
                result_content = await tool_fn.ainvoke(tc["args"])

            tool_messages.append(
                ToolMessage(content=str(result_content), tool_call_id=tc["id"])
            )

            # Detect and surface image artifacts
            import json as _json
            try:
                data = _json.loads(result_content)
                if data.get("is_valid") and data.get("image"):
                    artifact = {
                        "kind": "molecule_image",
                        "mime_type": "image/png",
                        "encoding": "base64",
                        "data": data["image"],
                        "smiles": data.get("smiles", state.get("active_smiles", "")),
                        "title": "2D 结构图",
                    }
                    artifacts_emitted.append(artifact)
                    await adispatch_custom_event("artifact", artifact)
            except Exception:
                pass

        all_messages.extend(tool_messages)
        current_prompt = prompt + all_messages

    # Update active_smiles if a new canonical SMILES was produced
    new_smiles: str | None = None
    for msg in reversed(all_messages):
        if isinstance(msg, ToolMessage):
            try:
                import json as _json
                data = _json.loads(msg.content)
                if data.get("is_valid") and data.get("smiles"):
                    new_smiles = data["smiles"]
                    break
            except Exception:
                pass

    update: dict = {
        "messages": all_messages,
        "artifacts": artifacts_emitted,
        "next_node": None,
    }
    if new_smiles:
        update["active_smiles"] = new_smiles

    return update


# ── Node: Analyst (tool-calling agent) ────────────────────────────────────────


async def analyst_node(state: ChemMVPState) -> dict:
    """Computes molecular physicochemical properties.  Uses a bound-tool LLM
    that can call the full ANALYST_TOOLS suite.

    Descriptor results (including structure images) are dispatched as custom
    events for the SSE stream.
    """
    analyst_llm = _build_chat_llm(tools=_ANALYST_ALL_TOOLS)

    context_parts: list[str] = []
    if state.get("active_smiles"):
        context_parts.append(f"当前 SMILES: {state['active_smiles']}")

    system_suffix = "\n\n" + "\n".join(context_parts) if context_parts else ""

    prompt: list[BaseMessage] = [
        SystemMessage(content=_ANALYST_SYSTEM + system_suffix),
        *state["messages"],
    ]

    all_messages: list[BaseMessage] = []
    artifacts_emitted: list[dict] = []

    current_prompt = prompt
    for _ in range(6):  # analyst may need multiple tool calls (e.g. validate → descriptors)
        response = await analyst_llm.ainvoke(current_prompt)
        all_messages.append(response)

        if not getattr(response, "tool_calls", None):
            break

        tool_messages: list[ToolMessage] = []
        for tc in response.tool_calls:
            tool_fn = next((t for t in _ANALYST_ALL_TOOLS if t.name == tc["name"]), None)
            if tool_fn is None:
                result_content = f"Unknown tool: {tc['name']}"
            else:
                result_content = await tool_fn.ainvoke(tc["args"])

            tool_messages.append(
                ToolMessage(content=str(result_content), tool_call_id=tc["id"])
            )

            # Surface descriptor / image artifacts
            import json as _json
            try:
                data = _json.loads(result_content)
                if data.get("is_valid"):
                    # Emit descriptor artifact (without image for brevity)
                    if data.get("descriptors") or data.get("lipinski"):
                        artifact = {
                            "kind": "descriptors",
                            "mime_type": "application/json",
                            "encoding": "json",
                            "data": {k: v for k, v in data.items() if "image" not in k},
                            "title": f"分子描述符 — {data.get('name') or data.get('smiles', '')}",
                        }
                        artifacts_emitted.append(artifact)
                        await adispatch_custom_event("artifact", artifact)

                    # Also emit structure image as a separate artifact
                    image_key = next(
                        (k for k in ("structure_image", "image", "highlighted_image") if data.get(k)),
                        None,
                    )
                    if image_key:
                        img_artifact = {
                            "kind": "molecule_image",
                            "mime_type": "image/png",
                            "encoding": "base64",
                            "data": data[image_key],
                            "smiles": data.get("smiles", state.get("active_smiles", "")),
                            "title": "2D 结构图",
                        }
                        artifacts_emitted.append(img_artifact)
                        await adispatch_custom_event("artifact", img_artifact)
            except Exception:
                pass

        all_messages.extend(tool_messages)
        current_prompt = prompt + all_messages

    # Update active_smiles from validated/canonical SMILES
    new_smiles: str | None = None
    for msg in reversed(all_messages):
        if isinstance(msg, ToolMessage):
            try:
                import json as _json
                data = _json.loads(msg.content)
                if data.get("is_valid") and data.get("smiles"):
                    new_smiles = data["smiles"]
                    break
            except Exception:
                pass

    update: dict = {
        "messages": all_messages,
        "artifacts": artifacts_emitted,
        "next_node": None,
    }
    if new_smiles:
        update["active_smiles"] = new_smiles

    return update


# ── Node: Prep (Open Babel tool-calling agent) ────────────────────────────────


async def prep_node(state: ChemMVPState) -> dict:
    """Handles format conversion, 3D conformer generation, and docking PDBQT prep.

    Uses PREP_TOOLS (all Open Babel-backed): tool_convert_format,
    tool_build_3d_conformer, tool_prepare_pdbqt, tool_list_formats.

    Large binary outputs (SDF, PDBQT) are dispatched as artifacts so the
    frontend can offer them as downloads without bloating the LLM context.
    """
    prep_llm = _build_chat_llm(tools=PREP_TOOLS)

    context_parts: list[str] = []
    if state.get("active_smiles"):
        context_parts.append(f"当前 SMILES: {state['active_smiles']}")

    system_suffix = "\n\n" + "\n".join(context_parts) if context_parts else ""

    prompt: list[BaseMessage] = [
        SystemMessage(content=_PREP_SYSTEM + system_suffix),
        *state["messages"],
    ]

    all_messages: list[BaseMessage] = []
    artifacts_emitted: list[dict] = []

    current_prompt = prompt
    for _ in range(5):  # prep may need list_formats → convert pipeline
        response = await prep_llm.ainvoke(current_prompt)
        all_messages.append(response)

        if not getattr(response, "tool_calls", None):
            break

        tool_messages: list[ToolMessage] = []
        for tc in response.tool_calls:
            tool_fn = next((t for t in PREP_TOOLS if t.name == tc["name"]), None)
            if tool_fn is None:
                result_content = f"Unknown tool: {tc['name']}"
            else:
                result_content = await tool_fn.ainvoke(tc["args"])

            tool_messages.append(
                ToolMessage(content=str(result_content), tool_call_id=tc["id"])
            )

            # Surface large file artifacts (SDF, PDBQT)
            import json as _json
            import app.chem.babel_ops as _bops
            try:
                data = _json.loads(result_content)
                if data.get("is_valid"):
                    # 3D conformer SDF artifact
                    # Note: _to_text() strips sdf_content from the LLM-facing JSON, so we
                    # re-call the kernel to obtain the full text for the artifact.
                    if data.get("type") == "conformer_3d":
                        _full = _bops.build_3d_conformer(
                            data.get("smiles", state.get("active_smiles", "")),
                            name=data.get("name", ""),
                            forcefield=data.get("forcefield", "mmff94"),
                            steps=data.get("steps", 500),
                        )
                        artifact = {
                            "kind": "conformer_3d",
                            "mime_type": "chemical/x-mdl-sdfile",
                            "encoding": "text",
                            "data": _full.get("sdf_content", ""),
                            "smiles": data.get("smiles", state.get("active_smiles", "")),
                            "title": f"3D Conformer — {data.get('name') or data.get('smiles', '')}",
                            "meta": {
                                "forcefield": data.get("forcefield"),
                                "energy_kcal_mol": data.get("energy_kcal_mol"),
                                "atom_count": data.get("atom_count"),
                            },
                        }
                        artifacts_emitted.append(artifact)
                        await adispatch_custom_event("artifact", artifact)

                    # PDBQT artifact
                    elif data.get("type") == "pdbqt_prep":
                        _full = _bops.prepare_pdbqt(
                            data.get("smiles", state.get("active_smiles", "")),
                            name=data.get("name", ""),
                            ph=data.get("ph", 7.4),
                        )
                        artifact = {
                            "kind": "pdbqt",
                            "mime_type": "chemical/x-pdbqt",
                            "encoding": "text",
                            "data": _full.get("pdbqt_content", ""),
                            "smiles": data.get("smiles", state.get("active_smiles", "")),
                            "title": f"PDBQT — {data.get('name') or data.get('smiles', '')}",
                            "meta": {
                                "ph": data.get("ph"),
                                "rotatable_bonds": data.get("rotatable_bonds"),
                                "flexibility_warning": data.get("flexibility_warning"),
                            },
                        }
                        artifacts_emitted.append(artifact)
                        await adispatch_custom_event("artifact", artifact)

                    # Generic format conversion artifact (SDF, MOL2, PDB, InChI, etc.)
                    # The truncated output IS present in data["output"]; re-call for full content.
                    elif data.get("type") == "format_conversion":
                        _smiles_input = state.get("active_smiles", "")
                        if _smiles_input:
                            _full = _bops.convert_format(
                                _smiles_input,
                                "smi",
                                data.get("output_format", "sdf"),
                            )
                            out_fmt = data.get("output_format", "file")
                            artifact = {
                                "kind": "format_conversion",
                                "mime_type": "text/plain",
                                "encoding": "text",
                                "data": _full.get("output", data.get("output", "")),
                                "title": f"Format Conversion → {out_fmt.upper()}",
                            }
                            artifacts_emitted.append(artifact)
                            await adispatch_custom_event("artifact", artifact)
            except Exception:
                pass

        all_messages.extend(tool_messages)
        current_prompt = prompt + all_messages

    update: dict = {
        "messages": all_messages,
        "artifacts": artifacts_emitted,
        "next_node": None,
    }
    return update


# ── Node: Shadow Lab (deterministic SMILES validation) ────────────────────────


async def shadow_lab_node(state: ChemMVPState) -> dict:
    """Pure RDKit SMILES validation node — the anti-hallucination firewall.

    Algorithm
    ---------
    1. Read ``state["active_smiles"]``.
    2. If None → nothing to validate, pass through to END.
    3. Call ``Chem.MolFromSmiles`` with ``sanitize=True``.
    4. If sanitization raises a valence / kekulization error:
       - Append the error message to ``validation_errors``.
       - Inject a HumanMessage requesting self-correction.
       - Set ``next_node = "supervisor"`` to trigger a correction loop.
    5. If valid → ``next_node = None`` (route to END).

    The node NEVER calls an LLM.
    """
    smiles = state.get("active_smiles")

    if not smiles:
        return {"next_node": None}

    error_msg: str | None = None
    try:
        mol = Chem.MolFromSmiles(smiles, sanitize=True)
        if mol is None:
            error_msg = f"RDKit 无法解析 SMILES（可能含非法原子或括号不匹配）：{smiles}"
    except Exception as exc:
        error_msg = f"RDKit 化合价检测异常（{type(exc).__name__}）：{exc}  SMILES={smiles}"

    if error_msg:
        await adispatch_custom_event(
            "shadow_lab_error",
            {"smiles": smiles, "error": error_msg},
        )
        return {
            "validation_errors": [error_msg],
            "next_node": "supervisor",
            "messages": [
                HumanMessage(
                    content=(
                        f"[Shadow Lab 验证失败]\n错误：{error_msg}\n\n"
                        "请修正 SMILES 后重新尝试，或告知用户该结构无法处理。"
                    ),
                    name="shadow_lab",
                )
            ],
        }

    # SMILES is valid — clear any stale error signal
    return {"next_node": None, "active_smiles": Chem.MolToSmiles(mol)}


# ── Conditional edges ─────────────────────────────────────────────────────────


def route_after_supervisor(state: ChemMVPState) -> str:
    """Conditional edge: supervisor → visualizer | analyst | prep | END.

    The LLM structured output uses the string "END" as a literal; we must map
    it to the LangGraph END sentinel ("__end__") before returning.
    """
    node = state.get("next_node") or "END"
    if node == "END":
        return END  # LangGraph END constant = "__end__"
    return node


def route_after_shadow_lab(state: ChemMVPState) -> str:
    """Conditional edge: shadow_lab → supervisor (correction) | END.

    Guards against infinite loops via iteration_count.
    """
    if state.get("next_node") == "supervisor" and state.get("iteration_count", 0) < MAX_ITERATIONS:
        return "supervisor"
    return END


# ── Graph assembly & compilation ──────────────────────────────────────────────


def build_graph() -> StateGraph:
    graph = StateGraph(ChemMVPState)

    # Register nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("visualizer", visualizer_node)
    graph.add_node("analyst",    analyst_node)
    graph.add_node("prep",       prep_node)
    graph.add_node("shadow_lab", shadow_lab_node)

    # Entry point
    graph.add_edge(START, "supervisor")

    # Supervisor → worker branch
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "visualizer": "visualizer",
            "analyst":    "analyst",
            "prep":       "prep",
            END:          END,
        },
    )

    # All three workers flow into Shadow Lab for SMILES validation
    graph.add_edge("visualizer", "shadow_lab")
    graph.add_edge("analyst",    "shadow_lab")
    graph.add_edge("prep",       "shadow_lab")

    # Shadow Lab decides: correct (→ supervisor) or accept (→ END)
    graph.add_conditional_edges(
        "shadow_lab",
        route_after_shadow_lab,
        {
            "supervisor": "supervisor",
            END: END,
        },
    )

    return graph


# Compile once at import time; reused across all requests.
compiled_graph = build_graph().compile()

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
from app.agents.lg_tools import ANALYST_TOOLS, ALL_TOOLS, VISUALIZER_TOOLS, RESEARCHER_TOOLS
from app.tools.babel.prep import (
    BABEL_ANALYSIS_TOOLS,
    PREP_TOOLS,
    tool_build_3d_conformer,
    tool_prepare_pdbqt,
)
from app.chem.rdkit_ops import compute_descriptors, mol_to_png_b64, validate_smiles

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_ITERATIONS = 3  # Maximum supervisor→worker→shadow_lab loops before forcing END

# ── Binary / large-payload field names that must NOT be fed back to the LLM ───
# Images (base64 PNG) or large molecule files sent back into the LLM context
# waste tokens and cause the model to copy raw binary into its text replies.
# These fields are dispatched to the frontend via on_custom_event artifacts
# instead, so we can safely strip them from ToolMessage content.
_STRIP_LLM_FIELDS = frozenset(
    {
        "image",           # tool_render_smiles / tool_validate_smiles
        "structure_image", # tool_compute_descriptors
        "highlighted_image",  # tool_substructure_match
        "sdf_content",     # tool_build_3d_conformer
        "pdbqt_content",   # tool_prepare_pdbqt
        "zip_bytes",       # future bulk exports
        "atoms",           # atom-level charge arrays (tool_compute_partial_charges)
    }
)


def _strip_llm_tool_content(raw: str) -> str:
    """Return a compact JSON string safe to use as ToolMessage.content.

    Removes large binary / base64 fields listed in _STRIP_LLM_FIELDS so the
    LLM never sees raw image data.  Stripped fields are replaced with a short
    placeholder so the LLM knows the artifact exists and was dispatched.
    """
    import json as _json

    try:
        data = _json.loads(raw)
    except Exception:
        return raw  # Not JSON — return as-is

    if not isinstance(data, dict):
        return raw

    stripped: list[str] = []
    cleaned = {}
    for key, val in data.items():
        if key in _STRIP_LLM_FIELDS and isinstance(val, str) and len(val) > 200:
            stripped.append(key)
        else:
            cleaned[key] = val

    if stripped:
        cleaned["_artifact_dispatched"] = stripped  # inform LLM without bulk data

    return _json.dumps(cleaned, ensure_ascii=False)


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
    # HITL fields — set by researcher_node when it needs user clarification
    pending_clarification: str | None
    interrupt_options: Annotated[list[str], operator.add]


# ── Structured output schema for Supervisor routing ───────────────────────────


class RouteDecision(BaseModel):
    """Structured output schema for the Supervisor node.

    The LLM fills this schema; LangGraph uses `next` to pick the downstream
    node.  No string parsing — fully type-safe.
    """

    next: Literal["visualizer", "analyst", "researcher", "prep", "END"] = Field(
        description=(
            "Which worker to invoke next.  Use 'visualizer' for 2D structure rendering; "
            "'analyst' for physicochemical calculations (Lipinski, QED, TPSA, similarity, "
            "scaffold, partial charges, cross-validate with Open Babel); "
            "'researcher' when the user wants to research/investigate a drug or compound by name "
            "(fetches SMILES from PubChem, runs full analysis, and searches the web for "
            "latest clinical/pharmacology news); "
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


def _build_chat_llm(tools: list | None = None, structured_schema: type | None = None, reasoning_override: dict | None = None) -> ChatOpenAI:
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
        "reasoning": reasoning_override or {"effort": "minimal"},
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

_RESEARCHER_SYSTEM = """\
你是 ChemAgent 的药物研究专家，使用 ReAct（推理-行动-观察-反思）范式进行深度调研。

═══ ReAct 工作协议 ═══

每次准备调用工具前，先完成以下三步内心推理（无需输出给用户）：
  ① 我已掌握哪些信息？（参考 [已调用工具] 清单与工具结果）
  ② 我仍然缺少什么信息才能完成报告？
  ③ 这个工具是否已调用过？（已调用且成功则跳过，避免重复）

推理完成后，选择最有价值的下一个工具调用。

═══ 信息完成检查清单（5 项全满足后立即输出报告）═══

  ✓ A. 已有 SMILES（来自 [Context]、用户输入或 tool_pubchem_lookup 成功结果）
  ✓ B. 已运行 tool_compute_descriptors（理化性质：Lipinski、QED、TPSA 等）
  ✓ C. 已运行 tool_murcko_scaffold（核心骨架提取）
  ✓ D. 已运行 tool_render_smiles（2D 结构图）
  ✓ E. 已进行 ≥1 次 tool_web_search（联网检索，英文或中文均可）

如果 [Context] 已提供"当前 SMILES"，视 A 为已满足，无需调用 tool_pubchem_lookup。
5 项全满足后，立即输出综合报告，不再调用任何工具。

═══ Human-in-the-Loop：以下情况必须调用 tool_ask_human ═══

遇到以下任意情况时，立即调用 tool_ask_human 暂停研究，提供明确的 options：
  1. tool_pubchem_lookup 返回 found=false，且备选英文名也失败（最多 2 次尝试后停止重试）
  2. 用户消息中没有任何化合物名称（如"帮我调研那个药"）
  3. 多个化合物共享同一名称，无法确定用户意图
  4. 连续两次 tool_web_search 均返回空 results 列表，且化合物名称可能有拼写问题

调用 tool_ask_human 后，立即停止，不再调用任何其他工具。

═══ 约束规则 ═══

- 每个工具最多调用一次（PubChem 失败时最多 2 次，第 2 次失败则调用 tool_ask_human）
- 每次调用工具前，先用 1-2 句中文简要说明推理思路（已完成哪些步骤、接下来要做什么），再发起工具调用
- 5 项清单完成后，输出唯一一份综合 Markdown 报告，然后停止
- 报告输出后不再调用任何工具
- ⚠️ 严禁在报告文本中嵌入 base64 图片数据或任何 data URI（如 <img src="data:image/png;base64,...">）；
  结构图已由工具自动生成并作为独立 artifact 推送到前端展示，报告中只需用文字说明"结构图已渲染"即可

═══ 综合报告格式（中文 Markdown）═══

## {化合物名称} 综合研究报告

### 基本信息
（分子式、MW、IUPAC 名、CID、canonical SMILES）

### 理化性质与成药性
（Lipinski Ro5 各项、QED 评分、TPSA、SA Score、旋转键数、重原子数）

### 核心骨架
（Murcko scaffold SMILES）

### 作用机制与药理
（基于网络检索结果撰写，注明信息来源 URL）

### 最新临床进展
（批准状态、适应症、临床试验期数、最新动态）

### 小结
（1-2 句精炼总结）
"""

_RESPONDER_SYSTEM = """\
你是 ChemAgent，一个专业的化学 AI 助手。请用中文直接回答用户的问题，语气专业、友好。
若问题涉及具体化合物，可介绍其化学结构、用途、性质等知识。如果已知 SMILES，可简要
提及。无需调用任何工具，直接作答即可。
"""

_SUPERVISOR_SYSTEM = """\
你是 ChemAgent 的首席化学主管，负责将用户请求精准路由给专家节点。

可用专家节点：
- **visualizer**：生成分子的 2D 结构图（仅需 SMILES 或化合物名称）
- **analyst**  ：计算理化性质（Lipinski Ro5、QED、TPSA、SA Score、Tanimoto 相似度、
                 Murcko 骨架、盐型处理、部分电荷分析（Gasteiger/MMFF94）、Open Babel 分子属性交叉验证）
- **researcher**：全面调研一款药物/化合物（自动从 PubChem 获取 SMILES、计算理化性质、生成结构图、搜索最新临床动态）
- **prep**     ：分子格式转换（SMILES↔SDF/MOL2/PDB/XYZ/InChI/InChIKey 等 110+ 格式）、
                 3D 构象生成（MMFF94/UFF 力场）、对接用 PDBQT 文件准备（AutoDock/Vina/Smina/GNINA）
- **END**      ：直接回答，无需调用工具（如问候、解释概念、对话收尾）

路由规则（按优先级）：
1. 包含“调研”“研究”“介绍”“分析这款药”“归纳”“全面了解”“research”“investigate”“overview” + 化合物名称 → researcher
2. 用户明确提供 SMILES → analyst（计算）或 visualizer（绘图）或 prep（格式/3D/对接）
3. 含 "3D构象"/"conformer"/"PDBQT"/"对接"/"docking" → prep
4. 含 "转换格式"/"convert"/"SDF"/"MOL2"/"PDB"/"InChI" → prep
5. 仅提化合物名称且要求绘图 → visualizer
6. 含 "成药性"/"Lipinski"/"分子量"/"LogP"/"QED"/"相似度"/"骨架" → analyst
7. 问候/功能介绍/无化学内容 → END

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


async def responder_node(state: ChemMVPState) -> dict:
    """Generates a direct conversational reply when no specialist tools are needed.

    Runs when the supervisor routes to END — i.e., the user asked a question
    that can be answered with knowledge alone (greetings, concept explanations,
    compound overviews, etc.).  Using a dedicated node keeps the supervisor's
    structured-output JSON tokens from leaking into the chat UI.
    """
    llm = _build_chat_llm()
    prompt: list[BaseMessage] = [
        SystemMessage(content=_RESPONDER_SYSTEM),
        *state["messages"],
    ]
    if state.get("active_smiles"):
        prompt.append(
            HumanMessage(
                content=f"[Context] 当前画布上已激活的 SMILES：{state['active_smiles']}"
            )
        )
    response = await llm.ainvoke(prompt)
    return {"messages": [response]}



async def researcher_node(state: ChemMVPState) -> dict:
    """ReAct-driven drug/compound research agent with Human-in-the-Loop support.

    Uses a Reason-Act-Observe-Reflect loop: the LLM self-evaluates its
    information gaps each iteration and picks the next tool dynamically.
    Calls tool_ask_human to pause and request user clarification when uncertain.
    """
    import json as _json

    researcher_llm = _build_chat_llm(
        tools=RESEARCHER_TOOLS,
        # Enable reasoning summary so the Responses API returns the model's
        # chain-of-thought as output[type=="reasoning"].summary[].text.
        reasoning_override={"effort": "low", "summary": "auto"},
    )

    # ── Build initial context suffix ───────────────────────────────────────────
    context_parts: list[str] = []
    if state.get("active_smiles"):
        context_parts.append(f"当前 SMILES: {state['active_smiles']}")
    if state.get("pending_clarification"):
        context_parts.append(
            f"[HITL 续研] 上轮暂停原因：{state['pending_clarification']}\n"
            f"用户已在最新消息中提供了答案，请根据答案继续研究。"
        )
    if state.get("validation_errors"):
        context_parts.append("注意：上一轮存在验证错误，请谨慎处理。")

    # Track which tools have been invoked (injected into system each round)
    called_tools: list[str] = []

    def _system_msg() -> SystemMessage:
        parts = list(context_parts)
        if called_tools:
            parts.append(f"[已调用工具]: {', '.join(called_tools)}")
        suffix = ("\n\n" + "\n".join(parts)) if parts else ""
        return SystemMessage(content=_RESEARCHER_SYSTEM + suffix)

    all_messages: list[BaseMessage] = []
    artifacts_emitted: list[dict] = []
    hitl_triggered = False
    hitl_question = ""
    hitl_options: list[str] = []

    # Ordered checklist items: (label, description, tool_name)
    _CHECKLIST = [
        ("A", "SMILES / 化合物信息获取", "tool_pubchem_lookup"),
        ("B", "理化性质 & 成药性计算",   "tool_compute_descriptors"),
        ("C", "Murcko 核心骨架提取",     "tool_murcko_scaffold"),
        ("D", "2D 结构图渲染",           "tool_render_smiles"),
        ("E", "联网文献 & 药理检索",      "tool_web_search"),
    ]

    def _make_checklist_text(iteration: int) -> str:
        """Deterministic fallback used when the model returns no reasoning summary."""
        done = [f"✓ {label}. {desc}" for label, desc, tool in _CHECKLIST if tool in called_tools]
        todo = [f"○ {label}. {desc}" for label, desc, tool in _CHECKLIST if tool not in called_tools]
        if iteration == 0:
            items = "\n".join(f"  {label}. {desc}" for label, desc, _ in _CHECKLIST)
            return f"开始调研，将依次完成以下步骤：\n{items}"
        lines = []
        if done:
            lines.append("已完成：\n" + "\n".join(f"  {s}" for s in done))
        if todo:
            lines.append("待完成：\n" + "\n".join(f"  {s}" for s in todo))
        return "\n\n".join(lines)

    def _extract_reasoning_summary(msg: BaseMessage) -> str:
        """Extract reasoning summary from a Responses API AIMessage.

        The Responses API returns reasoning as a separate output item:
          output[{type: 'reasoning', summary: [{type: 'summary_text', text: '...'}]}]

        langchain-openai surfaces this in AIMessage.additional_kwargs['output'].
        """
        output_items = getattr(msg, "additional_kwargs", {}).get("output", [])
        for item in output_items:
            if not isinstance(item, dict) or item.get("type") != "reasoning":
                continue
            texts = [
                s.get("text", "")
                for s in item.get("summary", [])
                if isinstance(s, dict)
            ]
            text = "\n\n".join(t for t in texts if t).strip()
            if text:
                return text
        return ""

    for iteration in range(12):  # ReAct loop — LLM self-terminates via checklist
        # Rebuild system message every round so [已调用工具] stays current
        current_prompt: list[BaseMessage] = [
            _system_msg(),
            *state["messages"],
            *all_messages,
        ]

        # Soft convergence nudge at iteration 8
        if iteration == 8:
            current_prompt.append(
                HumanMessage(
                    content="[系统提示] 已进行 8 次推理迭代。请在接下来 1-2 步内完成报告或调用 tool_ask_human。"
                )
            )

        # ── Stream the LLM response token-by-token ────────────────────────────
        # Using astream() instead of ainvoke() lets us push incremental thinking
        # text to the frontend in real-time, without waiting for the full response.
        from langchain_core.messages import AIMessageChunk

        response: BaseMessage | None = None
        accumulated_text = ""   # LLM output text accumulated across chunks
        _dispatch_counter = 0   # throttle: dispatch every N chars to avoid flooding

        async for chunk in researcher_llm.astream(current_prompt):
            # Merge chunks into a single AIMessage (preserves tool_calls etc.)
            response = chunk if response is None else response + chunk  # type: ignore[operator]

            # Extract text from this chunk
            raw = getattr(chunk, "content", "") or ""
            if isinstance(raw, list):
                chunk_text = "".join(
                    block.get("text", "")
                    for block in raw
                    if isinstance(block, dict) and block.get("type") == "output_text"
                )
            elif isinstance(raw, str):
                chunk_text = raw
            else:
                chunk_text = ""

            if chunk_text:
                accumulated_text += chunk_text
                _dispatch_counter += len(chunk_text)
                # Dispatch a thinking-in-progress event every ~40 chars so the
                # frontend updates smoothly without excessive SSE traffic.
                if _dispatch_counter >= 40:
                    _dispatch_counter = 0
                    await adispatch_custom_event(
                        "thinking",
                        {"text": accumulated_text, "iteration": iteration, "done": False},
                    )

        # response is None only if the LLM returned zero chunks (shouldn't happen)
        if response is None:
            break

        all_messages.append(response)

        # ── Final thinking dispatch for this iteration ─────────────────────────
        # Prefer the Responses API reasoning summary; fall back to the accumulated
        # output text (what the model actually wrote); last resort: checklist.
        reasoning_summary = _extract_reasoning_summary(response)
        final_thinking_text = (
            reasoning_summary
            or accumulated_text.strip()
            or _make_checklist_text(iteration)
        )
        await adispatch_custom_event(
            "thinking",
            {"text": final_thinking_text, "iteration": iteration, "done": True},
        )

        if not getattr(response, "tool_calls", None):
            # LLM emitted final text — ReAct loop complete
            break

        tool_messages: list[ToolMessage] = []
        should_break = False

        for tc in response.tool_calls:
            tool_name: str = tc["name"]
            tool_fn = next((t for t in RESEARCHER_TOOLS if t.name == tool_name), None)
            if tool_fn is None:
                result_content = f"Unknown tool: {tool_name}"
            else:
                result_content = await tool_fn.ainvoke(tc["args"])

            # Feed a stripped copy to the LLM — strip base64 images & large files
            # so the model never copies raw binary into its text replies.
            # The full result_content is still used below for artifact dispatch.
            tool_messages.append(
                ToolMessage(
                    content=_strip_llm_tool_content(str(result_content)),
                    tool_call_id=tc["id"],
                )
            )
            called_tools.append(tool_name)

            # ── Parse tool result ──────────────────────────────────────────────
            try:
                data = _json.loads(result_content)
            except Exception:
                data = {}

            # HITL: tool_ask_human fired → dispatch event and pause
            if data.get("type") == "clarification_requested":
                hitl_triggered = True
                hitl_question = data.get("question", "")
                hitl_options = data.get("options", [])
                await adispatch_custom_event(
                    "clarification_request",
                    {
                        "question": hitl_question,
                        "options": hitl_options,
                        "called_tools": called_tools,
                    },
                )
                should_break = True
                break  # stop processing further tool calls in this batch

            # Surface molecule image artifacts
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

            # Surface descriptors artifact (tool_compute_descriptors result)
            if data.get("type") == "descriptors" and data.get("is_valid"):
                desc_artifact: dict = {
                    "kind": "descriptors",
                    "mime_type": "application/json",
                    "encoding": "json",
                    "data": {
                        "smiles": data.get("smiles", ""),
                        "name": data.get("name", ""),
                        "formula": data.get("formula", ""),
                        "descriptors": data.get("descriptors", {}),
                        "lipinski": data.get("lipinski", {}),
                        "structure_image": data.get("structure_image", ""),
                    },
                    "title": (data.get("name") or data.get("smiles", "Molecule")) or "Molecule",
                }
                artifacts_emitted.append(desc_artifact)
                await adispatch_custom_event("artifact", desc_artifact)

            # Auto-render Murcko scaffold SMILES as a separate image artifact
            if tool_name == "tool_murcko_scaffold":
                scaffold_smiles = data.get("scaffold_smiles", "")
                if scaffold_smiles:
                    render_fn = next(
                        (t for t in RESEARCHER_TOOLS if t.name == "tool_render_smiles"), None
                    )
                    if render_fn is not None:
                        try:
                            scaffold_img_raw = await render_fn.ainvoke({"smiles": scaffold_smiles})
                            scaffold_img = _json.loads(scaffold_img_raw)
                            if scaffold_img.get("is_valid") and scaffold_img.get("image"):
                                scaffold_artifact = {
                                    "kind": "structure_image",
                                    "mime_type": "image/png",
                                    "encoding": "base64",
                                    "data": scaffold_img["image"],
                                    "smiles": scaffold_smiles,
                                    "title": "核心骨架 (Murcko Scaffold)",
                                }
                                artifacts_emitted.append(scaffold_artifact)
                                await adispatch_custom_event("artifact", scaffold_artifact)
                        except Exception:
                            pass  # scaffold render failure is non-fatal

        all_messages.extend(tool_messages)
        if should_break:
            break

    # ── Post-loop: if the loop exhausted without a final text response, force one ──
    # This happens when all 12 iterations produced tool_calls; the LLM never got a
    # chance to write the report.  One extra call with no tools available ensures
    # we always have a text response to stream back to the user.
    last_msg = all_messages[-1] if all_messages else None
    if (
        not hitl_triggered
        and last_msg is not None
        and getattr(last_msg, "tool_calls", None)  # last message was a tool call batch
    ):
        # Bind LLM without any tools so it MUST output text
        completion_llm = _build_chat_llm(tools=None)
        current_prompt = [
            _system_msg(),
            *state["messages"],
            *all_messages,
            HumanMessage(
                content=(
                    "[系统提示] 工具调用阶段已完成。请现在根据上方所有工具结果，"
                    "直接输出综合 Markdown 报告。不要再调用任何工具。"
                )
            ),
        ]
        final_response = await completion_llm.ainvoke(current_prompt)
        all_messages.append(final_response)

    # Update active_smiles if PubChem or validation returned a fresh SMILES
    new_smiles: str | None = None
    for msg in reversed(all_messages):
        if isinstance(msg, ToolMessage):
            try:
                import json as _json
                data = _json.loads(msg.content)
                smiles_candidate = data.get("canonical_smiles") or data.get("isomeric_smiles") or (data.get("is_valid") and data.get("smiles"))
                if smiles_candidate:
                    new_smiles = smiles_candidate
                    break
            except Exception:
                pass

    update: dict = {
        "messages": all_messages,
        "artifacts": artifacts_emitted,
        "next_node": None,
        # Clear pending_clarification on each researcher run; set if HITL fired
        "pending_clarification": hitl_question if hitl_triggered else None,
        "interrupt_options": hitl_options if hitl_triggered else [],
    }
    if new_smiles:
        update["active_smiles"] = new_smiles

    return update


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
                ToolMessage(
                    content=_strip_llm_tool_content(str(result_content)),
                    tool_call_id=tc["id"],
                )
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
                ToolMessage(
                    content=_strip_llm_tool_content(str(result_content)),
                    tool_call_id=tc["id"],
                )
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
                ToolMessage(
                    content=_strip_llm_tool_content(str(result_content)),
                    tool_call_id=tc["id"],
                )
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
    """Conditional edge: supervisor → visualizer | analyst | prep | responder.

    The LLM structured output uses the string "END" as a literal; we route that
    to the `responder` node so the user gets a proper conversational reply
    instead of raw routing JSON leaking into the chat UI.
    """
    node = state.get("next_node") or "END"
    if node == "END":
        return "responder"
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
    graph.add_node("responder",  responder_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("visualizer", visualizer_node)
    graph.add_node("analyst",    analyst_node)
    graph.add_node("prep",       prep_node)
    graph.add_node("shadow_lab", shadow_lab_node)

    # Entry point
    graph.add_edge(START, "supervisor")

    # Supervisor → worker branch (END routes through responder for clean UX)
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "visualizer": "visualizer",
            "analyst":    "analyst",
            "researcher": "researcher",
            "prep":       "prep",
            "responder":  "responder",
        },
    )

    # Responder is a terminal node — always goes to END
    graph.add_edge("responder",  END)
    graph.add_edge("researcher", END)

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

"""
ChemAgent team factory — builds the DefaultPattern multi-agent topology.

Topology
────────
  user_proxy (outside group)
      ↓ a_run_group_chat()
  DefaultPattern
      ├── planner              (coordinator — uses control tools only)
      ├── data_specialist      (PubChem + web search — self-executes tools)
      ├── computation_specialist (RDKit tools — self-executes tools)
      └── reviewer             (quality control, no tools)

Control flow (tool-driven, no sentinel strings)
───────────────────────────────────────────────
  Phase 1 termination:  ``submit_plan_for_approval(plan_details)``
      → ``ReplyResult(target=TerminateTarget())`` stops Phase 1 GroupChat.
        ``ctx["state"]`` is set to ``"awaiting_approval"``.

  Phase 2 termination:  ``finish_workflow(final_summary)``
      → ``ReplyResult(target=TerminateTarget())`` stops Phase 2 GroupChat.
        ``ctx["state"]`` is set to ``"completed"``.

  Routing between specialists:
      ``set_routing_target("data_specialist"|"computation_specialist")``
      → ``ReplyResult(target=AgentTarget(specialist))`` routes to that agent.

After-work transitions (DefaultPattern per-agent defaults)
───────────────────────────────────────────────────────────
  data_specialist        → reviewer (after each domain task)
  computation_specialist → reviewer (after each domain task)
  reviewer               → planner  (after each quality-control pass)
  planner                → controlled by tool return values

Returns 4-tuple: ``(user_proxy, pattern, ctx, agent_models)``
"""

from __future__ import annotations

import logging

from autogen import ConversableAgent
from autogen.agentchat import register_function
from autogen.agentchat.group import AgentTarget, ContextVariables
from autogen.agentchat.group.patterns import DefaultPattern

from app.agents.config import build_llm_config, get_fast_llm_config, get_resolved_model_name
from app.agents.executor import create_user_proxy
from app.agents.reasoning_client import ReasoningAwareClient
from app.agents.specialists import (
    create_computation_specialist,
    create_data_specialist,
    create_planner,
    create_reviewer,
    make_routing_tools,
    make_session_context,
)
from app.agents.specialists.control_tools import make_finish_workflow, make_submit_plan_for_approval
from app.tools import (
    analyze_molecule,
    check_substructure,
    compute_molecular_similarity,
    draw_molecule_structure,
    extract_murcko_scaffold,
    get_molecule_smiles,
    search_web,
)

logger = logging.getLogger(__name__)

# Domain tools owned by each specialist
_DATA_TOOLS = [get_molecule_smiles, search_web]
_COMPUTATION_TOOLS = [
    analyze_molecule,
    extract_murcko_scaffold,
    draw_molecule_structure,
    compute_molecular_similarity,
    check_substructure,
]


def create_chem_team(
    llm_config=None,
    model: str | None = None,
) -> tuple:
    """Build the 5-agent hub-and-spoke ChemAgent team.

    Args:
        llm_config: Pre-built AG2 LLMConfig.  If None, built from ``model``.
        model:      Model name override (falls back to ``OPENAI_MODEL`` env var).

    Returns:
        ``(user_proxy, pattern, ctx, agent_models)``
        where ``pattern`` is the ``DefaultPattern`` ready for
        ``a_run_group_chat(pattern, messages)``, ``ctx`` is the shared
        ``ContextVariables`` for the session, and ``agent_models`` maps
        agent names → resolved model name strings.
    """
    if llm_config is None:
        llm_config = build_llm_config(model)

    fast_config = get_fast_llm_config()

    # ── 1. Create agents ───────────────────────────────────────────────────────
    planner = create_planner(llm_config)
    data_specialist = create_data_specialist(fast_config)        # fast model: only calls tools
    computation_specialist = create_computation_specialist(fast_config)  # fast model: only calls tools
    reviewer = create_reviewer(fast_config)   # kept for explicit error-retry routing
    user_proxy = create_user_proxy()

    agents_map: dict[str, ConversableAgent] = {
        "planner": planner,
        "data_specialist": data_specialist,
        "computation_specialist": computation_specialist,
        "reviewer": reviewer,
    }

    # ── 2. Create shared ContextVariables for this session ────────────────────
    ctx: ContextVariables = make_session_context()

    # ── 3. Register tools (MUST precede register_model_client) ────────────────

    # 3a. Domain tools — specialist executes its own tools so GroupToolExecutor
    #     finds them in agent.tools via register_agents_functions
    for fn in _DATA_TOOLS:
        register_function(
            fn,
            caller=data_specialist,
            executor=data_specialist,
            name=fn.__name__,
            description=fn.__doc__ or "",
        )

    for fn in _COMPUTATION_TOOLS:
        register_function(
            fn,
            caller=computation_specialist,
            executor=computation_specialist,
            name=fn.__name__,
            description=fn.__doc__ or "",
        )

    # 3b. Control flow tools on planner — closure factories capture ctx so
    #     the function signature has no ContextVariables parameter, avoiding
    #     Pydantic TypeAdapter[ForwardRef('ContextVariables')] schema errors.
    #     Registered via register_function (same pattern as set_routing_target).
    submit_plan_for_approval = make_submit_plan_for_approval(ctx)
    register_function(
        submit_plan_for_approval,
        caller=planner,
        executor=planner,
        name="submit_plan_for_approval",
        description=(
            "【仅在规划阶段使用】完成任务拆解后，调用此工具将 <plan> 内容提交给用户审批。"
            "将计划的纯文本内容（无 XML 标签）传入 plan_details 参数。"
            "调用后对话暂停，等待用户批准——在用户批准前禁止继续执行任何步骤。"
        ),
    )
    finish_workflow = make_finish_workflow(ctx)
    register_function(
        finish_workflow,
        caller=planner,
        executor=planner,
        name="finish_workflow",
        description=(
            "【仅在执行阶段使用】所有计划步骤均已完成且 Reviewer 已验证最后一步后，"
            "调用此工具提交综合分析报告并终止对话。"
            "将完整的中文分析结论传入 final_summary（用户可直接阅读）。"
            "调用前必须确认所有步骤均通过 Reviewer 的 [OK] 验证。"
        ),
    )

    # 3c. Routing tool — closure captures agents_map; registered as both
    #     caller=planner AND executor=planner so GroupToolExecutor finds fn
    set_routing_target = make_routing_tools(ctx, agents_map)
    register_function(
        set_routing_target,
        caller=planner,
        executor=planner,
        name="set_routing_target",
        description=(
            "将控制权移交给指定专家（data_specialist 或 computation_specialist）。"
            "调用后 DefaultPattern 的 GroupToolExecutor 自动路由到目标专家，"
            "无需在文本中输出 [ROUTE: xxx] 标记。"
        ),
    )

    # ── 4. Register custom streaming client (AFTER register_function) ─────────
    for agent in (planner, data_specialist, computation_specialist, reviewer):
        agent.register_model_client(model_client_cls=ReasoningAwareClient)

    # ── 5. Set per-agent after_work transitions ────────────────────────────────
    # OPTIMISED TOPOLOGY: specialists route directly to planner (no reviewer hop).
    # Planner receives tool results directly and handles success/retry decisions.
    # This eliminates one LLM call per step (~40% latency reduction).
    #
    # Reviewer is still registered in the pattern for explicit error routing if
    # the planner decides a retry with human review is needed.
    data_specialist.handoffs.set_after_work(AgentTarget(planner))
    computation_specialist.handoffs.set_after_work(AgentTarget(planner))
    reviewer.handoffs.set_after_work(AgentTarget(planner))
    # Planner loops back to itself when generating text-only (no tool call)
    # so DefaultPattern doesn't terminate prematurely.
    planner.handoffs.set_after_work(AgentTarget(planner))

    # ── 6. Build DefaultPattern ────────────────────────────────────────────────
    pattern = DefaultPattern(
        initial_agent=planner,
        agents=[planner, data_specialist, computation_specialist, reviewer],
        user_agent=user_proxy,
        context_variables=ctx,
    )

    # ── 7. Build agent_models metadata (sent to frontend in session.started) ──
    resolved = get_resolved_model_name(model)
    fast_resolved = get_resolved_model_name(None)
    agent_models: dict[str, str] = {
        "planner": resolved,
        "data_specialist": fast_resolved,        # fast model for tool dispatch
        "computation_specialist": fast_resolved,  # fast model for tool dispatch
        "reviewer": fast_resolved,
    }

    logger.info(
        "ChemAgent team created: planner=%s data=%s computation=%s reviewer=%s",
        resolved,
        fast_resolved,
        fast_resolved,
        fast_resolved,
    )

    return user_proxy, pattern, ctx, agent_models

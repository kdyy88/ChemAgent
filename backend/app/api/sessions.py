"""
Redis-backed session management — stateless per-turn agent architecture.

Architecture change from v1 (in-memory ChatSession):
  v1: Each session held 9 AG2 agent objects in Python memory for 30 min TTL.
      50 sessions = 450 live agent objects consuming ~500 MB+ of RSS.

  v2: No persistent Python agent objects. Session state (turn history, model
      prefs) lives in Redis with 30-min TTL. Each WebSocket turn:
        1. read turn_history from Redis  (async, < 1 ms)
        2. build fresh AgentTeam         (sync in thread, ~1 ms)
        3. run routing + specialists     (sync in thread, 1-30 s)
        4. async synthesis to websocket  (async, streaming)
        5. push turn summary to Redis    (async, < 1 ms)
        6. del AgentTeam               → Python GC frees 9 objects immediately

Redis key schema
----------------
  session:{id}          hash   created_at, agent_models_json
  session:{id}:turns    list   JSON-encoded {user, result} (max len 3, TTL 1800 s)
"""

from __future__ import annotations

import json
import time
from uuid import uuid4

from autogen import ConversableAgent, LLMConfig
from autogen.io.run_response import RunResponseProtocol

from app.agents.manager import (
    create_routing_agent,
    parse_routing_decision,
    SYNTHESIS_SYSTEM_MESSAGE,
)
from app.agents.config import build_llm_config
from app.agents.specialists.visualizer import create_visualizer
from app.agents.specialists.researcher import create_researcher
from app.agents.specialists.analyst import create_analyst
from app.api.runtime import (
    AgentTeam,
    MultiAgentRunPlan,
    SpecialistSummary,
    build_synthesis_prompt,
    format_turn_history,
    today_str,
)
from app.core.redis_client import get_redis

SESSION_TTL = 1800          # 30 minutes
TURN_HISTORY_MAX = 3        # keep last N turns for routing context

# ── Redis helpers (async) ─────────────────────────────────────────────────────


def _session_key(session_id: str) -> str:
    return f"session:{session_id}"


def _turns_key(session_id: str) -> str:
    return f"session:{session_id}:turns"


async def create_session(
    agent_models: dict[str, str] | None = None,
) -> str:
    """Persist a new session to Redis. Returns the new session_id."""
    redis = get_redis()
    session_id = f"sess_{uuid4().hex}"
    key = _session_key(session_id)
    await redis.hset(key, mapping={
        "created_at": str(time.time()),
        "agent_models_json": json.dumps(agent_models or {}),
    })
    await redis.expire(key, SESSION_TTL)
    return session_id


async def session_exists(session_id: str) -> bool:
    """Return True if the session still lives in Redis."""
    redis = get_redis()
    return bool(await redis.exists(_session_key(session_id)))


async def get_session_meta(session_id: str) -> dict | None:
    """Return session metadata dict or None if session not found."""
    redis = get_redis()
    data = await redis.hgetall(_session_key(session_id))
    if not data:
        return None
    return {
        "session_id": session_id,
        "agent_models": json.loads(data.get("agent_models_json", "{}")),
    }


async def get_turn_history(session_id: str) -> list[dict]:
    """Return last ``TURN_HISTORY_MAX`` turns as a list of {user, result}."""
    redis = get_redis()
    raw_turns = await redis.lrange(_turns_key(session_id), -TURN_HISTORY_MAX, -1)
    turns: list[dict] = []
    for raw in raw_turns:
        try:
            turns.append(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return turns


async def push_turn(session_id: str, user: str, result_summary: str) -> None:
    """Append a turn summary to Redis and reset session TTL."""
    redis = get_redis()
    turns_key = _turns_key(session_id)
    entry = json.dumps({"user": user, "result": result_summary})
    await redis.rpush(turns_key, entry)
    await redis.ltrim(turns_key, -TURN_HISTORY_MAX, -1)
    await redis.expire(turns_key, SESSION_TTL)
    await redis.expire(_session_key(session_id), SESSION_TTL)


async def clear_session(session_id: str) -> None:
    """Delete all Redis keys belonging to this session."""
    redis = get_redis()
    await redis.delete(_session_key(session_id), _turns_key(session_id))


# ── Agent team helpers (sync — called in IO_POOL threads) ─────────────────────


def _resolved_model(models: dict, key: str) -> str:
    return build_llm_config(models.get(key)).config_list[0]["model"]


def _build_agent_team(agent_models: dict) -> tuple[AgentTeam, dict[str, str]]:
    """Instantiate AG2 agent objects for one turn. Takes ~1 ms (pure Python).

    Refactored to the modern single-agent pattern:
      - Each specialist is a single ConversableAgent + list[Tool].
      - No separate UserProxyAgent executor per specialist.
      - manager AssistantAgent removed (synthesis uses raw AsyncOpenAI).

    Returns (team, resolved_models).
    """
    resolved = {
        "manager":    _resolved_model(agent_models, "manager"),
        "visualizer": _resolved_model(agent_models, "visualizer"),
        "researcher": _resolved_model(agent_models, "researcher"),
        "analyst":    _resolved_model(agent_models, "analyst"),
    }

    router = create_routing_agent()
    visualizer, visualizer_tools = create_visualizer(model=agent_models.get("visualizer"))
    researcher, researcher_tools = create_researcher(model=agent_models.get("researcher"))
    analyst,    analyst_tools    = create_analyst(model=agent_models.get("analyst"))

    team = AgentTeam(
        router=router,
        visualizer=visualizer,
        visualizer_tools=visualizer_tools,
        researcher=researcher,
        researcher_tools=researcher_tools,
        analyst=analyst,
        analyst_tools=analyst_tools,
    )
    return team, resolved


def _do_routing(
    team: AgentTeam,
    prompt: str,
    turn_history: list[dict],
) -> dict:
    """Phase 1: run the Router synchronously with full history context.

    Uses the modern single-agent ConversableAgent.run(max_turns=1) pattern.
    Events are exhausted silently so result.summary is populated, then the
    routing JSON is parsed from that summary.
    """
    context_prefix = format_turn_history(turn_history)
    date_prefix = f"今日日期：{today_str()}"
    routing_prompt = (
        f"{date_prefix}\n{context_prefix}\n\n当前用户问题：{prompt}"
        if context_prefix
        else f"{date_prefix}\n\n当前用户问题：{prompt}"
    )

    result = team.router.run(
        message=routing_prompt,
        max_turns=1,
        clear_history=True,
        summary_method="last_msg",
        silent=True,
    )
    # Exhaust events so RunCompletionEvent populates result.summary
    for _ in result.events:
        pass
    routing_text = result.summary or ""
    return parse_routing_decision(routing_text)


def build_run_plan(
    prompt: str,
    turn_history: list[dict],
    agent_models: dict[str, str],
) -> tuple[MultiAgentRunPlan, AgentTeam, dict[str, str]]:
    """Build a MultiAgentRunPlan for this turn (sync, run inside asyncio.to_thread).

    Executes Phase 1 (routing) synchronously.  Phase 2 RunResponseProtocol
    objects are set up lazily (LLM calls fire only when events are iterated
    in the specialist drain functions inside event_bridge.py).

    Returns (plan, team, resolved_models).
    Caller must ``del team`` after streaming completes — this immediately
    frees all 9 AG2 agent objects so Python GC can reclaim the memory.
    """
    team, resolved_models = _build_agent_team(agent_models)

    # ── Phase 1 ───────────────────────────────────────────────────────────────
    routing = _do_routing(team, prompt, turn_history)
    route = routing["route"]
    refined = routing.get("refined_prompts") or {}
    rationale = routing.get("routing_rationale") or ""

    is_general = route == ["general"]
    phase2_items: list[tuple[str, RunResponseProtocol]] = []

    if not is_general:
        if "researcher" in route:
            res_prompt = refined.get("researcher") or prompt
            res_prompt = f"今日日期：{today_str()}\n\n{res_prompt}"
            phase2_items.append(("Researcher", team.researcher.run(
                message=res_prompt,
                tools=team.researcher_tools,
                clear_history=True,
                summary_method="last_msg",
                max_turns=6,   # 2 searches + refinements + summary, hard ceiling
                silent=False,
            )))

        if "visualizer" in route:
            vis_prompt = refined.get("visualizer") or prompt
            vis_prompt = f"今日日期：{today_str()}\n\n{vis_prompt}"
            phase2_items.append(("Visualizer", team.visualizer.run(
                message=vis_prompt,
                tools=team.visualizer_tools,
                clear_history=True,
                summary_method="last_msg",
                max_turns=6,   # 1 batch call + 1 retry + summary, hard ceiling
                silent=False,
            )))

        if "analyst" in route:
            ana_prompt = refined.get("analyst") or prompt
            ana_prompt = f"今日日期：{today_str()}\n\n{ana_prompt}"
            phase2_items.append(("Analyst", team.analyst.run(
                message=ana_prompt,
                tools=team.analyst_tools,
                clear_history=True,
                summary_method="last_msg",
                max_turns=4,   # 1-2 tool calls + summary, hard ceiling
                silent=False,
            )))

    # ── Phase 3 factory (called after Phase 2 exhausted) ─────────────────────
    manager_llm_config = build_llm_config(agent_models.get("manager"))

    def synthesis_factory(
        summaries: list[SpecialistSummary],
    ) -> tuple[str, str, LLMConfig]:
        synthesis_prompt = build_synthesis_prompt(
            original_prompt=prompt,
            routing_rationale=rationale,
            summaries=summaries,
            is_general=is_general,
        )
        return synthesis_prompt, SYNTHESIS_SYSTEM_MESSAGE, manager_llm_config

    plan = MultiAgentRunPlan(
        routing_rationale=rationale,
        phase2_items=phase2_items,
        synthesis_factory=synthesis_factory,
    )
    return plan, team, resolved_models


def run_greeting(agent_models: dict[str, str]) -> RunResponseProtocol:
    """Generate a greeting from a temporary ConversableAgent.

    Creates a fresh single-agent ConversableAgent for the greeting and immediately
    discards it. Does NOT build a full AgentTeam (manager was removed from AgentTeam
    in the v2 refactor since synthesis bypasses AG2 entirely via AsyncOpenAI).
    """
    from app.agents.config import build_llm_config as _build_llm_config
    greeter = ConversableAgent(
        name="Manager",
        system_message=SYNTHESIS_SYSTEM_MESSAGE,
        llm_config=_build_llm_config(agent_models.get("manager")),
        max_consecutive_auto_reply=1,
        human_input_mode="NEVER",
        code_execution_config=False,
    )
    return greeter.run(
        message=(
            "请用中文简短友好地问候用户，介绍你是专业化学助手 ChemAgent，"
            "简述你能帮助用户做什么（如查询化合物信息、绘制分子结构图、搜索文献等），"
            "并邀请用户提问。语气自然亲切，不超过3句话。纯文本，不要使用 Markdown。"
        ),
        clear_history=True,
        summary_method="last_msg",
        max_turns=2,  # one-shot: executor prompt → agent greeting reply
        silent=False,
    )

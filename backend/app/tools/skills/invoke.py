"""tool_invoke_skill — The SkillTool Bridge
==========================================

Implements the ``tool_invoke_skill`` LangChain tool that acts as the single
entry-point for the main agent to activate any registered skill.

Pipeline
--------
1. **Discovery** — Agent reads the L1 catalogue (always in system prompt) and
   identifies the skill whose ``when_to_use`` matches the current intent.
2. **Bridge** — Agent calls ``tool_invoke_skill(skill_name, arguments)``.
3. **Execution** — This tool loads the L2 SOP and either:
   - ``context=inline``: returns the SOP wrapped in a strong XML attention
     anchor so the agent continues its ReAct loop under skill instructions.
   - ``context=fork``:  delegates to an isolated sub-agent via the existing
     ``tool_run_sub_agent`` infrastructure (required_skills path), then returns
     the sub-agent result summary.

Security
--------
- Arguments are **never** substituted into the SOP via string replacement
  (prompt injection risk).  They are appended as a sanitised ``<arguments>``
  block by ``skills.loader.load_skill_sop``.
- Skill names are sanitised via ``_sanitize_skill_name`` before any filesystem
  access.
"""

from __future__ import annotations

import json
import logging

from app.tools.decorators import chem_tool

logger = logging.getLogger(__name__)


@chem_tool(tier="L1")
def tool_invoke_skill(skill_name: str, arguments: str = "{}") -> str:
    """Activate a registered skill by name and execute its SOP.

    Use this tool when the user's intent matches one of the skills listed in
    ``<available_skills>``.  Read each skill's ``when_to_use`` to decide.

    Parameters
    ----------
    skill_name:
        The exact ``name`` from the skill catalogue (e.g. ``"database-lookup"``).
    arguments:
        JSON string with key/value pairs matching the skill's declared
        ``arguments``.  Always include at least ``query`` (free-text intent),
        and ``smiles`` or ``artifact_id`` when a molecule is involved.
        Example: ``{"query": "aspirin", "smiles": "CC(=O)Oc1ccccc1C(=O)O"}``
    """
    # ── Parse arguments ────────────────────────────────────────────────────────
    try:
        parsed_args: dict = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError as exc:
        return json.dumps(
            {"status": "error", "error": f"Invalid JSON in arguments: {exc}"},
            ensure_ascii=False,
        )

    # ── Validate skill exists ──────────────────────────────────────────────────
    from app.skills.loader import load_skill_catalogue  # noqa: PLC0415

    catalogue = load_skill_catalogue()
    manifest = next((m for m in catalogue if m.name == skill_name), None)
    if manifest is None:
        available = [m.name for m in catalogue]
        return json.dumps(
            {
                "status": "error",
                "error": f"Skill not found: {skill_name!r}",
                "available_skills": available,
            },
            ensure_ascii=False,
        )

    # ── Dispatch by context ────────────────────────────────────────────────────
    if manifest.context == "inline":
        return _invoke_inline(skill_name, parsed_args)
    else:
        return _invoke_fork(skill_name, manifest, parsed_args)


# ── Inline execution ───────────────────────────────────────────────────────────


def _invoke_inline(skill_name: str, parsed_args: dict) -> str:
    """Load L2 SOP and return it with a strong XML attention anchor (雷3 対策)."""
    from app.skills.loader import load_skill_sop  # noqa: PLC0415

    try:
        sop_body = load_skill_sop(skill_name, parsed_args)
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    # The XML wrapper creates a strong attention anchor in the context window.
    # Plain JSON fields are forgotten as the context grows; a named XML block
    # is highly salient and models respect it across long multi-step traces.
    return (
        f"技能加载成功。请立刻停止闲聊，进入技能执行模式。\n"
        f"严格按照以下 XML 标签内的指令执行：\n\n"
        f'<skill_instructions name="{skill_name}">\n'
        f"{sop_body}\n"
        f"</skill_instructions>"
    )


# ── Fork execution ─────────────────────────────────────────────────────────────


def _invoke_fork(skill_name: str, manifest, parsed_args: dict) -> str:  # type: ignore[type-arg]
    """Delegate to an isolated sub-agent via tool_run_sub_agent (fork context).

    The sub-agent loads the full skill SOP via
    ``load_required_skill_markdown([skill_name])``—the existing path that reads
    the complete SKILL.md.  This deliberately avoids injecting the SOP through
    ``custom_instructions`` (max_length=2000 would be exceeded for rich skills).
    """
    import asyncio  # noqa: PLC0415

    from app.agents.sub_agents.tool import tool_run_sub_agent  # noqa: PLC0415

    task = parsed_args.get("task") or parsed_args.get("query") or skill_name
    smiles_policy = parsed_args.get("smiles_policy", "forbid_new")

    # Build the custom_tools list: skill's declared tools + the fetch/reference pair
    custom_tools = list(manifest.tool_names or [])
    for always_available in ("tool_fetch_chemistry_api", "tool_read_skill_reference"):
        if always_available not in custom_tools:
            custom_tools.append(always_available)

    try:
        result = asyncio.get_event_loop().run_until_complete(
            tool_run_sub_agent.ainvoke(
                {
                    "mode": "custom",
                    "task": str(task)[:1000],
                    "required_skills": [skill_name],
                    "custom_tools": custom_tools,
                    "smiles_policy": smiles_policy,
                }
            )
        )
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fork skill invocation failed: skill=%s", skill_name)
        return json.dumps(
            {"status": "error", "error": f"Fork execution failed: {exc}"},
            ensure_ascii=False,
        )

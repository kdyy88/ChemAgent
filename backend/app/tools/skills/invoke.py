"""tool_invoke_skill -- class-based BaseChemTool contract.

The SkillTool Bridge: single entry-point for the main agent to activate any
registered skill.

Security
--------
- Arguments are never substituted into the SOP via string replacement
  (prompt injection risk). They are appended as a sanitised <arguments>
  block by skills.loader.load_skill_sop.
- Skill names are sanitised via _sanitize_skill_name before any filesystem access.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemStateTool, _current_tool_config

logger = logging.getLogger(__name__)


class InvokeSkillInput(BaseModel):
    skill_name: str = Field(
        description="The exact name from the skill catalogue (e.g. 'database-lookup')"
    )
    arguments: str = Field(
        default="{}",
        description=(
            "JSON string with key/value pairs matching the skill's declared arguments. "
            "Always include at least 'query' (free-text intent), and 'smiles' or 'artifact_id' "
            "when a molecule is involved. "
            "Example: '{\"query\": \"aspirin\", \"smiles\": \"CC(=O)Oc1ccccc1C(=O)O\"}'"
        ),
    )


class ToolInvokeSkill(ChemStateTool[InvokeSkillInput, str]):
    """Activate a registered skill by name and execute its SOP.

    Use this tool when the user's intent matches one of the skills listed in
    ``<available_skills>``.  Read each skill's ``when_to_use`` to decide.
    """

    name = "tool_invoke_skill"
    args_schema = InvokeSkillInput
    tier = "L1"
    read_only = True
    max_result_size_chars = 16_000

    async def validate_input(
        self, args: InvokeSkillInput, context: dict
    ) -> ValidationResult:
        try:
            if args.arguments.strip():
                json.loads(args.arguments)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                result=False,
                message=f"Invalid JSON in arguments: {exc}",
            )
        return ValidationResult(result=True)

    def call(self, args: InvokeSkillInput) -> str:
        """Invoke a registered skill by name with JSON arguments and return its output."""
        parsed_args: dict = json.loads(args.arguments) if args.arguments.strip() else {}

        from app.skills.loader import load_skill_catalogue  # noqa: PLC0415

        catalogue = load_skill_catalogue()
        manifest = next((m for m in catalogue if m.name == args.skill_name), None)
        if manifest is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Skill not found: {args.skill_name!r}",
                    "available_skills": [m.name for m in catalogue],
                },
                ensure_ascii=False,
            )

        missing = [
            arg.name for arg in manifest.arguments
            if arg.required and arg.name not in parsed_args
        ]
        if missing:
            return json.dumps(
                {
                    "status": "error",
                    "error": (
                        f"Missing required arguments for skill {args.skill_name!r}: {missing}. "
                        "Use available tools to resolve them or ask the user."
                    ),
                },
                ensure_ascii=False,
            )

        if manifest.context == "inline":
            return _invoke_inline(args.skill_name, parsed_args)
        else:
            config = _current_tool_config.get()
            return _invoke_fork(args.skill_name, manifest, parsed_args, config)


def _invoke_inline(skill_name: str, parsed_args: dict) -> str:
    from app.skills.loader import load_skill_sop  # noqa: PLC0415

    try:
        sop_body = load_skill_sop(skill_name, parsed_args)
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    return (
        f"技能加载成功。请立刻停止闲聊，进入技能执行模式。\n"
        f"严格按照以下 XML 标签内的指令执行：\n\n"
        f'<skill_instructions name="{skill_name}">\n'
        f"{sop_body}\n"
        f"</skill_instructions>"
    )


def _invoke_fork(skill_name: str, manifest, parsed_args: dict, config) -> str:  # type: ignore[type-arg]
    import asyncio  # noqa: PLC0415

    from app.agents.sub_agents.tool import tool_run_sub_agent  # noqa: PLC0415

    task = parsed_args.get("task") or parsed_args.get("query") or skill_name
    smiles_policy = parsed_args.get("smiles_policy", "forbid_new")

    custom_tools = list(manifest.tool_names or [])
    for always_available in ("tool_fetch_chemistry_api", "tool_read_skill_reference"):
        if always_available not in custom_tools:
            custom_tools.append(always_available)

    invoke_input = {
        "mode": "custom",
        "task": str(task)[:1000],
        "required_skills": [skill_name],
        "custom_tools": custom_tools,
        "smiles_policy": smiles_policy,
    }

    try:
        result = asyncio.run(
            tool_run_sub_agent.ainvoke(invoke_input, config=config)
        )
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fork skill invocation failed: skill=%s", skill_name)
        return json.dumps(
            {"status": "error", "error": f"Fork execution failed: {exc}"},
            ensure_ascii=False,
        )


tool_invoke_skill = ToolInvokeSkill().as_langchain_tool()

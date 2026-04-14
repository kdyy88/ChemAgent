"""tool_read_skill_reference -- class-based BaseChemTool contract.

Progressive Disclosure L3 gate: fetches named reference files from
app/skills/builtin/{skill}/references/ on demand.

Security
--------
- Both skill_name and reference_name are sanitised via _sanitize_skill_name
  (alphanumeric + ._- only) in validate_input().
- The resolved path is checked to lie strictly under _BUILTIN_SKILLS_ROOT
  to prevent directory-traversal attacks.  Path traversal detection is
  done in validate_input() (parameter error -- model retries).
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemStateTool

logger = logging.getLogger(__name__)


class ReadSkillReferenceInput(BaseModel):
    skill_name: str = Field(
        description="The skill name, e.g. 'database-lookup'."
    )
    reference_name: str = Field(
        description=(
            "The reference filename without the .md extension, e.g. 'pubchem', "
            "'chembl', 'uniprot'. If unsure, call with any name and the error "
            "response will list all available references."
        )
    )


class ToolReadSkillReference(ChemStateTool[ReadSkillReferenceInput, str]):
    """Read a reference document from a skill's ``references/`` directory (L3).

    Call this after ``tool_invoke_skill`` returns the SOP and you need the
    detailed API endpoint documentation for a specific database before making
    an API call.
    """

    name = "tool_read_skill_reference"
    args_schema = ReadSkillReferenceInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 32_000

    async def validate_input(
        self, args: ReadSkillReferenceInput, context: dict
    ) -> ValidationResult:
        from app.skills.loader import _BUILTIN_SKILLS_ROOT, _sanitize_skill_name  # noqa: PLC0415

        try:
            safe_skill = _sanitize_skill_name(args.skill_name)
            safe_ref = _sanitize_skill_name(args.reference_name)
        except ValueError as exc:
            return ValidationResult(result=False, message=str(exc))

        # Path-traversal check at validate_input stage (parameter error -> model retries)
        root = _BUILTIN_SKILLS_ROOT.resolve()
        ref_path = (root / safe_skill / "references" / f"{safe_ref}.md").resolve()
        if root not in ref_path.parents:
            return ValidationResult(
                result=False,
                message="Path traversal detected in skill/reference name -- request denied.",
            )
        return ValidationResult(result=True)

    def call(self, args: ReadSkillReferenceInput) -> str:
        """Read the reference documentation for a skill from the built-in or custom skill library."""
        from app.skills.loader import _BUILTIN_SKILLS_ROOT, _sanitize_skill_name  # noqa: PLC0415

        safe_skill = _sanitize_skill_name(args.skill_name)
        safe_ref = _sanitize_skill_name(args.reference_name)

        root = _BUILTIN_SKILLS_ROOT.resolve()
        ref_path = (root / safe_skill / "references" / f"{safe_ref}.md").resolve()

        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8")

        ref_dir = (root / safe_skill / "references").resolve()
        available = sorted(p.stem for p in ref_dir.glob("*.md")) if ref_dir.is_dir() else []
        return json.dumps(
            {
                "status": "error",
                "message": f"Reference not found: {safe_skill}/{safe_ref}",
                "available_references": available,
            },
            ensure_ascii=False,
        )


tool_read_skill_reference = ToolReadSkillReference().as_langchain_tool()

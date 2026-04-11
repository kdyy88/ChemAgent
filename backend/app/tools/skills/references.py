"""tool_read_skill_reference — Progressive Disclosure L3 gate
=============================================================

Fetches a named reference file from ``app/skills/builtin/{skill}/references/``
on demand.  This is the L3 layer of the skill progressive disclosure model:

  L1 — ``name + description + when_to_use`` always present in system prompt
  L2 — Full SOP body returned by ``tool_invoke_skill``
  L3 — Reference docs fetched here as the agent needs them

Security
--------
- Both ``skill_name`` and ``reference_name`` are sanitised via
  ``_sanitize_skill_name`` (alphanumeric + ``._-`` only).
- The resolved path is checked to lie strictly under ``_BUILTIN_SKILLS_ROOT``
  to prevent directory-traversal attacks (e.g. ``../../etc/passwd``).
"""

from __future__ import annotations

import json
import logging

from app.tools.decorators import chem_tool

logger = logging.getLogger(__name__)


@chem_tool(tier="L1")
def tool_read_skill_reference(skill_name: str, reference_name: str) -> str:
    """Read a reference document from a skill's ``references/`` directory (L3).

    Call this after ``tool_invoke_skill`` returns the SOP and you need the
    detailed API endpoint documentation for a specific database before making
    an API call.

    Parameters
    ----------
    skill_name:
        The skill name, e.g. ``"database-lookup"``.
    reference_name:
        The reference filename without the ``.md`` extension, e.g.
        ``"pubchem"``, ``"chembl"``, ``"uniprot"``.
        If you are unsure which references are available, call this tool with
        any name and the error response will list all available references.
    """
    from app.skills.loader import _BUILTIN_SKILLS_ROOT, _sanitize_skill_name  # noqa: PLC0415

    # ── Sanitise both path components ─────────────────────────────────────────
    try:
        safe_skill = _sanitize_skill_name(skill_name)
        safe_ref = _sanitize_skill_name(reference_name)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    root = _BUILTIN_SKILLS_ROOT.resolve()
    ref_path = (root / safe_skill / "references" / f"{safe_ref}.md").resolve()

    # ── Path containment check (prevent directory traversal) ──────────────────
    if root not in ref_path.parents:
        return json.dumps(
            {"status": "error", "error": "Path traversal detected — request denied."},
            ensure_ascii=False,
        )

    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8")

    # ── Reference not found — return available list ────────────────────────────
    ref_dir = (root / safe_skill / "references").resolve()
    if ref_dir.is_dir():
        available = sorted(p.stem for p in ref_dir.glob("*.md"))
    else:
        available = []

    return json.dumps(
        {
            "status": "error",
            "message": f"Reference not found: {safe_skill}/{safe_ref}",
            "available_references": available,
        },
        ensure_ascii=False,
    )

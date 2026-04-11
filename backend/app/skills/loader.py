from __future__ import annotations

import html
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# ── Path roots ────────────────────────────────────────────────────────────────

# Built-in skills bundled with the application: app/skills/builtin/
_BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parent / "builtin"

# Legacy flat doc skills (docs/subagent-skills/*.md) — kept for backward compat
_DEFAULT_SKILLS_ROOT = Path(
    os.getenv(
        "CHEMAGENT_SKILLS_DIR",
        Path(__file__).resolve().parents[3] / "docs" / "subagent-skills",
    )
)

# ── Module-level catalogue cache ──────────────────────────────────────────────

_CATALOGUE_CACHE: list[Any] | None = None  # list[SkillManifest], typed Any to avoid circular import


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sanitize_skill_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized or not _SAFE_SKILL_NAME.fullmatch(normalized):
        raise ValueError(f"Unsafe skill name: {name!r}")
    return normalized


def _skill_path(name: str) -> Path:
    """Legacy flat-file path under _DEFAULT_SKILLS_ROOT."""
    safe_name = _sanitize_skill_name(name)
    root = _DEFAULT_SKILLS_ROOT.resolve()
    path = (root / f"{safe_name}.md").resolve()
    if root not in (path, *path.parents):
        raise ValueError(f"Skill path escapes configured root: {safe_name!r}")
    return path


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown file into (frontmatter_dict, body).

    Parses the leading ``---…---`` YAML block.  Returns ``({}, full_text)``
    if no frontmatter is present.  Uses ``yaml.safe_load`` — never ``yaml.load``.
    """
    import yaml  # noqa: PLC0415 — deferred; yaml is in pyproject.toml

    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text

    end = stripped.find("\n---", 3)
    if end == -1:
        return {}, text

    yaml_src = stripped[3:end].strip()
    body = stripped[end + 4:].lstrip("\n")

    try:
        data = yaml.safe_load(yaml_src) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse skill frontmatter: %s", exc)
        return {}, text

    return data if isinstance(data, dict) else {}, body


# ── L1: Catalogue (always-loaded metadata) ────────────────────────────────────


def load_skill_catalogue(*, force_reload: bool = False) -> list[Any]:
    """Return L1 catalogue: one ``SkillManifest`` per built-in skill.

    Results are cached at module level — zero filesystem I/O per request after
    first call.  Pass ``force_reload=True`` in tests or after hot-reload.
    """
    global _CATALOGUE_CACHE  # noqa: PLW0603

    if _CATALOGUE_CACHE is not None and not force_reload:
        return _CATALOGUE_CACHE

    from app.skills.base import SkillManifest  # noqa: PLC0415

    manifests: list[SkillManifest] = []
    for skill_md in sorted(_BUILTIN_SKILLS_ROOT.glob("*/SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
            fm, _ = _parse_frontmatter(text)
            if not fm.get("name"):
                logger.warning("Skill at %s has no 'name' in frontmatter — skipped", skill_md)
                continue
            # Pydantic validates and coerces; unknown keys are ignored (extra="ignore")
            manifest = SkillManifest.model_validate(fm)
            manifests.append(manifest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load skill from %s: %s", skill_md, exc)

    _CATALOGUE_CACHE = manifests
    logger.debug("Loaded %d built-in skill(s) into catalogue", len(manifests))
    return manifests


# ── L2: SOP body (activated on demand) ───────────────────────────────────────


def load_skill_sop(skill_name: str, arguments: dict[str, Any] | None = None) -> str:
    """Return the L2 SOP body for *skill_name* with arguments appended.

    The body is the full ``SKILL.md`` content with the YAML frontmatter stripped.
    Arguments are **never** substituted via string replacement (prompt injection
    risk).  Instead, non-empty arguments are appended as a structured
    ``<arguments>`` block using ``html.escape`` on every value, allowing the LLM
    to perform semantic binding.
    """
    safe_name = _sanitize_skill_name(skill_name)
    root = _BUILTIN_SKILLS_ROOT.resolve()
    skill_md_path = (root / safe_name / "SKILL.md").resolve()

    if root not in skill_md_path.parents:
        raise ValueError(f"Skill path escapes root: {safe_name!r}")

    if not skill_md_path.exists():
        raise FileNotFoundError(
            f"Skill SOP not found: {safe_name!r} "
            f"(expected {skill_md_path})"
        )

    text = skill_md_path.read_text(encoding="utf-8").strip()
    _, body = _parse_frontmatter(text)
    body = body.strip()

    if arguments:
        arg_lines = [
            f"  <{html.escape(str(k))}>{html.escape(str(v))}</{html.escape(str(k))}>"
            for k, v in arguments.items()
            if v is not None and str(v).strip()
        ]
        if arg_lines:
            body = body + "\n\n<arguments>\n" + "\n".join(arg_lines) + "\n</arguments>"

    return body


# ── Backward-compat: loads full SKILL.md for custom sub-agents ────────────────


def load_required_skill_markdown(required_skills: list[str] | None) -> str:
    """Load markdown skills for custom sub-agent prompt injection (legacy path).

    Resolution order:
    1. ``_BUILTIN_SKILLS_ROOT/{name}/SKILL.md`` (full content including frontmatter)
    2. ``_DEFAULT_SKILLS_ROOT/{name}.md``         (legacy flat doc files)
    """
    unique_names: list[str] = []
    for raw_name in required_skills or []:
        safe_name = _sanitize_skill_name(raw_name)
        if safe_name not in unique_names:
            unique_names.append(safe_name)

    if not unique_names:
        return ""

    sections: list[str] = []
    for skill_name in unique_names:
        # 1. Try built-in bundled skill
        builtin_path = (_BUILTIN_SKILLS_ROOT / skill_name / "SKILL.md").resolve()
        if _BUILTIN_SKILLS_ROOT.resolve() in builtin_path.parents and builtin_path.exists():
            content = builtin_path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f'<skill name="{skill_name}">\n{content}\n</skill>')
                continue

        # 2. Fall back to legacy flat doc file
        path = _skill_path(skill_name)
        if not path.exists():
            raise FileNotFoundError(f"Skill markdown not found: {skill_name}")
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Skill markdown is empty: {skill_name}")
        sections.append(f'<skill name="{skill_name}">\n{content}\n</skill>')

    return "\n\n".join(sections)
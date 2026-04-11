"""
Skills manager — top-level capability loader for ChemAgent.

Responsible for scanning the configured skills root, validating skill names,
and loading skill Markdown into prompt-injectable XML blocks.  Usable by both
the main agent and sub-agents; no dependency on ``agents/`` internals.

Skills root is resolved from the ``CHEMAGENT_SKILLS_DIR`` env variable, falling
back to ``<project>/backend/app/skills``.

Skill directory layout
----------------------
- ``<name>/SKILL.md`` — sub-directory style (preferred)
- ``<name>.md`` — top-level file style (legacy compat)

Each SKILL.md may contain YAML frontmatter (``---`` delimited) with fields:
``name``, ``description``, ``whenToUse``, ``applicableModes``.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_DEFAULT_SKILLS_ROOT = Path(
    os.getenv(
        "CHEMAGENT_SKILLS_DIR",
        str(Path(__file__).resolve().parent),
    )
)

# ── Frontmatter parsing ──────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^\s+-\s+(.+)", re.MULTILINE)


def _parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    """Parse simple YAML frontmatter without requiring PyYAML."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, str | list[str]] = {}
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        kv = _KV_RE.match(lines[i])
        if kv:
            key, value = kv.group(1), kv.group(2).strip()
            if not value:
                # Might be a list on subsequent lines
                items: list[str] = []
                i += 1
                while i < len(lines):
                    li = _LIST_ITEM_RE.match(lines[i])
                    if li:
                        items.append(li.group(1).strip())
                        i += 1
                    else:
                        break
                result[key] = items if items else ""
                continue
            result[key] = value
        i += 1
    return result


# ── SkillMeta ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkillMeta:
    """Lightweight metadata for a skill, parsed from frontmatter."""

    name: str
    description: str = ""
    when_to_use: str = ""
    applicable_modes: tuple[str, ...] = ()
    path: Path = field(default_factory=lambda: Path("."))


# ── Scanning ──────────────────────────────────────────────────────────────────

_skill_cache: list[SkillMeta] | None = None


def _scan_skills_root(root: Path) -> list[SkillMeta]:
    """Walk *root* for skill files and parse their frontmatter."""
    resolved = root.resolve()
    if not resolved.is_dir():
        logger.warning("Skills root does not exist: %s", resolved)
        return []

    skills: list[SkillMeta] = []

    # Sub-directory style: <name>/SKILL.md
    for child in sorted(resolved.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        meta = _meta_from_file(skill_file, fallback_name=child.name)
        if meta:
            skills.append(meta)

    # Top-level file style: <name>.md (skip __init__.py, manager.py etc.)
    for child in sorted(resolved.glob("*.md")):
        if not child.is_file():
            continue
        meta = _meta_from_file(child, fallback_name=child.stem)
        if meta:
            # Avoid duplicates if a sub-directory skill has the same name
            if not any(s.name == meta.name for s in skills):
                skills.append(meta)

    return skills


def _meta_from_file(path: Path, *, fallback_name: str) -> SkillMeta | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Cannot read skill file: %s", path)
        return None

    fm = _parse_frontmatter(text)
    name = str(fm.get("name") or fallback_name).strip()
    if not name or not _SAFE_SKILL_NAME.fullmatch(name):
        logger.warning("Skipping skill with invalid name: %s", path)
        return None

    modes_raw = fm.get("applicableModes", [])
    modes = tuple(modes_raw) if isinstance(modes_raw, list) else ()

    return SkillMeta(
        name=name,
        description=str(fm.get("description") or ""),
        when_to_use=str(fm.get("whenToUse") or ""),
        applicable_modes=modes,
        path=path,
    )


def scan_all_skills(*, _force: bool = False) -> list[SkillMeta]:
    """Return metadata for all discovered skills (cached after first call)."""
    global _skill_cache  # noqa: PLW0603
    if _skill_cache is not None and not _force:
        return _skill_cache
    _skill_cache = _scan_skills_root(_DEFAULT_SKILLS_ROOT)
    return _skill_cache


def invalidate_skill_cache() -> None:
    """Force a rescan on next ``scan_all_skills()`` call (useful in tests)."""
    global _skill_cache  # noqa: PLW0603
    _skill_cache = None


# ── Skill listing (compact XML for system-prompt injection) ───────────────────


def format_skill_listing(modes: list[str] | None = None) -> str:
    """Return a compact ``<available_skills>`` XML block for prompt injection.

    Only skills whose ``applicable_modes`` intersect *modes* are included.
    If *modes* is ``None`` all skills are returned.
    """
    all_skills = scan_all_skills()
    if modes is not None:
        mode_set = set(modes)
        filtered = [s for s in all_skills if not s.applicable_modes or mode_set & set(s.applicable_modes)]
    else:
        filtered = list(all_skills)

    if not filtered:
        return ""

    lines = ["<available_skills>"]
    for s in filtered:
        attrs = f'name="{s.name}"'
        if s.description:
            attrs += f' description="{s.description}"'
        if s.when_to_use:
            attrs += f' whenToUse="{s.when_to_use}"'
        lines.append(f"  <skill {attrs}/>")
    lines.append("</available_skills>")
    return "\n".join(lines)


# ── On-demand full-content loading ────────────────────────────────────────────


def load_skill_by_name(name: str) -> str:
    """Load the full Markdown content of a single skill by *name*.

    Performs path-traversal protection via ``_sanitize_skill_name`` and verifies
    the resolved path falls within the skills root.

    Returns the raw Markdown content (including frontmatter).
    Raises ``FileNotFoundError`` if the skill is not registered.
    """
    safe_name = _sanitize_skill_name(name)
    all_skills = scan_all_skills()
    for skill in all_skills:
        if skill.name == safe_name:
            resolved = skill.path.resolve()
            root = _DEFAULT_SKILLS_ROOT.resolve()
            if root not in (resolved, *resolved.parents):
                raise ValueError(f"Skill path escapes configured root: {safe_name!r}")
            content = resolved.read_text(encoding="utf-8").strip()
            if not content:
                raise ValueError(f"Skill markdown is empty: {safe_name}")
            return content
    raise FileNotFoundError(f"Skill not found: {safe_name}")


# ── Legacy API (backward compat for custom mode) ─────────────────────────────


def _sanitize_skill_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized or not _SAFE_SKILL_NAME.fullmatch(normalized):
        raise ValueError(f"Unsafe skill name: {name!r}")
    return normalized


def load_required_skill_markdown(required_skills: list[str] | None) -> str:
    """Load local markdown skills for prompt injection (legacy API).

    De-duplicates names, wraps each file in ``<skill name="...">`` XML tags,
    and returns the concatenated block ready for system-prompt injection.
    Raises ``FileNotFoundError`` / ``ValueError`` on missing or empty skills.
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
        content = load_skill_by_name(skill_name)
        sections.append(
            "\n".join(
                [
                    f'<skill name="{skill_name}">',
                    content,
                    "</skill>",
                ]
            )
        )

    return "\n\n".join(sections)

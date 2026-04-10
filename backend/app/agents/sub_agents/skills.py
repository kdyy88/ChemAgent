from __future__ import annotations

import os
import re
from pathlib import Path

_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_DEFAULT_SKILLS_ROOT = Path(
    os.getenv(
        "CHEMAGENT_SKILLS_DIR",
        Path(__file__).resolve().parents[4] / "docs" / "subagent-skills",
    )
)


def _sanitize_skill_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized or not _SAFE_SKILL_NAME.fullmatch(normalized):
        raise ValueError(f"Unsafe skill name: {name!r}")
    return normalized


def _skill_path(name: str) -> Path:
    safe_name = _sanitize_skill_name(name)
    root = _DEFAULT_SKILLS_ROOT.resolve()
    path = (root / f"{safe_name}.md").resolve()
    if root not in (path, *path.parents):
        raise ValueError(f"Skill path escapes configured root: {safe_name!r}")
    return path


def load_required_skill_markdown(required_skills: list[str] | None) -> str:
    """Load local markdown skills for custom sub-agent prompt injection."""
    unique_names: list[str] = []
    for raw_name in required_skills or []:
        safe_name = _sanitize_skill_name(raw_name)
        if safe_name not in unique_names:
            unique_names.append(safe_name)

    if not unique_names:
        return ""

    sections: list[str] = []
    for skill_name in unique_names:
        path = _skill_path(skill_name)
        if not path.exists():
            raise FileNotFoundError(f"Skill markdown not found: {skill_name}")
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Skill markdown is empty: {skill_name}")
        sections.append(
            "\n".join(
                [
                    f"<skill name=\"{skill_name}\">",
                    content,
                    "</skill>",
                ]
            )
        )

    return "\n\n".join(sections)
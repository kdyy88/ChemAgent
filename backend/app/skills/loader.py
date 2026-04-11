"""
skills/loader.py — Per-session skill discovery and tool binding.

The SessionSkillLoader is the main entry point for the agents layer to get
the active tool list and prompt injection for a given session.

Flow:
  1. On SSE request arrival, call SessionSkillLoader.load(session_id)
  2. Loader reads session skill config (Redis or default built-ins)
  3. Returns (active_tools, prompt_injection_text)
  4. Main agent calls llm.bind_tools(active_tools) + injects prompt_injection_text

Session skill config is stored in Redis under:
  chemagent:session-skills:{session_id}  → JSON list of skill names

If no config exists, all enabled_by_default skills are activated.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.skills.base import SkillManifest
from app.tools.registry import TOOL_REGISTRY, ToolRegistry, get_populated_registry

log = logging.getLogger(__name__)

# ── Built-in skill registry ───────────────────────────────────────────────────
_SKILL_REGISTRY: dict[str, SkillManifest] = {}


def register_skill(manifest: SkillManifest) -> None:
    """Register a skill manifest (called by builtin skill modules on import)."""
    _SKILL_REGISTRY[manifest.name] = manifest


def _ensure_skills_loaded() -> None:
    """Import all builtin skill manifests to trigger self-registration."""
    from app.skills.builtin.rdkit_analysis import manifest as _rdkit  # noqa: F401
    from app.skills.builtin.mol_3d import manifest as _mol3d           # noqa: F401


# ── Session skill loader ──────────────────────────────────────────────────────

class SessionSkillLoader:
    """Resolves the active skill set for a given session_id."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._tool_registry = registry or get_populated_registry()

    async def load(
        self,
        session_id: str,
        *,
        skill_overrides: list[str] | None = None,
    ) -> tuple[list[Any], str]:
        """
        Returns (active_tools, prompt_injection) for the session.

        Parameters
        ----------
        session_id:
            The LangGraph thread_id / frontend session_id.
        skill_overrides:
            If provided, use these skill names instead of the session config.
            Useful for SubAgentDelegation that specifies explicit skills.
        """
        _ensure_skills_loaded()

        active_skill_names = skill_overrides or await self._read_session_skills(session_id)
        active_tools, prompt_parts = [], []

        for name in active_skill_names:
            manifest = _SKILL_REGISTRY.get(name)
            if manifest is None:
                log.warning("Skill '%s' not found in registry — skipping", name)
                continue
            tools = self._tool_registry.get_tools_by_names(manifest.tool_names)
            active_tools.extend(tools)
            if manifest.prompt_fragment:
                prompt_parts.append(manifest.prompt_fragment)

        prompt_injection = "\n\n".join(prompt_parts)
        log.debug(
            "Session %s: loaded %d tools from skills %s",
            session_id,
            len(active_tools),
            active_skill_names,
        )
        return active_tools, prompt_injection

    async def _read_session_skills(self, session_id: str) -> list[str]:
        """Read skill names from Redis, falling back to enabled_by_default."""
        try:
            from app.core.redis_pool import get_redis_pool
            redis = await get_redis_pool()
            raw = await redis.get(f"chemagent:session-skills:{session_id}")
            if raw:
                return json.loads(raw)
        except Exception as exc:
            log.debug("Could not read session skills from Redis: %s", exc)

        # Default: all enabled_by_default skills
        return [name for name, m in _SKILL_REGISTRY.items() if m.enabled_by_default]

    async def save_session_skills(self, session_id: str, skill_names: list[str]) -> None:
        """Persist skill configuration for a session."""
        try:
            from app.core.redis_pool import get_redis_pool
            redis = await get_redis_pool()
            await redis.set(
                f"chemagent:session-skills:{session_id}",
                json.dumps(skill_names),
                ex=86400,  # 24h TTL
            )
        except Exception as exc:
            log.warning("Could not save session skills to Redis: %s", exc)

"""Sub-Agent Tool Registry
==========================

Deny-by-default whitelist registry for sub-agent tool permissions.

Design
------
- ``ALWAYS_DENIED`` tools are stripped from **every** mode, regardless of what
  the caller requests.  This enforces the three inviolable contracts:
    - ``run_sub_agent`` is never available to sub-agents (depth=1 anti-recursion).
    - ``tool_ask_human`` is exclusive to the root agent (HITL clarification cannot
      bubble up from a sub-agent prompt).
    - ``tool_update_task_status`` belongs to the root agent's planner only.
- Each ``SubAgentMode`` maps to a frozenset of allowed tool names (whitelist).
- ``get_tools_for_mode()`` looks up the whitelist, validates any caller-specified
  overrides, and returns the resolved ``list[BaseTool]``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


# ── Mode definitions ──────────────────────────────────────────────────────────


class SubAgentMode(str, Enum):
    explore = "explore"   # Read-only investigation (RDKit + PubChem + web)
    plan    = "plan"      # Pure-LLM structured planning, no tools
    general = "general"   # Full chemistry execution (RDKit + Babel)
    custom  = "custom"    # Caller-defined whitelist


# ── Always-denied list (anti-recursion + HITL safety) ────────────────────────

ALWAYS_DENIED: frozenset[str] = frozenset({
    # Prevent depth > 1 recursion — sub-agents cannot spawn sub-agents.
    "tool_run_sub_agent",
    # HITL clarification flows through the root agent only.
    "tool_ask_human",
    # Task status book-keeping is owned by the root planner.
    "tool_update_task_status",
})


# ── Per-mode whitelists ───────────────────────────────────────────────────────

_EXPLORE_TOOLS: frozenset[str] = frozenset({
    # Safe read-only RDKit operations
    "tool_validate_smiles",
    "tool_evaluate_molecule",
    "tool_compute_descriptors",
    "tool_compute_similarity",
    "tool_substructure_match",
    "tool_murcko_scaffold",
    "tool_strip_salts",
    # Rendering (read-only, generates artifact pointer)
    "tool_render_smiles",
    # External lookups (read-only)
    "tool_pubchem_lookup",
    "tool_web_search",
    # Lightweight Babel inspection
    "tool_compute_mol_properties",
    "tool_list_formats",
})

_PLAN_TOOLS: frozenset[str] = frozenset()  # no tools — pure LLM reasoning

_GENERAL_TOOLS: frozenset[str] = frozenset({
    # Full RDKit suite
    "tool_validate_smiles",
    "tool_evaluate_molecule",
    "tool_compute_descriptors",
    "tool_compute_similarity",
    "tool_substructure_match",
    "tool_murcko_scaffold",
    "tool_strip_salts",
    "tool_render_smiles",
    "tool_pubchem_lookup",
    "tool_web_search",
    # Full Babel suite
    "tool_convert_format",
    "tool_build_3d_conformer",
    "tool_prepare_pdbqt",
    "tool_compute_mol_properties",
    "tool_compute_partial_charges",
    "tool_list_formats",
})

# custom mode uses caller-provided list (validated at runtime)

TOOL_PERMISSIONS: dict[SubAgentMode, frozenset[str]] = {
    SubAgentMode.explore: _EXPLORE_TOOLS,
    SubAgentMode.plan:    _PLAN_TOOLS,
    SubAgentMode.general: _GENERAL_TOOLS,
    # custom: resolved dynamically in get_tools_for_mode
}


# ── Resolver ──────────────────────────────────────────────────────────────────


def get_tools_for_mode(
    mode: SubAgentMode,
    custom_tools: list[str] | None = None,
) -> list[Any]:
    """Return the filtered list of LangChain tool objects for *mode*.

    Parameters
    ----------
    mode:
        The sub-agent operating mode; controls the base whitelist.
    custom_tools:
        For ``SubAgentMode.custom`` only — caller-specified allowlist of
        tool names. Entries in ``ALWAYS_DENIED`` are stripped silently.
        Unknown tool names raise ``ValueError``.

    Returns
    -------
    list[BaseTool]
        Ordered list of permitted LangChain tool objects.

    Raises
    ------
    ValueError
        If *mode* is ``custom`` and *custom_tools* contains an unrecognised name.
    """
    # Lazy import to break the circular reference:
    # lg_tools → tools/sub_agent → tool_registry → lg_tools
    from app.agents.lg_tools import ALL_CHEM_TOOLS  # noqa: PLC0415

    catalog: dict[str, Any] = {t.name: t for t in ALL_CHEM_TOOLS}

    if mode == SubAgentMode.custom:
        if not custom_tools:
            # No tools requested — behave like plan mode (pure LLM)
            return []
        # Validate against catalog; strip denied tools silently.
        unknown = [n for n in custom_tools if n not in catalog and n not in ALWAYS_DENIED]
        if unknown:
            raise ValueError(
                f"Unknown tool names for custom sub-agent: {unknown}. "
                f"Valid names: {sorted(catalog)}"
            )
        allowed_names = [n for n in custom_tools if n not in ALWAYS_DENIED and n in catalog]
    else:
        whitelist = TOOL_PERMISSIONS[mode]
        # Redundant safety pass: also strip ALWAYS_DENIED in case whitelist
        # was edited inadvertently.
        allowed_names = [n for n in whitelist if n not in ALWAYS_DENIED and n in catalog]

    return [catalog[name] for name in allowed_names]

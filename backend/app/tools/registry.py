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

from app.tools.decorators import CHEM_TIER_METADATA_KEY, ChemToolTier


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

_CONTROL_TOOLS: frozenset[str] = frozenset({
    "tool_run_sub_agent",
    "tool_ask_human",
    "tool_update_task_status",
})

_STATIC_TIER_OVERRIDES: dict[str, ChemToolTier] = {
    "tool_validate_smiles": "L1",
    "tool_evaluate_molecule": "L1",
    "tool_compute_descriptors": "L1",
    "tool_compute_similarity": "L1",
    "tool_substructure_match": "L1",
    "tool_murcko_scaffold": "L1",
    "tool_strip_salts": "L1",
    "tool_render_smiles": "L1",
    "tool_pubchem_lookup": "L1",
    "tool_web_search": "L1",
    "tool_compute_mol_properties": "L1",
    "tool_list_formats": "L1",
    "tool_convert_format": "L2",
    "tool_build_3d_conformer": "L2",
    "tool_prepare_pdbqt": "L2",
    "tool_compute_partial_charges": "L2",
}


def _tool_catalog() -> dict[str, Any]:
    from app.tools.chem import ALL_CHEM_TOOLS  # noqa: PLC0415

    return {t.name: t for t in ALL_CHEM_TOOLS}


def get_tool_tier(tool_or_name: Any) -> ChemToolTier | None:
    """Return the configured L1/L2 tier for a tool object or tool name."""
    if isinstance(tool_or_name, str):
        tool_name = tool_or_name
        metadata: dict[str, Any] = {}
    else:
        tool_name = str(getattr(tool_or_name, "name", "") or "").strip()
        metadata = dict(getattr(tool_or_name, "metadata", None) or {})

    tier = metadata.get(CHEM_TIER_METADATA_KEY)
    if tier in {"L1", "L2"}:
        return tier
    return _STATIC_TIER_OVERRIDES.get(tool_name)


def get_tools_by_tier(
    tier: ChemToolTier,
    *,
    include_control_tools: bool = False,
) -> list[Any]:
    """Return all registered chemistry tools for the requested tier."""
    catalog = _tool_catalog()
    allowed_names = [
        name
        for name, tool_obj in catalog.items()
        if get_tool_tier(tool_obj) == tier or (include_control_tools and name in _CONTROL_TOOLS)
    ]
    return [catalog[name] for name in allowed_names]


def get_root_tools(*, include_l2: bool = True) -> list[Any]:
    """Return the root-agent tool set from the registry source of truth.

    For now Root keeps soft isolation semantics: it always receives all control
    tools and all L1 tools, and can optionally see L2 tools.
    """
    catalog = _tool_catalog()
    allowed_names: list[str] = []
    for name, tool_obj in catalog.items():
        tier = get_tool_tier(tool_obj)
        if name in _CONTROL_TOOLS:
            allowed_names.append(name)
            continue
        if tier == "L1" or (include_l2 and tier == "L2"):
            allowed_names.append(name)
    return [catalog[name] for name in allowed_names]


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
    catalog = _tool_catalog()

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

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

from app.tools.metadata import CHEM_TIER_METADATA_KEY, ChemToolTier


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
    # Skills infrastructure (L3 reference reading + database API fetching)
    "tool_invoke_skill",
    "tool_read_skill_reference",
    "tool_fetch_chemistry_api",
    # File system: read-only
    "tool_read_file",
    # State management (safe, no I/O)
    "tool_update_scratchpad",
    "tool_create_molecule_node",
    "tool_update_viewport",
    # Diagnostics backfill (escape hatch for shell/sub-agent computed values)
    "tool_patch_diagnostics",
    # Molecule screening (reads injected tree, no I/O)
    "tool_screen_molecules",
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
    # Skills infrastructure
    "tool_invoke_skill",
    "tool_read_skill_reference",
    "tool_fetch_chemistry_api",
    # File system: full CRUD + shell
    "tool_read_file",
    "tool_write_file",
    "tool_edit_file",
    "tool_run_shell",
    # State management (safe, no I/O)
    "tool_update_scratchpad",
    "tool_create_molecule_node",
    "tool_update_viewport",
    # Diagnostics backfill + screening
    "tool_patch_diagnostics",
    # Molecule screening
    "tool_screen_molecules",
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
    # Skills infrastructure
    "tool_invoke_skill": "L1",
    "tool_read_skill_reference": "L1",
    "tool_fetch_chemistry_api": "L1",
    # File / shell tools
    "tool_read_file": "L1",
    "tool_write_file": "L2",
    "tool_edit_file": "L2",
    "tool_run_shell": "L2",
    # State management tools (pure state, no I/O)
    "tool_update_scratchpad": "L1",
    "tool_create_molecule_node": "L1",
    "tool_update_viewport": "L1",
    # Diagnostics backfill (escape hatch — pure state write, no I/O)
    "tool_patch_diagnostics": "L1",
    # Molecule screening (reads injected tree snapshot, no I/O)
    "tool_screen_molecules": "L1",
}


def _tool_catalog() -> dict[str, Any]:
    from app.tools.catalog import ALL_CHEM_TOOLS  # noqa: PLC0415

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


# ── New helpers (BaseChemTool contract support) ───────────────────────────────


def is_tool_read_only(tool_or_name: Any) -> bool:
    """Return True when a tool is declared as read-only via BaseChemTool.read_only
    or via the legacy ``chem_read_only`` metadata key.

    Checks ``tool.metadata["chem_read_only"]`` set by
    ``BaseChemTool._build_metadata()``.  Falls back to False (fail-closed).
    """
    if isinstance(tool_or_name, str):
        catalog = _tool_catalog()
        tool_obj = catalog.get(tool_or_name)
        if tool_obj is None:
            return False
    else:
        tool_obj = tool_or_name
    metadata = dict(getattr(tool_obj, "metadata", None) or {})
    return bool(metadata.get("chem_read_only", False))


def get_tool_prompt_injection(tool_or_name: Any, context: dict | None = None) -> str:
    """Return the per-tool JIT system prompt contribution.

    For ``BaseChemTool``-based tools, the underlying instance is stored on
    ``tool._chem_instance`` and its ``prompt()`` coroutine is called.
    Falls back gracefully to ``""`` for legacy ``@chem_tool`` tools.
    """
    import asyncio  # noqa: PLC0415

    if isinstance(tool_or_name, str):
        catalog = _tool_catalog()
        tool_obj = catalog.get(tool_or_name)
    else:
        tool_obj = tool_or_name
    if tool_obj is None:
        return ""
    instance = getattr(tool_obj, "_chem_instance", None)
    if instance is None:
        return ""
    try:
        coro = instance.prompt(context or {})
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context — caller should await directly.
                return ""
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)
    except Exception:  # noqa: BLE001
        return ""


def compile_tool_prompts(tools: list[Any], context: dict | None = None) -> str:
    """Concatenate non-empty prompt contributions from a tool set.

    Designed for use in sub-agent system prompt assembly::

        extra = compile_tool_prompts(allowed_tools, context)
        if extra:
            system_prompt += "\\n\\n" + extra
    """
    parts = [get_tool_prompt_injection(t, context) for t in tools]
    return "\n\n".join(p for p in parts if p.strip())


# ── Startup integrity assertion ───────────────────────────────────────────────


def assert_explore_tools_are_read_only() -> None:
    """Verify that every tool in _EXPLORE_TOOLS declares ``read_only=True``.

    Call once at application startup (e.g. in ``app/main.py``) to catch the
    class of bug where a mutating tool is accidentally added to the explore
    whitelist.  Raises ``AssertionError`` with the offending names.

    Tools not yet migrated to ``BaseChemTool`` (no ``chem_read_only`` key in
    metadata) are skipped with a warning so the migration can proceed
    incrementally without breaking startup.
    """
    import logging as _logging  # noqa: PLC0415

    _log = _logging.getLogger(__name__)
    catalog = _tool_catalog()
    violations: list[str] = []
    skipped: list[str] = []
    for name in _EXPLORE_TOOLS:
        tool_obj = catalog.get(name)
        if tool_obj is None:
            continue
        metadata = dict(getattr(tool_obj, "metadata", None) or {})
        if "chem_read_only" not in metadata:
            skipped.append(name)
            continue
        if not metadata["chem_read_only"]:
            violations.append(name)
    if skipped:
        _log.warning(
            "assert_explore_tools_are_read_only: %d tools not yet migrated to "
            "BaseChemTool and cannot be verified: %s",
            len(skipped),
            skipped,
        )
    assert not violations, (
        f"Explore-mode tools must declare read_only=True. Violations: {violations}"
    )

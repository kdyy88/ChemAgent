"""
LangGraph-compatible @tool wrappers over the deterministic rdkit_ops.py layer.

These tools are used by Worker nodes (Visualizer / Analyst / Researcher) inside
the LangGraph StateGraph.  Each wrapper adds a concise docstring (used by the
LLM as a tool description) and maps the dict-based return value to a Python
object that plays well with LangChain's tool protocol.

Shadow-Lab integration note
----------------------------
These tools never validate SMILES themselves — that is exclusively the
Shadow Lab node's responsibility.  Tools call rdkit_ops and return raw dicts;
the Shadow Lab intercepts the result SMILES and runs RDKit valence checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from tavily import TavilyClient

from app.agents.utils import strip_binary_fields
from app.tools.babel.prep import ALL_BABEL_TOOLS
from app.chem.rdkit_ops import (
    _mol_to_highlighted_png_b64,
    compute_descriptors,
    compute_similarity,
    mol_to_png_b64,
    murcko_scaffold,
    strip_salts_and_neutralize,
    substructure_match,
    validate_smiles,
)
from rdkit import Chem

logger = logging.getLogger(__name__)


# ── Helper: pretty-print dict results for LLM consumption ────────────────────

def _to_text(data: dict) -> str:
    """Convert a rdkit_ops result dict to a compact JSON string for the LLM."""
    # Remove bulky image/binary fields, including nested molecule previews.
    cleaned = strip_binary_fields(data)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


_SMILES_MAX_LEN = 10_000


def _check_smiles_input(smiles: str) -> str | None:
    """Return an error JSON string if the SMILES looks unsafe, else None."""
    if len(smiles) > _SMILES_MAX_LEN:
        return json.dumps({"is_valid": False, "error": f"SMILES 超出最大长度限制（{_SMILES_MAX_LEN} 字符）"})
    if any(c in smiles for c in ("\x00", "\n", "\r")):
        return json.dumps({"is_valid": False, "error": "SMILES 包含非法控制字符"})
    if smiles.count("(") - smiles.count(")") != 0:
        return json.dumps({"is_valid": False, "error": "SMILES 括号不匹配"})
    return None


def _input_missing_error() -> str:
    return json.dumps(
        {
            "is_valid": False,
            "error": "必须至少提供 `smiles` 或 `artifact_id` 之一。",
        },
        ensure_ascii=False,
    )


def _normalize_optional_text(value: str | None) -> str:
    return value.strip() if isinstance(value, str) else ""


async def _resolve_smiles_from_artifact(artifact_id: str, fallback_smiles: str) -> tuple[str, bool]:
    """Resolve canonical SMILES from an artifact record.

    Returns (smiles, from_artifact) where ``from_artifact`` is True when the
    artifact lookup succeeded.  Falls back to ``fallback_smiles`` on miss/error
    and logs a WARNING so the caller can audit the degraded path.
    """
    from app.core.artifact_store import get_engine_artifact  # noqa: PLC0415
    try:
        record = await get_engine_artifact(artifact_id)
        if record and isinstance(record, dict) and record.get("canonical_smiles"):
            logger.debug("Resolved SMILES from artifact %s", artifact_id)
            return record["canonical_smiles"], True
        logger.warning(
            "artifact_id=%s not found or has no canonical_smiles — falling back to raw SMILES input",
            artifact_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to resolve artifact %s: %s — falling back to raw SMILES input", artifact_id, exc)
    return fallback_smiles, False


# ── T1: Validate & Canonicalize SMILES ───────────────────────────────────────

@tool
def tool_validate_smiles(smiles: Annotated[str, "SMILES string to validate"]) -> str:
    """Validate a SMILES string and return its RDKit canonical form, formula,
    and atom/bond statistics.  Returns JSON with is_valid flag."""
    if err := _check_smiles_input(smiles):
        return err
    result = validate_smiles(smiles)
    return _to_text(result)


# ── T3: Comprehensive Molecular Descriptors ──────────────────────────────────

@tool
async def tool_evaluate_molecule(
    smiles: Annotated[str | None, "SMILES string of the molecule (optional when artifact_id is provided)"] = None,
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
    artifact_id: Annotated[str | None, "Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore"] = None,
) -> str:
    """Evaluate a molecule atomically via validate -> descriptors pipeline.

    This tool is the preferred entrypoint for new molecule assessment because it
    guarantees sequential execution and canonical SMILES handoff, avoiding race
    conditions between separate validate/descriptor calls.
    """
    raw_smiles = _normalize_optional_text(smiles)
    raw_artifact_id = _normalize_optional_text(artifact_id)
    if not raw_smiles and not raw_artifact_id:
        return _input_missing_error()

    input_smiles = raw_smiles
    from_artifact = False
    if raw_artifact_id:
        input_smiles, from_artifact = await _resolve_smiles_from_artifact(raw_artifact_id, raw_smiles)

    if err := _check_smiles_input(input_smiles):
        return err

    validation = validate_smiles(input_smiles)
    if not validation.get("is_valid"):
        return _to_text(
            {
                "type": "evaluation",
                "is_valid": False,
                "artifact_id": None,
                "parent_artifact_id": raw_artifact_id or None,
                "from_artifact": from_artifact,
                "validation": validation,
                "error": validation.get("error", "SMILES validation failed"),
            }
        )

    canonical = validation.get("canonical_smiles", input_smiles)
    descriptors = compute_descriptors(canonical, name)

    # Immutable lineage: every chemistry state transition gets a fresh artifact
    # id.  When derived from an existing artifact, preserve provenance via
    # parent_artifact_id instead of overwriting prior state.
    created_artifact_id = f"art_{uuid.uuid4().hex[:8]}"
    from app.core.artifact_store import store_engine_artifact  # noqa: PLC0415
    record = {
        "type": "molecule",
        "canonical_smiles": canonical,
        "formula": validation.get("formula") or descriptors.get("formula"),
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if raw_artifact_id:
        record["parent_artifact_id"] = raw_artifact_id
    await store_engine_artifact(created_artifact_id, record)

    return _to_text(
        {
            "type": "evaluation",
            "is_valid": bool(descriptors.get("is_valid", False)),
            "artifact_id": created_artifact_id,
            "parent_artifact_id": raw_artifact_id or None,
            "from_artifact": from_artifact,
            "validation": validation,
            "descriptors": descriptors.get("descriptors"),
            "lipinski": descriptors.get("lipinski"),
            "formula": descriptors.get("formula") or validation.get("formula"),
            "smiles": canonical,
            "name": name,
        }
    )


# ── T3: Comprehensive Molecular Descriptors ──────────────────────────────────

@tool
async def tool_compute_descriptors(
    smiles: Annotated[str | None, "SMILES string of the molecule (optional when artifact_id is provided)"] = None,
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
    artifact_id: Annotated[str | None, "Optional artifact pointer; when set, canonical_smiles is resolved from ArtifactStore"] = None,
) -> str:
    """Compute comprehensive molecular descriptors including Lipinski Rule-of-5
    (MW, LogP, HBD, HBA), TPSA, QED drug-likeness score, synthetic accessibility
    (SA Score), ring count, fraction sp3, and heavy atom count.

    Prefer ``tool_evaluate_molecule`` for new molecules (atomic validate->compute).
    This tool remains useful for incremental descriptor updates and supports
    artifact pointers to avoid SMILES copy drift.
    """
    raw_smiles = _normalize_optional_text(smiles)
    raw_artifact_id = _normalize_optional_text(artifact_id)
    if not raw_smiles and not raw_artifact_id:
        return _input_missing_error()

    resolved_smiles = raw_smiles
    if raw_artifact_id:
        resolved_smiles, _ = await _resolve_smiles_from_artifact(raw_artifact_id, raw_smiles)

    if err := _check_smiles_input(resolved_smiles):
        return err
    result = compute_descriptors(resolved_smiles, name)

    created_artifact_id = f"art_{uuid.uuid4().hex[:8]}"
    from app.core.artifact_store import store_engine_artifact  # noqa: PLC0415
    record = {
        "type": "molecule",
        "canonical_smiles": result.get("smiles") or resolved_smiles,
        "formula": result.get("formula"),
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if raw_artifact_id:
        record["parent_artifact_id"] = raw_artifact_id
        result["parent_artifact_id"] = raw_artifact_id
    await store_engine_artifact(created_artifact_id, record)
    result["artifact_id"] = created_artifact_id
    return _to_text(result)


# ── T4: Tanimoto Similarity ───────────────────────────────────────────────────

@tool
def tool_compute_similarity(
    smiles1: Annotated[str, "SMILES of the first molecule"],
    smiles2: Annotated[str, "SMILES of the second molecule"],
    radius: Annotated[int, "Morgan fingerprint radius (default 2 = ECFP4)"] = 2,
) -> str:
    """Compute Tanimoto similarity between two molecules using Morgan (ECFP4)
    fingerprints.  Returns a similarity score from 0.0 (dissimilar) to 1.0
    (identical) plus a human-readable interpretation.  Returns JSON."""
    for smi in (smiles1, smiles2):
        if err := _check_smiles_input(smi):
            return err
    result = compute_similarity(smiles1, smiles2, radius=radius)
    return _to_text(result)


# ── T5: Substructure Match + PAINS Screen ─────────────────────────────────────

@tool
def tool_substructure_match(
    smiles: Annotated[str, "SMILES of the target molecule"],
    smarts_pattern: Annotated[str, "SMARTS pattern to search for (e.g. functional group)"],
    compound_name: Annotated[str, "Human-readable name of the compound (e.g. 'Imatinib', '伊马替尼')"] = "",
    substructure_name: Annotated[str, "Human-readable name of the substructure being searched (e.g. 'Pyrimidine', '嘧啶')"] = "",
) -> str:
    """Check if a SMARTS substructure pattern matches a molecule, report match
    atom indices, and run PAINS (Pan Assay Interference) alerts screening.
    Returns JSON with matched, match_count, pains_alerts.

    IMPORTANT: This tool automatically generates and delivers a highlighted 2D
    structure image (with the matched atoms highlighted) to the user.
    Do NOT call tool_render_smiles afterward — it would produce a redundant
    second image.  Use compound_name and substructure_name so the image title
    is human-readable (e.g. compound_name='Imatinib', substructure_name='Pyrimidine').
    """
    if err := _check_smiles_input(smiles):
        return err
    result = substructure_match(smiles, smarts_pattern)
    # Attach display names so the postprocessor can build a descriptive title.
    if compound_name:
        result["compound_name"] = compound_name
    if substructure_name:
        result["substructure_name"] = substructure_name
    return _to_text(result)


# ── T6: Murcko Scaffold Extraction ───────────────────────────────────────────

@tool
def tool_murcko_scaffold(
    smiles: Annotated[str, "SMILES of the molecule to decompose"],
) -> str:
    """Extract the Bemis-Murcko scaffold and generic carbon scaffold from a
    molecule.  Useful for analysing core ring systems in a drug series.
    Returns JSON with scaffold_smiles and generic_scaffold_smiles."""
    if err := _check_smiles_input(smiles):
        return err
    result = murcko_scaffold(smiles)
    return _to_text(result)


# ── T9: Salt Stripping & Neutralization ───────────────────────────────────────

@tool
def tool_strip_salts(
    smiles: Annotated[str, "SMILES string possibly containing salt counterions"],
) -> str:
    """Strip salt fragments (e.g. HCl, Na+) from a molecule and neutralize
    formal charges.  Returns the largest parent fragment in canonical SMILES.
    Returns JSON with cleaned_smiles and removed_fragments."""
    if err := _check_smiles_input(smiles):
        return err
    result = strip_salts_and_neutralize(smiles)
    return _to_text(result)


# ── T7: 2D Structure Rendering (returns bare base64 PNG) ─────────────────────

@tool
def tool_render_smiles(
    smiles: Annotated[str, "Canonical SMILES to render as a 2D structure image"],
    highlight_atoms: Annotated[list[int], "Optional atom indices to highlight in the rendered image"] = [],
    compound_name: Annotated[str, "Human-readable compound name used as the image title (e.g. 'Aspirin', '阿司匹林')"] = "",
) -> str:
    """Render a 2D structure image for a SMILES string.  Returns a JSON object
    with a base64-encoded PNG (no data-URI prefix) in the 'image' field.

    If ``highlight_atoms`` is provided, those atom indices are highlighted in
    the rendered image.  This is useful for scaffold or substructure follow-up
    rendering after a previous matching step.

    Note: If you just ran tool_substructure_match, a highlighted image was
    already generated automatically — do NOT call this tool again unless you
    need a separate plain (non-highlighted) structure image.
    Always pass compound_name so the displayed title is human-readable.
    """
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        if err := _check_smiles_input(smiles):
            return err
        return json.dumps({"is_valid": False, "error": f"RDKit 无法解析 SMILES: {smiles}"})

    normalized_highlights = sorted({
        int(atom_idx)
        for atom_idx in highlight_atoms
        if isinstance(atom_idx, int) and 0 <= atom_idx < mol.GetNumAtoms()
    })

    if normalized_highlights:
        image_b64 = _mol_to_highlighted_png_b64(mol, normalized_highlights, size=(400, 400))
    else:
        image_b64 = mol_to_png_b64(mol, size=(400, 400))

    canonical = Chem.MolToSmiles(mol)
    result: dict[str, object] = {
        "is_valid": True,
        "smiles": canonical,
        "image": image_b64,
        "highlight_atoms": normalized_highlights,
    }
    if compound_name:
        result["compound_name"] = compound_name
    return json.dumps(result, ensure_ascii=False,
    )


# ── Exported catalog for graph.py ─────────────────────────────────────────────

# ── Rx. PubChem compound lookup ───────────────────────────────────────────────

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_SERPER_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_TAVILY_MAX_RESULTS = 8
_TAVILY_SEARCH_DEPTH = "advanced"


@tool
async def tool_pubchem_lookup(
    name: Annotated[str, "Drug or compound name (e.g. 'azithromycin', 'aspirin')"],
) -> str:
    """Look up a compound by name in PubChem.  Returns canonical SMILES,
    molecular formula, molecular weight, IUPAC name, and CID.
    Use this first when the user provides only a compound name and no SMILES."""
    try:
        async with httpx.AsyncClient(timeout=_PUBCHEM_TIMEOUT) as client:
            # Step 1: resolve name → CID
            cid_url = f"{_PUBCHEM_BASE}/compound/name/{quote(name)}/cids/JSON"
            r = await client.get(cid_url)
            r.raise_for_status()
            cid = r.json()["IdentifierList"]["CID"][0]

            # Step 2: fetch properties for the CID
            # PubChem returns IsomericSMILES as "SMILES" and CanonicalSMILES as
            # "ConnectivitySMILES" for many compounds — request both name variants.
            props = "IsomericSMILES,CanonicalSMILES,SMILES,MolecularFormula,MolecularWeight,IUPACName"
            prop_url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/{props}/JSON"
            p = await client.get(prop_url)
            p.raise_for_status()
            prop = p.json()["PropertyTable"]["Properties"][0]

        # Field names differ by compound type; fall back gracefully
        isomeric = (
            prop.get("IsomericSMILES")
            or prop.get("SMILES")          # PubChem sometimes uses bare "SMILES"
            or prop.get("CanonicalSMILES")
            or prop.get("ConnectivitySMILES")
            or ""
        )
        canonical = (
            prop.get("CanonicalSMILES")
            or prop.get("ConnectivitySMILES")  # connectivity = canonical topology
            or prop.get("SMILES")
            or isomeric
            or ""
        )

        return json.dumps({
            "found": True,
            "name": name,
            "cid": cid,
            "canonical_smiles": canonical,
            "isomeric_smiles": isomeric,
            "formula": prop.get("MolecularFormula", ""),
            "molecular_weight": prop.get("MolecularWeight", ""),
            "iupac_name": prop.get("IUPACName", ""),
            "pubchem_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"found": False, "name": name, "error": str(exc)})


# ── Rx. Web / literature search ───────────────────────────────────────────────

_SERPER_URL = "https://google.serper.dev/search"


async def _tool_web_search_serper(
    query: Annotated[str, "Search query (e.g. 'azithromycin clinical trials 2024')"],
) -> str:
    """Legacy Serper implementation kept for future fallback/revival."""
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return json.dumps({
            "status": "error",
            "error": "SERPER_API_KEY not set — web search unavailable.",
        })
    try:
        async with httpx.AsyncClient(timeout=_SERPER_TIMEOUT) as client:
            r = await client.post(
                _SERPER_URL,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 8},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc), "query": query})

    results = []
    if ab := data.get("answerBox"):
        text = ab.get("answer") or ab.get("snippet") or ""
        if text:
            results.append({"title": ab.get("title", "Direct Answer"), "url": ab.get("link", ""), "snippet": text})
    for item in data.get("organic", []):
        results.append({"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")})

    return json.dumps({"status": "success", "query": query, "results": results}, ensure_ascii=False)


@tool
async def tool_web_search(
    query: Annotated[str, "Search query (e.g. 'azithromycin clinical trials 2024')"],
) -> str:
    """Search the web and medical literature for recent drug approvals, clinical
    trial results, mechanism of action, safety data, and pharmacology news.
    Returns a list of results with titles, URLs, and snippets.
    Use this to find up-to-date information that may not be in training data."""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return json.dumps(
            {
                "status": "error",
                "error": "TAVILY_API_KEY not set — web search unavailable.",
            },
            ensure_ascii=False,
        )

    def _run_tavily_search() -> dict:
        client = TavilyClient(api_key=api_key)
        return client.search(
            query=query,
            search_depth=_TAVILY_SEARCH_DEPTH,
            max_results=_TAVILY_MAX_RESULTS,
        )

    try:
        data = await asyncio.to_thread(_run_tavily_search)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc), "query": query}, ensure_ascii=False)

    results = []
    answer = data.get("answer") or ""
    if answer:
        results.append(
            {
                "title": "Tavily Answer",
                "url": "",
                "snippet": answer,
            }
        )

    for item in data.get("results", []):
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "") or item.get("raw_content", "") or "",
            }
        )

    return json.dumps(
        {
            "status": "success",
            "query": query,
            "provider": "tavily",
            "results": results,
        },
        ensure_ascii=False,
    )


# ── Human-in-the-loop pause tool ─────────────────────────────────────────────


class AskHumanArgs(BaseModel):
    question: str = Field(
        ...,
        description=(
            "A single concise clarification question in Chinese. "
            "This is a terminal control action, not a data tool. "
            "If you call this tool, it must be the ONLY tool call in the current turn."
        ),
        min_length=4,
        max_length=160,
    )
    options: list[str] = Field(
        default_factory=list,
        description=(
            "Optional 2-4 short quick-reply choices in Chinese. "
            "Keep them mutually exclusive and user-facing. "
            "Do not include analysis text, explanations, or more than four choices."
        ),
        max_length=4,
    )


@tool(args_schema=AskHumanArgs)
def tool_ask_human(
    question: Annotated[str, "The clarifying question to ask the user, in Chinese"],
    options: Annotated[
        list[str],
        "2-4 quick-reply options for the user to choose from (optional, Chinese)",
    ] = [],
) -> str:
    """Terminal HITL control tool for requesting a user clarification.

    HARD RULES:
    1. This tool is not a chemistry data tool. It is a stop-and-wait control action.
    2. If you call this tool, it MUST be the only tool call in the current turn.
    3. After deciding to call this tool, stop immediately and do not call PubChem,
       web search, RDKit, Open Babel, or any other tool in the same turn.
    4. Ask exactly one concrete question. Do not bundle multiple questions.
    5. Only use this when progress is blocked by missing user input.

    WHEN TO USE — call this tool (and stop further tool calls in this turn) when:
    1. tool_pubchem_lookup returns found=false for the compound name, AND a backup
       English name also fails — ask the user for the correct name or a SMILES.
    2. The user's message is ambiguous (e.g. "帮我调研那个药" with no compound name).
    3. Multiple compounds share the same name and you cannot determine which one
       the user intends (e.g. "taxol" could refer to paclitaxel or docetaxel class).
    4. After two consecutive web searches return empty results — ask the user to
       confirm the compound spelling or provide an alternative name.

    DO NOT use this tool when you have sufficient information to proceed.
    After calling this tool, do NOT call any other tools — stop immediately."""
    return json.dumps(
        {
            "type": "clarification_requested",
            "question": question,
            "options": options,
        },
        ensure_ascii=False,
    )


@tool
def tool_update_task_status(
    task_id: Annotated[str, "Task id from the planner-generated task list"],
    status: Annotated[
        Literal["in_progress", "completed", "failed"],
        "New execution status for the task",
    ],
    summary: Annotated[
        str | None,
        "Optional one-sentence summary of the task outcome or blocking reason",
    ] = None,
) -> str:
    """Report task execution progress for planner-generated task lists.

    Call this tool before starting a planned task only when the task spans
    multiple rounds or needs explicit long-running UI feedback. For short tasks
    that will complete in the current work span, you may skip the initial
    ``in_progress`` update and report only the final ``completed``/``failed``
    status.
    When marking a task completed or failed, provide a short summary whenever
    there is a concrete stage result worth carrying forward. Only use task ids
    that already exist in the current plan.
    """
    return json.dumps(
        {
            "status": "success",
            "task_id": task_id,
            "task_status": status,
            "summary": summary,
        },
        ensure_ascii=False,
    )


ALL_RDKIT_TOOLS = [
    tool_validate_smiles,
    tool_evaluate_molecule,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_substructure_match,
    tool_murcko_scaffold,
    tool_strip_salts,
    tool_render_smiles,
    tool_pubchem_lookup,
    tool_web_search,
    tool_ask_human,
    tool_update_task_status,
]

# Lazy import to avoid circular dependency:
# lg_tools → tools/sub_agent → tool_registry → lg_tools
def _get_sub_agent_tool() -> list:
    from app.agents.tools.sub_agent import tool_run_sub_agent  # noqa: PLC0415
    return [tool_run_sub_agent]


ALL_CHEM_TOOLS = [
    *ALL_RDKIT_TOOLS,
    *ALL_BABEL_TOOLS,
    *_get_sub_agent_tool(),
]

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

import json
import os
from typing import Annotated

import requests
from langchain_core.tools import tool

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


# ── Helper: pretty-print dict results for LLM consumption ────────────────────

def _to_text(data: dict) -> str:
    """Convert a rdkit_ops result dict to a compact JSON string for the LLM."""
    # Remove bulky base64 image fields before handing to LLM text response
    cleaned = {k: v for k, v in data.items() if "image" not in k and "structure" not in k}
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


# ── T1: Validate & Canonicalize SMILES ───────────────────────────────────────

@tool
def tool_validate_smiles(smiles: Annotated[str, "SMILES string to validate"]) -> str:
    """Validate a SMILES string and return its RDKit canonical form, formula,
    and atom/bond statistics.  Returns JSON with is_valid flag."""
    result = validate_smiles(smiles)
    return _to_text(result)


# ── T3: Comprehensive Molecular Descriptors ──────────────────────────────────

@tool
def tool_compute_descriptors(
    smiles: Annotated[str, "SMILES string of the molecule"],
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
) -> str:
    """Compute comprehensive molecular descriptors including Lipinski Rule-of-5
    (MW, LogP, HBD, HBA), TPSA, QED drug-likeness score, synthetic accessibility
    (SA Score), ring count, fraction sp3, and heavy atom count.  Returns JSON."""
    result = compute_descriptors(smiles, name)
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
    result = compute_similarity(smiles1, smiles2, radius=radius)
    return _to_text(result)


# ── T5: Substructure Match + PAINS Screen ─────────────────────────────────────

@tool
def tool_substructure_match(
    smiles: Annotated[str, "SMILES of the target molecule"],
    smarts_pattern: Annotated[str, "SMARTS pattern to search for (e.g. functional group)"],
) -> str:
    """Check if a SMARTS substructure pattern matches a molecule, report match
    atom indices, and run PAINS (Pan Assay Interference) alerts screening.
    Returns JSON with matched, match_count, pains_alerts."""
    result = substructure_match(smiles, smarts_pattern)
    return _to_text(result)


# ── T6: Murcko Scaffold Extraction ───────────────────────────────────────────

@tool
def tool_murcko_scaffold(
    smiles: Annotated[str, "SMILES of the molecule to decompose"],
) -> str:
    """Extract the Bemis-Murcko scaffold and generic carbon scaffold from a
    molecule.  Useful for analysing core ring systems in a drug series.
    Returns JSON with scaffold_smiles and generic_scaffold_smiles."""
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
    result = strip_salts_and_neutralize(smiles)
    return _to_text(result)


# ── T7: 2D Structure Rendering (returns bare base64 PNG) ─────────────────────

@tool
def tool_render_smiles(
    smiles: Annotated[str, "Canonical SMILES to render as a 2D structure image"],
    highlight_atoms: Annotated[list[int], "Optional atom indices to highlight in the rendered image"] = [],
) -> str:
    """Render a 2D structure image for a SMILES string.  Returns a JSON object
    with a base64-encoded PNG (no data-URI prefix) in the 'image' field.

    If ``highlight_atoms`` is provided, those atom indices are highlighted in
    the rendered image.  This is useful for scaffold or substructure follow-up
    rendering after a previous matching step.
    """
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
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
    return json.dumps(
        {
            "is_valid": True,
            "smiles": canonical,
            "image": image_b64,
            "highlight_atoms": normalized_highlights,
        },
        ensure_ascii=False,
    )


# ── Exported catalog for graph.py ─────────────────────────────────────────────

# ── Rx. PubChem compound lookup ───────────────────────────────────────────────

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


@tool
def tool_pubchem_lookup(
    name: Annotated[str, "Drug or compound name (e.g. 'azithromycin', 'aspirin')"],
) -> str:
    """Look up a compound by name in PubChem.  Returns canonical SMILES,
    molecular formula, molecular weight, IUPAC name, and CID.
    Use this first when the user provides only a compound name and no SMILES."""
    try:
        # Step 1: resolve name → CID
        cid_url = f"{_PUBCHEM_BASE}/compound/name/{requests.utils.quote(name)}/cids/JSON"
        r = requests.get(cid_url, timeout=10)
        r.raise_for_status()
        cid = r.json()["IdentifierList"]["CID"][0]

        # Step 2: fetch properties for the CID
        # PubChem returns IsomericSMILES as "SMILES" and CanonicalSMILES as
        # "ConnectivitySMILES" for many compounds — request both name variants.
        props = "IsomericSMILES,CanonicalSMILES,SMILES,MolecularFormula,MolecularWeight,IUPACName"
        prop_url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/{props}/JSON"
        p = requests.get(prop_url, timeout=10)
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


@tool
def tool_web_search(
    query: Annotated[str, "Search query (e.g. 'azithromycin clinical trials 2024')"],
) -> str:
    """Search the web and medical literature for recent drug approvals, clinical
    trial results, mechanism of action, safety data, and pharmacology news.
    Returns a list of results with titles, URLs, and snippets.
    Use this to find up-to-date information that may not be in training data."""
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return json.dumps({
            "status": "error",
            "error": "SERPER_API_KEY not set — web search unavailable.",
        })
    try:
        r = requests.post(
            _SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
            timeout=15,
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


# ── Human-in-the-loop pause tool ─────────────────────────────────────────────


@tool
def tool_ask_human(
    question: Annotated[str, "The clarifying question to ask the user, in Chinese"],
    options: Annotated[
        list[str],
        "2-4 quick-reply options for the user to choose from (optional, Chinese)",
    ] = [],
) -> str:
    """Pause research and ask the user a clarifying question when you are uncertain.

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


ALL_RDKIT_TOOLS = [
    tool_validate_smiles,
    tool_compute_descriptors,
    tool_compute_similarity,
    tool_substructure_match,
    tool_murcko_scaffold,
    tool_strip_salts,
    tool_render_smiles,
    tool_pubchem_lookup,
    tool_web_search,
    tool_ask_human,
]

ALL_CHEM_TOOLS = [
    *ALL_RDKIT_TOOLS,
    *ALL_BABEL_TOOLS,
]

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
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.babel.prep import ALL_BABEL_TOOLS
from app.services.chem_engine.rdkit_ops import (
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
def tool_compute_descriptors(
    smiles: Annotated[str, "SMILES string of the molecule"],
    name: Annotated[str, "Common or IUPAC name of the compound (optional)"] = "",
) -> str:
    """Compute comprehensive molecular descriptors including Lipinski Rule-of-5
    (MW, LogP, HBD, HBA), TPSA, QED drug-likeness score, synthetic accessibility
    (SA Score), ring count, fraction sp3, and heavy atom count.  Returns JSON."""
    if err := _check_smiles_input(smiles):
        return err
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


@tool
async def tool_web_search(
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




# ── Exported tool catalogs ────────────────────────────────────────────────────

from app.tools.babel.prep import ALL_BABEL_TOOLS
from app.tools.system.task_status import tool_ask_human, tool_update_task_status

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
    tool_update_task_status,
]

ALL_CHEM_TOOLS = [
    *ALL_RDKIT_TOOLS,
    *ALL_BABEL_TOOLS,
]

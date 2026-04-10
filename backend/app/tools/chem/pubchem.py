"""PubChem compound lookup tool."""

from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import quote

import httpx

from app.tools.decorators import chem_tool

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# ── Rx. PubChem compound lookup ───────────────────────────────────────────────

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_SERPER_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_TAVILY_MAX_RESULTS = 8
_TAVILY_SEARCH_DEPTH = "advanced"


@chem_tool(tier="L1")
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

from __future__ import annotations

import asyncio
import json
import os
from typing import Annotated
from urllib.parse import quote

import httpx
from tavily import TavilyClient

from app.tools.decorators import chem_tool

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_SERPER_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SERPER_URL = "https://google.serper.dev/search"
_TAVILY_MAX_RESULTS = 8
_TAVILY_SEARCH_DEPTH = "advanced"


@chem_tool(tier="L1")
async def tool_pubchem_lookup(
    name: Annotated[str, "Drug or compound name (e.g. 'azithromycin', 'aspirin')"],
) -> str:
    """Look up a compound by name in PubChem and return compact JSON metadata."""
    try:
        async with httpx.AsyncClient(timeout=_PUBCHEM_TIMEOUT) as client:
            cid_url = f"{_PUBCHEM_BASE}/compound/name/{quote(name)}/cids/JSON"
            response = await client.get(cid_url)
            response.raise_for_status()
            cid = response.json()["IdentifierList"]["CID"][0]

            props = "IsomericSMILES,CanonicalSMILES,SMILES,MolecularFormula,MolecularWeight,IUPACName"
            prop_url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/{props}/JSON"
            prop_response = await client.get(prop_url)
            prop_response.raise_for_status()
            prop = prop_response.json()["PropertyTable"]["Properties"][0]

        isomeric = (
            prop.get("IsomericSMILES")
            or prop.get("SMILES")
            or prop.get("CanonicalSMILES")
            or prop.get("ConnectivitySMILES")
            or ""
        )
        canonical = (
            prop.get("CanonicalSMILES")
            or prop.get("ConnectivitySMILES")
            or prop.get("SMILES")
            or isomeric
            or ""
        )

        return json.dumps(
            {
                "found": True,
                "name": name,
                "cid": cid,
                "canonical_smiles": canonical,
                "isomeric_smiles": isomeric,
                "formula": prop.get("MolecularFormula", ""),
                "molecular_weight": prop.get("MolecularWeight", ""),
                "iupac_name": prop.get("IUPACName", ""),
                "pubchem_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"found": False, "name": name, "error": str(exc)})


async def _tool_web_search_serper(
    query: Annotated[str, "Search query (e.g. 'azithromycin clinical trials 2024')"],
) -> str:
    """Legacy Serper implementation kept for future fallback/revival."""
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return json.dumps({"status": "error", "error": "SERPER_API_KEY not set — web search unavailable."})
    try:
        async with httpx.AsyncClient(timeout=_SERPER_TIMEOUT) as client:
            response = await client.post(
                _SERPER_URL,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 8},
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "error": str(exc), "query": query})

    results = []
    if answer_box := data.get("answerBox"):
        text = answer_box.get("answer") or answer_box.get("snippet") or ""
        if text:
            results.append({"title": answer_box.get("title", "Direct Answer"), "url": answer_box.get("link", ""), "snippet": text})
    for item in data.get("organic", []):
        results.append({"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")})

    return json.dumps({"status": "success", "query": query, "results": results}, ensure_ascii=False)


@chem_tool(tier="L1")
async def tool_web_search(
    query: Annotated[str, "Search query (e.g. 'azithromycin clinical trials 2024')"],
) -> str:
    """Search the web and literature using Tavily and return compact JSON results."""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return json.dumps({"status": "error", "error": "TAVILY_API_KEY not set — web search unavailable."}, ensure_ascii=False)

    def _run_tavily_search() -> dict:
        client = TavilyClient(api_key=api_key)
        return client.search(query=query, search_depth=_TAVILY_SEARCH_DEPTH, max_results=_TAVILY_MAX_RESULTS)

    try:
        data = await asyncio.to_thread(_run_tavily_search)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "error": str(exc), "query": query}, ensure_ascii=False)

    results = []
    answer = data.get("answer") or ""
    if answer:
        results.append({"title": "Tavily Answer", "url": "", "snippet": answer})

    for item in data.get("results", []):
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "") or item.get("raw_content", "") or "",
            }
        )

    return json.dumps({"status": "success", "query": query, "provider": "tavily", "results": results}, ensure_ascii=False)


ALL_PUBCHEM_TOOLS = [tool_pubchem_lookup, tool_web_search]
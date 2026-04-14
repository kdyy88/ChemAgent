"""PubChem and web-search tool implementations -- class-based BaseChemTool contract."""

from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field
from tavily import TavilyClient

from app.domain.schemas.workflow import ValidationResult
from app.tools.base import ChemLookupTool

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_TAVILY_MAX_RESULTS = 8
_TAVILY_SEARCH_DEPTH = "advanced"


# ── 1. tool_pubchem_lookup ────────────────────────────────────────────────────


class PubchemLookupInput(BaseModel):
    name: str = Field(
        description="Drug or compound name (e.g. 'azithromycin', 'aspirin')"
    )


class ToolPubchemLookup(ChemLookupTool[PubchemLookupInput, str]):
    """Look up a compound by name in PubChem and return compact JSON metadata."""

    name = "tool_pubchem_lookup"
    args_schema = PubchemLookupInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 4_000

    async def validate_input(
        self, args: PubchemLookupInput, context: dict
    ) -> ValidationResult:
        if not args.name.strip():
            return ValidationResult(result=False, message="name 不能为空")
        return ValidationResult(result=True)

    async def call(self, args: PubchemLookupInput) -> str:
        """Search PubChem by compound name and return SMILES, formula, weight and metadata."""
        try:
            async with httpx.AsyncClient(timeout=_PUBCHEM_TIMEOUT) as client:
                cid_url = f"{_PUBCHEM_BASE}/compound/name/{quote(args.name)}/cids/JSON"
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
                    "name": args.name,
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
            return json.dumps({"found": False, "name": args.name, "error": str(exc)})


tool_pubchem_lookup = ToolPubchemLookup().as_langchain_tool()


# ── 2. tool_web_search ────────────────────────────────────────────────────────


class WebSearchInput(BaseModel):
    query: str = Field(
        description="Search query (e.g. 'azithromycin clinical trials 2024')"
    )


class ToolWebSearch(ChemLookupTool[WebSearchInput, str]):
    """Search the web and literature using Tavily and return compact JSON results."""

    name = "tool_web_search"
    args_schema = WebSearchInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    max_result_size_chars = 8_000

    async def validate_input(
        self, args: WebSearchInput, context: dict
    ) -> ValidationResult:
        if not args.query.strip():
            return ValidationResult(result=False, message="query 不能为空")
        return ValidationResult(result=True)

    async def call(self, args: WebSearchInput) -> str:
        """Search the web using Tavily and return a summarised answer with source URLs."""
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            return json.dumps(
                {"status": "error", "error": "TAVILY_API_KEY not set -- web search unavailable."},
                ensure_ascii=False,
            )

        def _run_tavily() -> dict:
            client = TavilyClient(api_key=api_key)
            return client.search(
                query=args.query,
                search_depth=_TAVILY_SEARCH_DEPTH,
                max_results=_TAVILY_MAX_RESULTS,
            )

        try:
            data = await asyncio.to_thread(_run_tavily)
        except Exception as exc:  # noqa: BLE001
            return json.dumps(
                {"status": "error", "error": str(exc), "query": args.query},
                ensure_ascii=False,
            )

        results = []
        if answer := data.get("answer"):
            results.append({"title": "Tavily Answer", "url": "", "snippet": answer})
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "") or item.get("raw_content", "") or "",
                }
            )
        return json.dumps(
            {"status": "success", "query": args.query, "provider": "tavily", "results": results},
            ensure_ascii=False,
        )


tool_web_search = ToolWebSearch().as_langchain_tool()


ALL_PUBCHEM_TOOLS = [
    tool_pubchem_lookup,
    tool_web_search,
]

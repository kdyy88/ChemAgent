"""Web and literature search tool (Tavily + Serper fallback)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Annotated

import httpx
from tavily import TavilyClient

from app.tools.decorators import chem_tool

_SERPER_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_TAVILY_MAX_RESULTS = 8
_TAVILY_SEARCH_DEPTH = "advanced"
_SERPER_URL = "https://google.serper.dev/search"

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


@chem_tool(tier="L1")
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

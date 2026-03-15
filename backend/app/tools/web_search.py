# backend/app/tools/web_search.py
"""
Web-search tool powered by Serper (https://serper.dev).

Requires SERPER_API_KEY in backend/.env.
Falls back to an error result (rather than silently returning stale mock data)
so the Researcher agent knows the search didn't succeed and can tell the user.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from app.core.tooling import ToolExecutionResult, tool_registry

_SERPER_URL = "https://google.serper.dev/search"
_TIMEOUT_SECONDS = 15
_ENV_LOADED = False


def _ensure_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_file = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(dotenv_path=env_file, override=False)
    _ENV_LOADED = True


@tool_registry.register(
    name="web_search",
    description=(
        "Search the web and medical literature for recent drug approvals, clinical trial results, "
        "molecular discovery news, and other chemistry or pharmacology information. "
        "Returns a list of relevant results with titles, URLs, and snippets."
    ),
    display_name="Web / Literature Search",
    category="retrieval",
    output_kinds=("json",),
    tags=("search", "web", "literature", "drugs", "news"),
    reflection_hint=(
        "If results are insufficient, try rephrasing the query with more specific terms "
        "such as drug class, target, disease indication, or year range."
    ),
)
def web_search(query: str) -> ToolExecutionResult:
    """
    Search the web for chemistry and pharmacology information via Serper.dev.

    Args:
        query: The search query string (e.g. 'FDA approved lung cancer drugs 2024').
    """
    _ensure_env()
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return ToolExecutionResult(
            status="error",
            summary="SERPER_API_KEY is not set. Add it to backend/.env to enable web search.",
            data={"query": query},
            artifacts=[],
        )

    try:
        response = requests.post(
            _SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return ToolExecutionResult(
            status="error",
            summary=f"Web search timed out after {_TIMEOUT_SECONDS}s for query: {query}",
            data={"query": query},
            artifacts=[],
        )
    except requests.exceptions.RequestException as exc:
        return ToolExecutionResult(
            status="error",
            summary=f"Web search request failed: {exc}",
            data={"query": query},
            artifacts=[],
        )

    # Normalise Serper response into a flat list of result dicts
    results: list[dict] = []

    for item in data.get("organic", []):
        results.append({
            "title":   item.get("title", ""),
            "url":     item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })

    # Include the "answerBox" if Serper returned a direct answer
    if answer_box := data.get("answerBox"):
        answer_text = (
            answer_box.get("answer")
            or answer_box.get("snippet")
            or answer_box.get("snippetHighlighted", "")
        )
        if answer_text:
            results.insert(0, {
                "title":   answer_box.get("title", "Direct Answer"),
                "url":     answer_box.get("link", ""),
                "snippet": answer_text,
            })

    summary = f"Found {len(results)} result(s) for query '{query}'."

    return ToolExecutionResult(
        status="success",
        summary=summary,
        data={"query": query, "results": results},
        artifacts=[],
    )

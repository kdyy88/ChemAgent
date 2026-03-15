# backend/app/tools/web_search.py
"""
Stub web-search tool for the Researcher specialist.

# TODO: Replace mock implementation with a real provider, e.g.:
#   - Tavily: pip install tavily-python, set TAVILY_API_KEY in .env
#   - SerpAPI: pip install google-search-results, set SERPAPI_API_KEY in .env
#
# Example Tavily swap (drop-in replacement for the body below):
#   from tavily import TavilyClient
#   client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
#   results = client.search(query=query, max_results=5)
#   items = [{"title": r["title"], "url": r["url"], "snippet": r["content"]} for r in results["results"]]
"""

from app.core.tooling import ToolExecutionResult, tool_registry

_MOCK_DRUG_NEWS = [
    {
        "title": "FDA approves Amivantamab-vmjw (Rybrevant) for NSCLC with EGFR Exon 20 insertions",
        "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-amivantamab-vmjw-non-small-cell-lung-cancer",
        "snippet": "The FDA approved amivantamab-vmjw (Rybrevant, Janssen Biotech) for adult patients with locally advanced or metastatic NSCLC with EGFR exon 20 insertion mutations.",
        "drug_name": "Amivantamab",
        "indication": "Non-small cell lung cancer (NSCLC) with EGFR Exon 20 insertions",
        "approval_year": 2021,
    },
    {
        "title": "FDA approves Adagrasib (Krazati) for KRAS G12C-mutated NSCLC",
        "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-adagrasib-kras-g12c-mutated-nsclc",
        "snippet": "Adagrasib (Krazati) received FDA approval for adult patients with KRAS G12C-mutated locally advanced or metastatic NSCLC, as determined by an FDA-approved test.",
        "drug_name": "Adagrasib",
        "indication": "NSCLC with KRAS G12C mutation",
        "approval_year": 2022,
    },
    {
        "title": "FDA approves Sotorasib (Lumakras) for adult patients with KRAS G12C-mutated NSCLC",
        "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-sotorasib-kras-g12c-mutated-nsclc",
        "snippet": "Sotorasib (Lumakras, Amgen) is a first-in-class KRAS inhibitor approved for KRAS G12C-mutated NSCLC treatment.",
        "drug_name": "Sotorasib",
        "indication": "NSCLC with KRAS G12C mutation",
        "approval_year": 2021,
    },
]


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
    Search the web for chemistry and pharmacology information.

    Args:
        query: The search query string (e.g. 'FDA approved lung cancer drugs 2024').
    """
    # ── STUB ─────────────────────────────────────────────────────────────────
    # Always returns mock FDA drug-approval news regardless of query.
    # Replace this section with a real API call when an API key is available.
    # ─────────────────────────────────────────────────────────────────────────
    results = _MOCK_DRUG_NEWS

    summary_lines = [f"- {r['drug_name']}: {r['indication']} (approved {r['approval_year']})" for r in results]
    summary = (
        f"[STUB] Found {len(results)} result(s) for query '{query}':\n"
        + "\n".join(summary_lines)
    )

    return ToolExecutionResult(
        status="success",
        summary=summary,
        data={
            "query": query,
            "results": results,
            "source": "stub_mock",
            "note": "This is mock data. Replace web_search() with a real provider for production use.",
        },
        artifacts=[],
    )

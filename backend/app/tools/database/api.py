"""tool_fetch_chemistry_api — Whitelisted HTTP GET for chemistry databases
=========================================================================

Provides the main agent with authenticated, safe read access to a curated
list of public chemistry and biomedical REST APIs.

Security hardening (排雷5)
--------------------------
1. **HTTPS-only**: the URL scheme is verified to be ``https`` before any
   network call.  ``http://`` and other schemes are rejected.
2. **Hostname whitelist**: the resolved hostname must be in
   ``ALLOWED_CHEMISTRY_HOSTS``.  IP literals and private-range hostnames are
   implicitly excluded.
3. **follow_redirects=False**: prevents SSRF via 301/302 redirect chains that
   could point to internal cluster addresses or ``127.0.0.1``.
4. **Strict timeout**: 30 s wall-clock hard limit via httpx.

Usage
-----
The agent should:
1. Call ``tool_invoke_skill("database-lookup", {...})`` to receive the SOP.
2. Call ``tool_read_skill_reference("database-lookup", "<db>")`` to get the
   specific API endpoint documentation for the target database.
3. Construct the URL according to the reference docs and call this tool.
"""

from __future__ import annotations

import json
import logging
import urllib.parse

import httpx

from app.tools.decorators import chem_tool

logger = logging.getLogger(__name__)

# ── Hostname whitelist ────────────────────────────────────────────────────────

ALLOWED_CHEMISTRY_HOSTS: frozenset[str] = frozenset({
    # PubChem / NCBI
    "pubchem.ncbi.nlm.nih.gov",
    "eutils.ncbi.nlm.nih.gov",
    # EBI umbrella (ChEMBL, ChEBI, UniProt mirrored, AlphaFold)
    "www.ebi.ac.uk",
    "ebi.ac.uk",
    "alphafold.ebi.ac.uk",
    # UniProt
    "www.uniprot.org",
    "rest.uniprot.org",
    # PDB / RCSB
    "data.rcsb.org",
    "www.rcsb.org",
    # KEGG
    "rest.kegg.jp",
    # ZINC
    "zinc.docking.org",
    # BindingDB
    "www.bindingdb.org",
    # STRING
    "string-db.org",
    # FDA / OpenFDA
    "api.fda.gov",
    # DailyMed (NIH/NLM)
    "dailymed.nlm.nih.gov",
    # Reactome
    "reactome.org",
    "www.reactome.org",
    # ClinicalTrials.gov
    "clinicaltrials.gov",
    "www.clinicaltrials.gov",
})


@chem_tool(tier="L1", timeout=30)
def tool_fetch_chemistry_api(url: str, params: str = "{}") -> str:
    """Make an HTTPS GET request to a whitelisted chemistry/biomedical database API.

    Always call ``tool_read_skill_reference`` first to get the correct URL
    format and parameter names for the target database before calling this tool.

    Parameters
    ----------
    url:
        Full HTTPS URL to the API endpoint.
        Example: ``"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/property/MolecularFormula,MolecularWeight,IUPACName/JSON"``
    params:
        Optional JSON string of query parameters to append to the URL.
        Example: ``{"MaxRecords": "10"}``
        Pass ``"{}"`` (default) when all parameters are already in the URL.
    """
    # ── Parse and validate params ──────────────────────────────────────────────
    try:
        parsed_params: dict = json.loads(params) if params.strip() else {}
    except json.JSONDecodeError as exc:
        return json.dumps(
            {"status": "error", "error": f"Invalid JSON in params: {exc}"},
            ensure_ascii=False,
        )

    # ── Parse URL ─────────────────────────────────────────────────────────────
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"status": "error", "error": f"Cannot parse URL: {exc}"},
            ensure_ascii=False,
        )

    # ── Enforce HTTPS (雷5: prevent plaintext + SSRF downgrade) ──────────────
    if parsed.scheme != "https":
        return json.dumps(
            {
                "status": "error",
                "error": "Only HTTPS URLs are permitted. Please use https://.",
                "supplied_scheme": parsed.scheme,
            },
            ensure_ascii=False,
        )

    # ── Hostname whitelist check ──────────────────────────────────────────────
    hostname = (parsed.hostname or "").lower().strip()
    if not hostname or hostname not in ALLOWED_CHEMISTRY_HOSTS:
        return json.dumps(
            {
                "status": "error",
                "error": f"Host not in allowed list: {hostname!r}",
                "allowed_hosts": sorted(ALLOWED_CHEMISTRY_HOSTS),
            },
            ensure_ascii=False,
        )

    # ── HTTP request (雷5: follow_redirects=False) ────────────────────────────
    try:
        response = httpx.get(
            url,
            params=parsed_params or None,
            timeout=30.0,
            follow_redirects=False,
            headers={"Accept": "application/json, text/plain, */*"},
        )
    except httpx.TimeoutException:
        return json.dumps(
            {"status": "error", "error": f"Request timed out after 30 s: {url}"},
            ensure_ascii=False,
        )
    except httpx.RequestError as exc:
        return json.dumps(
            {"status": "error", "error": f"Network error: {exc}", "url": url},
            ensure_ascii=False,
        )

    # ── Handle redirects (returned as errors, not followed) ───────────────────
    if response.is_redirect:
        return json.dumps(
            {
                "status": "error",
                "error": "Server returned a redirect. Not followed (SSRF prevention).",
                "http_status": response.status_code,
                "location": response.headers.get("location", ""),
            },
            ensure_ascii=False,
        )

    # ── HTTP error statuses ────────────────────────────────────────────────────
    if not response.is_success:
        return json.dumps(
            {
                "status": "error",
                "http_status": response.status_code,
                "url": url,
                "body_preview": response.text[:400],
            },
            ensure_ascii=False,
        )

    return response.text

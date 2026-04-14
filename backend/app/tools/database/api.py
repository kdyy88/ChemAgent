"""tool_fetch_chemistry_api -- class-based BaseChemTool contract.

Security hardening (OWASP SSRF prevention)
-------------------------------------------
1. HTTPS-only: scheme verified before any network call.
2. Hostname whitelist: resolved hostname must be in ALLOWED_CHEMISTRY_HOSTS.
3. follow_redirects=False: prevents SSRF via redirect chains.
4. Strict 30 s timeout.

Layering:
- validate_input()  -- checks URL parseability and params JSON validity.
- check_permissions() -- enforces HTTPS-only + hostname whitelist (SSRF gate).
- call() -- executes the safe GET request.
"""

from __future__ import annotations

import json
import logging
import urllib.parse

import httpx
from pydantic import BaseModel, Field

from app.domain.schemas.workflow import PermissionResult, ValidationResult
from app.tools.base import ChemComputeTool

logger = logging.getLogger(__name__)

# ── Hostname whitelist ────────────────────────────────────────────────────────

ALLOWED_CHEMISTRY_HOSTS: frozenset[str] = frozenset({
    "pubchem.ncbi.nlm.nih.gov",
    "eutils.ncbi.nlm.nih.gov",
    "www.ebi.ac.uk",
    "ebi.ac.uk",
    "alphafold.ebi.ac.uk",
    "www.uniprot.org",
    "rest.uniprot.org",
    "data.rcsb.org",
    "www.rcsb.org",
    "rest.kegg.jp",
    "zinc.docking.org",
    "www.bindingdb.org",
    "string-db.org",
    "api.fda.gov",
    "dailymed.nlm.nih.gov",
    "reactome.org",
    "www.reactome.org",
    "clinicaltrials.gov",
    "www.clinicaltrials.gov",
})


class FetchChemistryApiInput(BaseModel):
    url: str = Field(
        description=(
            "Full HTTPS URL to the API endpoint. "
            "Example: \"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/"
            "property/MolecularFormula,MolecularWeight,IUPACName/JSON\""
        )
    )
    params: str = Field(
        default="{}",
        description=(
            "Optional JSON string of query parameters to append to the URL. "
            "Example: '{\"MaxRecords\": \"10\"}'. Pass '{}' when all parameters are in the URL."
        ),
    )


class ToolFetchChemistryApi(ChemComputeTool[FetchChemistryApiInput, str]):
    """Make an HTTPS GET request to a whitelisted chemistry/biomedical database API.

    Always call ``tool_read_skill_reference`` first to get the correct URL
    format and parameter names for the target database before calling this tool.
    """

    name = "tool_fetch_chemistry_api"
    args_schema = FetchChemistryApiInput
    tier = "L1"
    read_only = True
    is_concurrency_safe = True
    timeout = 30.0
    max_result_size_chars = 32_000

    async def validate_input(
        self, args: FetchChemistryApiInput, context: dict
    ) -> ValidationResult:
        # Validate params JSON
        try:
            if args.params.strip():
                json.loads(args.params)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                result=False,
                message=f"Invalid JSON in params: {exc}",
            )
        # Validate URL is parseable
        try:
            urllib.parse.urlparse(args.url)
        except Exception as exc:  # noqa: BLE001
            return ValidationResult(
                result=False,
                message=f"Cannot parse URL: {exc}",
            )
        return ValidationResult(result=True)

    async def check_permissions(
        self, args: FetchChemistryApiInput, context: dict
    ) -> PermissionResult:
        try:
            parsed = urllib.parse.urlparse(args.url)
        except Exception:  # noqa: BLE001
            return PermissionResult(granted=False, reason="URL parse failed during permission check")

        if parsed.scheme != "https":
            return PermissionResult(
                granted=False,
                reason=f"Only HTTPS URLs are permitted. Supplied scheme: {parsed.scheme!r}",
            )

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname or hostname not in ALLOWED_CHEMISTRY_HOSTS:
            return PermissionResult(
                granted=False,
                reason=f"Host not in allowed list: {hostname!r}",
            )
        return PermissionResult(granted=True)

    def call(self, args: FetchChemistryApiInput) -> str:
        """Fetch data from a chemistry or biomedical REST API endpoint and return JSON results."""
        parsed_params: dict = json.loads(args.params) if args.params.strip() else {}
        try:
            response = httpx.get(
                args.url,
                params=parsed_params or None,
                timeout=30.0,
                follow_redirects=False,
                headers={"Accept": "application/json, text/plain, */*"},
            )
        except httpx.TimeoutException:
            return json.dumps(
                {"status": "error", "error": f"Request timed out after 30 s: {args.url}"},
                ensure_ascii=False,
            )
        except httpx.RequestError as exc:
            return json.dumps(
                {"status": "error", "error": f"Network error: {exc}", "url": args.url},
                ensure_ascii=False,
            )

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

        if not response.is_success:
            return json.dumps(
                {
                    "status": "error",
                    "http_status": response.status_code,
                    "url": args.url,
                    "body_preview": response.text[:400],
                },
                ensure_ascii=False,
            )

        return response.text


tool_fetch_chemistry_api = ToolFetchChemistryApi().as_langchain_tool()

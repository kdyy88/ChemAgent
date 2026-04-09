---
name: database-lookup
description: Search public scientific, biomedical databases via their REST APIs and return structured JSON results. Also trigger when the user mentions any database by name or asks about molecular properties, drug-target interactions, binding affinities, protein interactions, pathway membership, pharmacogenomics, economic time series, materials properties, commercially available compounds, virtual screening, compound purchasability, chemical libraries, building blocks, cancer genomics, somatic mutations, tumor mutation profiles, nucleotide sequences, genome assemblies, sequencing reads, ENA accessions, INSDC data, or wants to cross-reference entities across sources.
metadata:
  skill-author: Ye.
---

# Database Lookup

You have access to PubChem public databases through their REST APIs. Your job is to query them, and return the raw JSON results along with which databases you used.

## Core Workflow

1. **Read the reference file** — Each database has a reference file in `references/` with endpoint details, query formats, and example calls. Read the relevant file(s) before making API calls.

2. **Make the API call(s)** — See the **Making API Calls** section below for which HTTP fetch tool to use on your platform.

3. **Return results** — Always return:
   - The **raw JSON** response from each database
   - A **list of databases queried** with the specific endpoints used
   - If a query returned no results, say so explicitly rather than omitting it

## Database Selection Guide

Match the user's intent to the right database(s). Many queries benefit from hitting multiple databases.

### Chemistry & Drugs
| User is asking about... | Primary database(s) | Also consider |
|---|---|---|
| Chemical compounds, molecules | PubChem | ChEMBL |
| Molecular properties (weight, formula, SMILES) | PubChem | — |
| Drug synonyms, CAS numbers | PubChem (synonyms) | DrugBank |
| Bioactivity data, IC50, binding assays | ChEMBL | BindingDB, PubChem |
| Drug binding affinities (Ki, IC50, Kd) | ChEMBL, BindingDB | PubChem |
| Drug-target interactions | ChEMBL, DrugBank | BindingDB, Open Targets |
| Ligands for a protein target (by UniProt) | BindingDB | ChEMBL |
| Target identification from compound structure | BindingDB (SMILES similarity) | ChEMBL |
| Drug labels, adverse events, recalls | FDA (OpenFDA) | DailyMed |
| Drug labels (structured product labels) | DailyMed | FDA (OpenFDA) |
| Drug pharmacology, indications | DrugBank | FDA |
| Chemical cross-referencing | PubChem (xrefs) | ChEMBL |
| Commercially available compounds for screening | ZINC | PubChem |
| Similarity/substructure search (purchasable) | ZINC | PubChem, ChEMBL |
| Drug-like compound libraries, building blocks | ZINC | — |
| FDA-approved drug structures | ZINC (fda subset) | PubChem, FDA |
| Compound purchasability, vendor catalogs | ZINC | — |

### Identifier Resolution

When a database doesn't recognize an identifier, convert it using these workflows:

**Compounds**: Name → **PubChem** `/compound/name/{name}/cids/JSON` → get CID → convert to ChEMBL ID via **UniChem** or **ChEMBL** molecule search. If name lookup fails, try SMILES, InChIKey, or CAS number.


If you don't recognize your platform or the fetch tool fails, fall back to `curl` via whatever shell/terminal tool is available. Example:
```bash
curl -s -H "Accept: application/json" "https://api.example.com/endpoint"
```

### Request guidelines

- Set `Accept: application/json` header where supported
- URL-encode special characters in query parameters — SMILES strings (`/`, `#`, `=`, `@`), compound names with parentheses, and ontology terms with colons (`HP:0001250` → `HP%3A0001250`) are common sources of failures. With `curl`, use `--data-urlencode` for safety.
- **Parallel OK**: When querying *different* databases (e.g., PubChem + ChEMBL + Reactome), run them in parallel — most APIs have generous rate limits.
- **Serialize requests to rate-limited APIs**: NCBI APIs (Gene, GEO, Protein, Taxonomy, dbSNP, SRA) at 3 req/sec without key, 10 with key. Also watch: Ensembl (15 req/sec), BLS v1 (25 req/day without key), SEC EDGAR (10 req/sec), NOAA (5 req/sec with token).
- If you get a rate-limit error (HTTP 429 or 503), wait briefly and retry once

### Error recovery

If an API returns an error or empty results:
1. **Check the identifier format** — use the Common Identifier Formats table above. A gene symbol may need to be converted to NCBI Gene ID or Ensembl ID first.
2. **Try alternative identifiers** — if a compound name fails in PubChem, try SMILES, InChIKey, or CID. If a gene symbol fails, try the NCBI Gene ID.
3. **Try a different database** — if one database is down or returns nothing, check the "Also consider" column in the selection guide for alternatives.
4. **Report the failure** — tell the user which database failed, the error, and what you tried instead.

### Pagination

Many APIs return paginated results — if you only read the first page, you may miss data. Common patterns:

- **Offset/Limit**: `offset=0&limit=100` → increment offset by limit for the next page (ChEMBL, FRED, NOAA, USGS, NCBI E-utilities, ENA, GDC, FDA)
- **Cursor-based**: Response includes a `nextPageToken` or `cursor` value — pass it in the next request (ClinicalTrials.gov, UniProt)
- **Page number**: `page=1&per_page=50` → increment page (World Bank, cBioPortal, ZINC)

Check the reference file for each database's specific pagination parameters. If a response includes `total`, `totalCount`, or `next` and the number of returned results is less than the total, there are more pages.

For targeted lookups (single gene, single compound), the first page is usually sufficient. Paginate when the user needs comprehensive results (e.g., "all clinical trials for X" or "all known variants in gene Y").

## Output Format

Structure your response like this:

```
## Databases Queried
- **PubChem** — /compound/name/aspirin/property/...
- **Reactome** — /search/query?query=aspirin

## Results

### PubChem
[raw JSON response]

### Reactome
[raw JSON response]
```

If results are very large, present the most relevant portion and note that additional data is available. But default to showing the full raw JSON — the user asked for it.


## Available Databases

Read the relevant reference file before making any API call.


### Chemistry & Drugs
| Database | Reference File | What it covers |
|---|---|---|
| PubChem | `references/pubchem.md` | Compounds, properties, synonyms |

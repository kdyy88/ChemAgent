---
name: database-lookup
description: Search public chemistry, drug, and biomedical databases via their REST APIs. Covers compounds (PubChem, ChEMBL, ZINC, ChEBI, BindingDB), drugs (DailyMed, FDA/OpenFDA, KEGG), proteins/structures (UniProt, PDB, AlphaFold, STRING, Reactome), and clinical data (Open Targets, ClinicalTrials.gov).
user-invocable: true
argument-hint: "{\"query\": \"[搜索词]\", \"smiles\": \"[可选结构]\"}"
metadata:
  when_to_use: Use when the user asks to look up compounds, drugs, proteins, targets, pathways, binding affinities, drug-target interactions, clinical trials, or any data from a public chemistry/biomedical database API. Also trigger when a database is mentioned by name, or the task involves molecular properties, pharmacology, ADMET cross-referencing, or purchasable compound searches.
---

# Database Lookup (Chemistry & Biomedical)

You have access to public chemistry and biomedical databases through their REST APIs. Your job is to figure out which database(s) are relevant to the user's question, query them, and return the raw JSON results along with which databases you used.

## Core Workflow

1. **Understand the query** — What is the user looking for? A compound? A gene? A pathway? A binding affinity? This determines which database(s) to hit.

2. **Select database(s)** — Use the database selection guide below. When in doubt, search multiple databases — it's better to cast a wide net than to miss relevant data.

3. **Read the reference file** — Each database has a reference file in `references/` with endpoint details, query formats, and example calls. Read the relevant file(s) before making API calls.

4. **Make the API call(s)** — See the **Making API Calls** section below for which HTTP fetch tool to use on your platform.

5. **Return results** — Always return:
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
| Drug synonyms, CAS numbers | PubChem (synonyms) | — |
| Bioactivity data, IC50, binding assays | ChEMBL | BindingDB, PubChem |
| Drug binding affinities (Ki, IC50, Kd) | ChEMBL, BindingDB | PubChem |
| Drug-target interactions | ChEMBL | BindingDB, Open Targets |
| Ligands for a protein target (by UniProt) | BindingDB | ChEMBL |
| Target identification from compound structure | BindingDB (SMILES similarity) | ChEMBL |
| Drug labels, adverse events, recalls | FDA (OpenFDA) | DailyMed |
| Drug labels (structured product labels) | DailyMed | FDA (OpenFDA) |
| Chemical cross-referencing | PubChem (xrefs) | ChEMBL |
| Commercially available compounds for screening | ZINC | PubChem |
| Similarity/substructure search (purchasable) | ZINC | PubChem, ChEMBL |
| Drug-like compound libraries, building blocks | ZINC | — |
| FDA-approved drug structures | ZINC (fda subset) | PubChem, FDA |
| Compound purchasability, vendor catalogs | ZINC | — |
| Metabolic pathways involving compounds | KEGG | Reactome |
| Chemical entities of biological interest | ChEBI | PubChem |

### Biology (Drug-Target Relevant)
| User is asking about... | Primary database(s) | Also consider |
|---|---|---|
| Biological pathways | Reactome, KEGG | — |
| What pathways a gene/protein is in | Reactome (mapping), KEGG | — |
| Protein sequence, function, annotation | UniProt | — |
| Protein-protein interactions | STRING | — |
| 3D protein structures (experimental) | PDB (RCSB) | — |
| 3D protein structures (predicted) | AlphaFold DB | PDB |

### Disease & Clinical (Drug-Related)
| User is asking about... | Primary database(s) | Also consider |
|---|---|---|
| Drug-target-disease associations | Open Targets | ChEMBL |
| Clinical trials for a drug/disease | ClinicalTrials.gov | FDA |
| Pharmacogenomics, drug-gene interactions | ClinPGx (PharmGKB) | — |

### Cross-Domain Queries
| User is asking about... | Primary database(s) | Also consider |
|---|---|---|
| Everything about a compound | PubChem + ChEMBL | BindingDB, ZINC, Reactome, FDA |
| Everything about a drug target | UniProt + PDB + STRING | Reactome, ChEMBL, Open Targets |
| Drug target pathways | ChEMBL + Reactome | Open Targets |

When the user's query spans multiple domains (e.g. "what do we know about aspirin"), query all relevant databases in parallel.

## Common Identifier Formats

| Identifier | Format | Example | Used by |
|---|---|---|---|
| PubChem CID | Integer | `2244` (aspirin) | PubChem |
| ChEMBL ID | `CHEMBL####` | `CHEMBL25` (aspirin) | ChEMBL |
| UniProt accession | `P#####` or `Q#####` | `P04637` (TP53) | UniProt, STRING, AlphaFold, Reactome |
| PDB ID | 4-char alphanumeric | `1OHR` | PDB |
| ZINC ID | `ZINC` + 15 digits | `ZINC000000000053` (aspirin) | ZINC |
| Reactome stable ID | `R-HSA-######` | `R-HSA-109581` | Reactome |
| KEGG compound | `C#####` | `C00022` (pyruvate) | KEGG |
| ChEBI ID | `CHEBI:#####` | `CHEBI:15365` (aspirin) | ChEBI |

### Identifier Resolution

**Compounds**: Name → **PubChem** `/compound/name/{name}/cids/JSON` → get CID → convert to ChEMBL ID via **ChEMBL** molecule search. If name lookup fails, try SMILES, InChIKey, or CAS number.

**Proteins**: Gene symbol (e.g. "TP53") → **UniProt** search (`gene_exact:{symbol} AND organism_id:9606`) → get UniProt accession → use in STRING, AlphaFold, Reactome.

**Diseases**: Name → **Open Targets** search → get EFO ID → use in downstream queries.

## POST-Only APIs

These databases require HTTP POST and **will not work with WebFetch** (GET-only). Use `curl` via your platform's shell tool instead:

| Database | Why POST needed | Example |
|---|---|---|
| Open Targets | GraphQL endpoint | `curl -X POST -H "Content-Type: application/json" -d '{"query":"..."}' https://api.platform.opentargets.org/api/v4/graphql` |

## Databases with Restricted Access

| Database | Restriction | Free alternative |
|---|---|---|
| DrugBank | Paid API license required | Use **ChEMBL** + **PubChem** + **OpenFDA** instead |
| COSMIC | Free academic registration required (JWT auth) | Use **Open Targets** for cancer mutation data |
| BRENDA | Free registration required (SOAP, not REST) | Use **KEGG** for enzyme/pathway data |

When a restricted database is needed, fall back to the free alternative and tell the user.

## API Keys

Some databases work better with an API key (free registration). Check the environment first (`$VAR_NAME`), then `.env`, then proceed without.

| Database | Env Variable | Note |
|---|---|---|
| NCBI (PubChem, Gene) | `NCBI_API_KEY` | Higher rate limits with key |
| OpenFDA | `OPENFDA_API_KEY` | Optional, works without |

## Making API Calls

Use your environment's HTTP fetch tool. Fall back to `curl` if unavailable:
```bash
curl -s -H "Accept: application/json" "https://api.example.com/endpoint"
```

### Request guidelines

- Set `Accept: application/json` header where supported
- URL-encode special characters — SMILES strings (`/`, `#`, `=`, `@`) and ontology terms with colons are common failure sources
- **Parallel OK**: When querying *different* databases (e.g., PubChem + ChEMBL + Reactome), run them in parallel
- If you get a rate-limit error (HTTP 429 or 503), wait briefly and retry once

### Error recovery

1. **Check the identifier format** — use the Common Identifier Formats table
2. **Try alternative identifiers** — if a name fails, try SMILES, InChIKey, or CID
3. **Try a different database** — check the "Also consider" column for alternatives
4. **Report the failure** — tell the user which database failed and what you tried instead

## Available Databases

Read the relevant reference file before making any API call.

### Chemistry & Drugs
| Database | Reference File | What it covers |
|---|---|---|
| PubChem | `references/pubchem.md` | Compounds, properties, synonyms |
| ChEMBL | `references/chembl.md` | Bioactivity, drug discovery |
| FDA (OpenFDA) | `references/fda.md` | Drug labels, adverse events, recalls |
| DailyMed | `references/dailymed.md` | Drug labels (NIH/NLM) |
| KEGG | `references/kegg.md` | Pathways, genes, compounds |
| ChEBI | `references/chebi.md` | Chemical entities of biological interest |
| ZINC | `references/zinc.md` | Commercially available compounds, virtual screening |
| BindingDB | `references/bindingdb.md` | Experimentally measured binding affinities |

### Biology (Drug-Target Relevant)
| Database | Reference File | What it covers |
|---|---|---|
| UniProt | `references/uniprot.md` | Protein sequences, function |
| STRING | `references/string.md` | Protein-protein interactions |
| PDB | `references/pdb.md` | Protein 3D structures |
| AlphaFold DB | `references/alphafold.md` | Predicted protein structures |
| Reactome | `references/reactome.md` | Biological pathways, reactions |

### Disease & Clinical
| Database | Reference File | What it covers |
|---|---|---|
| Open Targets | `references/opentargets.md` | Target-disease associations (POST) |
| ClinPGx (PharmGKB) | `references/clinpgx.md` | Pharmacogenomics |
| ClinicalTrials.gov | `references/clinicaltrials.md` | Clinical trial registry |

## 5. Synthesis & Output Format (Crucial)

You are an expert computational chemist and structural biologist. **DO NOT act like a simple web scraper.**

1. **Blend Internal Knowledge with API Data:** First, structure your answer using your vast internal domain knowledge. For example, if asked about a protein (like TP53), use your knowledge to explain its biological context, its well-known domains (e.g., TAD, DBD, CTD), and classic structures (e.g., 1TSR). Then, use the API data to *verify* this information, extract the exact sequence, or provide the latest/most specific PDB IDs.
2. **Scientist-Friendly Formatting:**
   - Present information in a highly readable, structured, and educational manner (use Markdown tables, bold text, and clear sections).
   - For long lists (like PDBs), categorize them logically (e.g., by domain, by method, or highlight the top 3 most representative ones) instead of dumping all of them.
3. **NO Developer Logs:**
   - **NEVER** output raw JSON blocks.
   - **NEVER** output raw HTTP requests (like `GET https://...`).
   - Simply acknowledge the data sources elegantly (e.g., "*Based on the latest data from UniProt and RCSB PDB...*").

## Adding New Databases

Each database is a self-contained reference file in `references/`. To add a new database:

1. Create `references/<database-name>.md` following the same format as existing files
2. Add an entry to the database selection guide above
3. The reference file should include: base URL, key endpoints, query parameter formats, example calls, rate limits, and response structure

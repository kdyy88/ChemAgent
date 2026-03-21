/**
 * Typed fetch wrapper for the deterministic chemistry REST endpoints.
 *
 * `structure_image` is always a bare base64 string returned by the backend.
 * The `data:image/png;base64,` URI prefix is added exclusively in LipinskiCard
 * JSX to avoid double-prefixing.
 */

const BASE_URL =
  (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000')
    .replace(/^ws/, 'http')
    .replace(/\/$/, '')

// ── Property types ────────────────────────────────────────────────────────────

export type LipinskiProperty = {
  value: number
  threshold?: number   // present for the 4 Lipinski criteria
  pass?: boolean       // present for the 4 Lipinski criteria
  unit?: string        // present for TPSA ("Å²")
}

export type LipinskiProperties = {
  molecular_weight: LipinskiProperty
  log_p: LipinskiProperty
  h_bond_donors: LipinskiProperty
  h_bond_acceptors: LipinskiProperty
  tpsa: LipinskiProperty   // display-only, no threshold / pass
}

// ── Discriminated union ───────────────────────────────────────────────────────

export type LipinskiResult = {
  type: 'lipinski'
  is_valid: true
  smiles: string
  name: string
  properties: LipinskiProperties
  lipinski_pass: boolean
  violations: number
  /** Bare base64 PNG string — no data: URI prefix. */
  structure_image: string
}

export type LipinskiError = {
  is_valid: false
  error: string
}

export type LipinskiResponse = LipinskiResult | LipinskiError

// ── Fetch helper ──────────────────────────────────────────────────────────────

export async function analyzeMolecule(
  smiles: string,
  name = '',
): Promise<LipinskiResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles, name }),
  })

  if (!res.ok) {
    // Unexpected HTTP error (5xx, network proxy error, etc.)
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }

  return res.json() as Promise<LipinskiResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// Open Babel API types & fetch helpers
// All endpoints live under /api/babel/*
// ═══════════════════════════════════════════════════════════════════════════════

// ── Shared error shape ────────────────────────────────────────────────────────

export type BabelError = {
  is_valid: false
  error: string
}

// ── Tool 1: Universal Format Converter ───────────────────────────────────────

export type FormatConversionResult = {
  type: 'format_conversion'
  is_valid: true
  input_format: string
  output_format: string
  output: string
  atom_count: number
  heavy_atom_count: number
}

export type FormatConversionResponse = FormatConversionResult | BabelError

export async function convertFormat(
  molecule: string,
  inputFormat: string,
  outputFormat: string,
): Promise<FormatConversionResponse> {
  const res = await fetch(`${BASE_URL}/api/babel/convert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ molecule, input_format: inputFormat, output_format: outputFormat }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<FormatConversionResponse>
}

// ── Tool 2: 3D Conformer Builder ─────────────────────────────────────────────

export type Conformer3DResult = {
  type: 'conformer_3d'
  is_valid: true
  name: string
  smiles: string
  sdf_content: string
  atom_count: number
  heavy_atom_count: number
  forcefield: string
  steps: number
  has_3d_coords: boolean
}

export type Conformer3DResponse = Conformer3DResult | BabelError

export async function build3DConformer(
  smiles: string,
  name = '',
  forcefield = 'mmff94',
  steps = 500,
): Promise<Conformer3DResponse> {
  const res = await fetch(`${BASE_URL}/api/babel/conformer3d`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles, name, forcefield, steps }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Conformer3DResponse>
}

// ── Tool 3: PDBQT Docking Prep ───────────────────────────────────────────────

export type PdbqtPrepResult = {
  type: 'pdbqt_prep'
  is_valid: true
  name: string
  smiles: string
  pdbqt_content: string
  ph: number
  rotatable_bonds: number
  heavy_atom_count: number
  total_atom_count: number
  has_root_marker: boolean
  has_torsdof_marker: boolean
  /** True when rotatable_bonds > 10 — Vina/Smina accuracy degrades above this threshold. */
  flexibility_warning: boolean
}

export type PdbqtPrepResponse = PdbqtPrepResult | BabelError

export async function preparePdbqt(
  smiles: string,
  name = '',
  ph = 7.4,
): Promise<PdbqtPrepResponse> {
  const res = await fetch(`${BASE_URL}/api/babel/pdbqt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles, name, ph }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<PdbqtPrepResponse>
}

/**
 * Typed fetch wrapper for the deterministic chemistry REST endpoints.
 *
 * `structure_image` is always a bare base64 string returned by the backend.
 * The `data:image/png;base64,` URI prefix is added exclusively in JSX.
 */

const BASE_URL =
  (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000')
    .replace(/^ws/, 'http')
    .replace(/\/$/, '')

// ═══════════════════════════════════════════════════════════════════════════════
// Shared error shape
// ═══════════════════════════════════════════════════════════════════════════════

export type ChemError = {
  is_valid: false
  error: string
}

// ═══════════════════════════════════════════════════════════════════════════════
// T1: SMILES Validation
// ═══════════════════════════════════════════════════════════════════════════════

export type ValidateResult = {
  type: 'validate'
  is_valid: true
  input_smiles: string
  canonical_smiles: string
  formula: string
  atom_count: number
  heavy_atom_count: number
  bond_count: number
  ring_count: number
  is_canonical: boolean
}

export type ValidateResponse = ValidateResult | ChemError

export async function validateSmiles(smiles: string): Promise<ValidateResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<ValidateResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// T9: Salt Stripping & Neutralization
// ═══════════════════════════════════════════════════════════════════════════════

export type SaltStripResult = {
  type: 'salt_strip'
  is_valid: true
  original_smiles: string
  cleaned_smiles: string
  removed_fragments: string[]
  charge_neutralized: boolean
  had_salts: boolean
  parent_formula: string
  parent_heavy_atoms: number
  structure_image: string
}

export type SaltStripResponse = SaltStripResult | ChemError

export async function saltStrip(smiles: string): Promise<SaltStripResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/salt-strip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SaltStripResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// T3: Comprehensive Molecular Descriptors (replaces Lipinski)
// ═══════════════════════════════════════════════════════════════════════════════

export type LipinskiCriterion = {
  value: number
  threshold: number
  pass: boolean
}

export type DescriptorsResult = {
  type: 'descriptors'
  is_valid: true
  smiles: string
  name: string
  formula: string
  descriptors: {
    molecular_weight: number
    log_p: number
    h_bond_donors: number
    h_bond_acceptors: number
    tpsa: number
    rotatable_bonds: number
    ring_count: number
    aromatic_rings: number
    fraction_csp3: number
    heavy_atom_count: number
    qed: number
    sa_score: number
  }
  lipinski: {
    criteria: {
      molecular_weight: LipinskiCriterion
      log_p: LipinskiCriterion
      h_bond_donors: LipinskiCriterion
      h_bond_acceptors: LipinskiCriterion
    }
    pass: boolean
    violations: number
  }
  structure_image: string
}

export type DescriptorsResponse = DescriptorsResult | ChemError

export async function computeDescriptors(
  smiles: string,
  name = '',
): Promise<DescriptorsResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/descriptors`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles, name }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<DescriptorsResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// T4: Molecular Similarity
// ═══════════════════════════════════════════════════════════════════════════════

export type MolInfo = {
  smiles: string
  formula: string
  heavy_atoms: number
  image: string
}

export type SimilarityResult = {
  type: 'similarity'
  is_valid: true
  molecule_1: MolInfo
  molecule_2: MolInfo
  tanimoto: number
  interpretation: string
  fingerprint_type: string
  radius: number
  n_bits: number
}

export type SimilarityResponse = SimilarityResult | ChemError

export async function computeSimilarity(
  smiles1: string,
  smiles2: string,
  radius = 2,
  nBits = 2048,
): Promise<SimilarityResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/similarity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles1, smiles2, radius, n_bits: nBits }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SimilarityResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// T5: Substructure Search + PAINS
// ═══════════════════════════════════════════════════════════════════════════════

export type PainsAlert = {
  name: string
}

export type SubstructureResult = {
  type: 'substructure'
  is_valid: true
  smiles: string
  smarts_pattern: string
  matched: boolean
  match_count: number
  match_atoms: number[][]
  highlighted_image: string
  pains_alerts: PainsAlert[]
  pains_clean: boolean
}

export type SubstructureResponse = SubstructureResult | ChemError

export async function substructureMatch(
  smiles: string,
  smartsPattern: string,
): Promise<SubstructureResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/substructure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles, smarts_pattern: smartsPattern }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SubstructureResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// T6: Murcko Scaffold
// ═══════════════════════════════════════════════════════════════════════════════

export type ScaffoldResult = {
  type: 'scaffold'
  is_valid: true
  smiles: string
  scaffold_smiles: string
  generic_scaffold_smiles: string
  molecule_image: string
  scaffold_image: string
}

export type ScaffoldResponse = ScaffoldResult | ChemError

export async function murckoScaffold(smiles: string): Promise<ScaffoldResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/scaffold`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<ScaffoldResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// T7: Molecular Properties (OpenBabel)
// ═══════════════════════════════════════════════════════════════════════════════

export type MolPropertiesResult = {
  type: 'mol_properties'
  is_valid: true
  smiles: string
  formula: string
  exact_mass: number
  molecular_weight: number
  formal_charge: number
  spin_multiplicity: number
  heavy_atom_count: number
  atom_count: number
  bond_count: number
  rotatable_bonds: number
}

export type MolPropertiesResponse = MolPropertiesResult | ChemError

export async function computeMolProperties(
  smiles: string,
): Promise<MolPropertiesResponse> {
  const res = await fetch(`${BASE_URL}/api/babel/properties`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<MolPropertiesResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// Utility: Supported Formats (for ConvertTool dropdown)
// ═══════════════════════════════════════════════════════════════════════════════

export type FormatEntry = {
  code: string
  description: string
}

export type SupportedFormats = {
  input_formats: FormatEntry[]
  output_formats: FormatEntry[]
  input_count: number
  output_count: number
}

export async function fetchSupportedFormats(): Promise<SupportedFormats> {
  const res = await fetch(`${BASE_URL}/api/babel/formats`)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SupportedFormats>
}

// ═══════════════════════════════════════════════════════════════════════════════
// Existing types (kept for backward compat — used by BabelResultCard etc.)
// ═══════════════════════════════════════════════════════════════════════════════

// Re-export under old names for existing components
export type BabelError = ChemError

// ── Legacy Lipinski types (used by LipinskiCard in chat) ─────────────────────

export type LipinskiProperty = {
  value: number
  threshold?: number
  pass?: boolean
  unit?: string
}

export type LipinskiProperties = {
  molecular_weight: LipinskiProperty
  log_p: LipinskiProperty
  h_bond_donors: LipinskiProperty
  h_bond_acceptors: LipinskiProperty
  tpsa: LipinskiProperty
}

export type LipinskiResult = {
  type: 'lipinski'
  is_valid: true
  smiles: string
  name: string
  properties: LipinskiProperties
  lipinski_pass: boolean
  violations: number
  structure_image: string
}

export type LipinskiError = {
  is_valid: false
  error: string
}

export type LipinskiResponse = LipinskiResult | LipinskiError

export async function analyzeMolecule(
  smiles: string,
  name = '',
): Promise<LipinskiResponse> {
  const res = await fetch(`${BASE_URL}/api/rdkit/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles, name }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<LipinskiResponse>
}

// ── Open Babel existing types ────────────────────────────────────────────────

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
  energy_kcal_mol: number | null
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

// ═══════════════════════════════════════════════════════════════════════════════
// F2: Partial Charge Analysis
// ═══════════════════════════════════════════════════════════════════════════════

export type ChargeAtom = {
  idx: number
  element: string
  charge: number
}

export type PartialChargeResult = {
  type: 'partial_charge'
  is_valid: true
  smiles: string
  charge_model: string
  atoms: ChargeAtom[]
  heavy_atoms: ChargeAtom[]
  total_charge: number
  atom_count: number
  heavy_atom_count: number
}

export type PartialChargeResponse = PartialChargeResult | ChemError

export async function computePartialCharges(
  smiles: string,
  method = 'gasteiger',
): Promise<PartialChargeResponse> {
  const res = await fetch(`${BASE_URL}/api/babel/partial-charges`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ smiles, method }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<PartialChargeResponse>
}

// ═══════════════════════════════════════════════════════════════════════════════
// F3: SDF Batch Processing (Split / Merge)
// ═══════════════════════════════════════════════════════════════════════════════

export type SdfMolEntry = {
  index: number
  name: string
  smiles: string
}

export type SdfSplitResult = {
  type: 'sdf_split'
  is_valid: true
  molecule_count: number
  molecules: SdfMolEntry[]
}

export type SdfMergeResult = {
  type: 'sdf_merge'
  is_valid: true
  molecule_count: number
  error_count: number
}

export async function sdfSplit(file: File): Promise<SdfSplitResult | ChemError> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE_URL}/api/babel/sdf-split`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SdfSplitResult | ChemError>
}

export async function sdfMerge(files: File[]): Promise<SdfMergeResult | ChemError> {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  const res = await fetch(`${BASE_URL}/api/babel/sdf-merge`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SdfMergeResult | ChemError>
}

export function getSdfSplitDownloadUrl(): string {
  return `${BASE_URL}/api/babel/sdf-split-download`
}

export function getSdfMergeDownloadUrl(): string {
  return `${BASE_URL}/api/babel/sdf-merge-download`
}

import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BabelResultCard } from '../BabelResultCard'
import type { BabelResponse } from '../BabelResultCard'

// ── Setup ──────────────────────────────────────────────────────────────────────

beforeEach(() => {
  // clipboard
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  })
  // URL APIs used by triggerDownload
  vi.stubGlobal('URL', {
    createObjectURL: vi.fn().mockReturnValue('blob:mock'),
    revokeObjectURL: vi.fn(),
  })
  // Prevent JSDOM click error on anchor
  HTMLAnchorElement.prototype.click = vi.fn()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ── Fixtures ───────────────────────────────────────────────────────────────────

const errorData: BabelResponse = { is_valid: false, error: 'Babel conversion failed.' }

const formatConversionData: BabelResponse = {
  type: 'format_conversion',
  is_valid: true,
  input_format: 'smi',
  output_format: 'sdf',
  output: 'mol-data-here',
  atom_count: 26,
  heavy_atom_count: 9,
}

const conformer3dData: BabelResponse = {
  type: 'conformer_3d',
  is_valid: true,
  name: 'Ethanol',
  smiles: 'CCO',
  sdf_content: 'sdf-content-here',
  atom_count: 9,
  heavy_atom_count: 3,
  forcefield: 'mmff94',
  steps: 500,
  has_3d_coords: true,
  energy_kcal_mol: -5.1,
}

const conformer3dNoCoords: BabelResponse = {
  ...conformer3dData,
  has_3d_coords: false,
} as BabelResponse

const pdbqtData: BabelResponse = {
  type: 'pdbqt_prep',
  is_valid: true,
  name: 'Ligand',
  smiles: 'CCO',
  pdbqt_content: 'pdbqt-content-here',
  ph: 7.4,
  rotatable_bonds: 5,
  heavy_atom_count: 3,
  total_atom_count: 9,
  has_root_marker: true,
  has_torsdof_marker: true,
  flexibility_warning: false,
}

const pdbqtFlexible: BabelResponse = {
  ...pdbqtData,
  rotatable_bonds: 12,
  flexibility_warning: true,
} as BabelResponse

const pdbqtMissingMarkers: BabelResponse = {
  ...pdbqtData,
  has_root_marker: false,
  has_torsdof_marker: false,
} as BabelResponse

// ── BabelErrorCard ─────────────────────────────────────────────────────────────

describe('BabelResultCard – error state', () => {
  it('shows "转换失败" heading', () => {
    render(<BabelResultCard data={errorData} />)
    expect(screen.getByText('转换失败')).toBeInTheDocument()
  })

  it('shows the error message', () => {
    render(<BabelResultCard data={errorData} />)
    expect(screen.getByText('Babel conversion failed.')).toBeInTheDocument()
  })
})

// ── FormatConversionCard ───────────────────────────────────────────────────────

describe('BabelResultCard – format_conversion', () => {
  it('shows "格式转换成功"', () => {
    render(<BabelResultCard data={formatConversionData} />)
    expect(screen.getByText('格式转换成功')).toBeInTheDocument()
  })

  it('displays input and output format badges', () => {
    render(<BabelResultCard data={formatConversionData} />)
    expect(screen.getByText('smi')).toBeInTheDocument()
    expect(screen.getByText('sdf')).toBeInTheDocument()
  })

  it('shows atom count info rows', () => {
    render(<BabelResultCard data={formatConversionData} />)
    expect(screen.getByText('重原子数')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
  })

  it('shows the output content in a pre block', () => {
    render(<BabelResultCard data={formatConversionData} />)
    expect(screen.getByText('mol-data-here')).toBeInTheDocument()
  })

  it('copy button calls clipboard.writeText with output', async () => {
    render(<BabelResultCard data={formatConversionData} />)
    fireEvent.click(screen.getByText('复制'))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('mol-data-here')
  })

  it('copy button shows "已复制！" after clicking', async () => {
    render(<BabelResultCard data={formatConversionData} />)
    fireEvent.click(screen.getByText('复制'))
    await waitFor(() => expect(screen.getByText('已复制！')).toBeInTheDocument())
  })
})

// ── Conformer3DCard ────────────────────────────────────────────────────────────

describe('BabelResultCard – conformer_3d', () => {
  it('shows generation success heading', () => {
    render(<BabelResultCard data={conformer3dData} />)
    expect(screen.getByText('Ethanol — 生成成功')).toBeInTheDocument()
  })

  it('does NOT show 3D warning when has_3d_coords=true', () => {
    render(<BabelResultCard data={conformer3dData} />)
    expect(screen.queryByText(/Z 坐标全为零/)).not.toBeInTheDocument()
  })

  it('shows 3D coordinate warning when has_3d_coords=false', () => {
    render(<BabelResultCard data={conformer3dNoCoords} />)
    expect(screen.getByText(/Z 坐标全为零/)).toBeInTheDocument()
  })

  it('shows force field value', () => {
    render(<BabelResultCard data={conformer3dData} />)
    expect(screen.getByText('mmff94')).toBeInTheDocument()
  })

  it('shows step count', () => {
    render(<BabelResultCard data={conformer3dData} />)
    expect(screen.getByText('500')).toBeInTheDocument()
  })
})

// ── PdbqtPrepCard ─────────────────────────────────────────────────────────────

describe('BabelResultCard – pdbqt_prep', () => {
  it('shows docking file ready heading', () => {
    render(<BabelResultCard data={pdbqtData} />)
    expect(screen.getByText('Ligand — 对接文件就绪')).toBeInTheDocument()
  })

  it('does NOT show flexibility warning when rotatable_bonds <= 10', () => {
    render(<BabelResultCard data={pdbqtData} />)
    // The InfoRow label '可旋转键数' is always shown; the specific warning about
    // exceeding the Vina/Smina limit should NOT appear.
    expect(screen.queryByText(/超过 Vina\/Smina/)).not.toBeInTheDocument()
    expect(screen.queryByText(/超过.*推荐上限/)).not.toBeInTheDocument()
  })

  it('shows flexibility warning when rotatable_bonds > 10', () => {
    render(<BabelResultCard data={pdbqtFlexible} />)
    expect(screen.getByText(/可旋转键 12 个/)).toBeInTheDocument()
  })

  it('does NOT show marker integrity error when markers are present', () => {
    render(<BabelResultCard data={pdbqtData} />)
    expect(screen.queryByText(/缺少必需标记/)).not.toBeInTheDocument()
  })

  it('shows marker integrity error when markers are missing', () => {
    render(<BabelResultCard data={pdbqtMissingMarkers} />)
    expect(screen.getByText(/缺少必需标记/)).toBeInTheDocument()
  })

  it('shows pH value', () => {
    render(<BabelResultCard data={pdbqtData} />)
    expect(screen.getByText('7.4')).toBeInTheDocument()
  })
})

// ── ContentPreview truncation (tested via FormatConversionCard) ────────────────

describe('BabelResultCard – ContentPreview truncation', () => {
  it('shows full content when output has ≤12 lines', () => {
    const data: BabelResponse = { ...formatConversionData, output: Array(10).fill('line').join('\n') } as BabelResponse
    render(<BabelResultCard data={data} />)
    // 10 lines → no truncation → no expand button
    expect(screen.queryByText(/展开查看全部/)).not.toBeInTheDocument()
    // All content visible in the <pre> block
    const pre = document.querySelector('pre')
    expect(pre?.textContent).toContain('line')
  })

  it('shows truncation hint "(N 行，展开查看全部)" when output has >12 lines', () => {
    const long = Array(20).fill('line').join('\n')
    const data: BabelResponse = { ...formatConversionData, output: long } as BabelResponse
    render(<BabelResultCard data={data} />)
    expect(screen.getByText(/20 行，展开查看全部/)).toBeInTheDocument()
  })

  it('expands to full content on button click', () => {
    const long = Array(20).fill('a').join('\n')
    const data: BabelResponse = { ...formatConversionData, output: long } as BabelResponse
    render(<BabelResultCard data={data} />)
    fireEvent.click(screen.getByText(/20 行，展开查看全部/))
    // After expansion, the "expand" hint should be gone
    expect(screen.queryByText(/20 行，展开查看全部/)).not.toBeInTheDocument()
  })
})

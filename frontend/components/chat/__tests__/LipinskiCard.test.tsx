import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LipinskiCard } from '../LipinskiCard'
import type { LipinskiResponse } from '@/lib/chem-api'

// ── Fixtures ───────────────────────────────────────────────────────────────────

function makeSuccessData(overrides?: Partial<{
  name: string
  lipinski_pass: boolean
  violations: number
}>): LipinskiResponse {
  return {
    type: 'lipinski',
    is_valid: true,
    smiles: 'CCO',
    name: overrides?.name ?? 'Ethanol',
    lipinski_pass: overrides?.lipinski_pass ?? true,
    violations: overrides?.violations ?? 0,
    structure_image: 'iVBORw0KGgo=',
    properties: {
      molecular_weight: { value: 46.07, threshold: 500, pass: true },
      log_p: { value: -0.31, threshold: 5, pass: true },
      h_bond_donors: { value: 1, threshold: 5, pass: true },
      h_bond_acceptors: { value: 1, threshold: 10, pass: true },
      tpsa: { value: 20.23, unit: 'Å²' },
    },
  }
}

const errorData: LipinskiResponse = {
  is_valid: false,
  error: 'Invalid SMILES string: XYZ',
}

// ── Error state ────────────────────────────────────────────────────────────────

describe('LipinskiCard – error state', () => {
  it('renders the error message', () => {
    render(<LipinskiCard data={errorData} />)
    expect(screen.getByText('Invalid SMILES string: XYZ')).toBeInTheDocument()
  })

  it('shows "SMILES 解析失败" heading', () => {
    render(<LipinskiCard data={errorData} />)
    expect(screen.getByText('SMILES 解析失败')).toBeInTheDocument()
  })

  it('shows a helpful tip', () => {
    render(<LipinskiCard data={errorData} />)
    expect(screen.getByText(/请检查环闭合/)).toBeInTheDocument()
  })
})

// ── Success state ──────────────────────────────────────────────────────────────

describe('LipinskiCard – success state', () => {
  it('shows the molecule name', () => {
    render(<LipinskiCard data={makeSuccessData({ name: 'Aspirin' })} />)
    expect(screen.getByText('Aspirin')).toBeInTheDocument()
  })

  it('shows "Unnamed Molecule" when name is empty', () => {
    render(<LipinskiCard data={makeSuccessData({ name: '' })} />)
    expect(screen.getByText('Unnamed Molecule')).toBeInTheDocument()
  })

  it('shows "通过 Lipinski 五规则" badge when lipinski_pass=true', () => {
    render(<LipinskiCard data={makeSuccessData({ lipinski_pass: true })} />)
    expect(screen.getByText('通过 Lipinski 五规则')).toBeInTheDocument()
  })

  it('shows violation count badge when lipinski_pass=false', () => {
    render(<LipinskiCard data={makeSuccessData({ lipinski_pass: false, violations: 2 })} />)
    expect(screen.getByText('2 条违规')).toBeInTheDocument()
  })

  it('renders the molecule image with data URI prefix', () => {
    render(<LipinskiCard data={makeSuccessData()} />)
    const img = document.querySelector('img')!
    expect(img.getAttribute('src')).toMatch(/^data:image\/png;base64,/)
  })

  it('renders the molecule SMILES string', () => {
    render(<LipinskiCard data={makeSuccessData()} />)
    expect(screen.getByText('CCO')).toBeInTheDocument()
  })
})

// ── Property rows ──────────────────────────────────────────────────────────────

describe('LipinskiCard – property rows', () => {
  it('renders the four Lipinski property labels', () => {
    render(<LipinskiCard data={makeSuccessData()} />)
    expect(screen.getByText('分子量')).toBeInTheDocument()
    expect(screen.getByText('脂水分配系数 LogP')).toBeInTheDocument()
    expect(screen.getByText('氢键供体 HBD')).toBeInTheDocument()
    expect(screen.getByText('氢键受体 HBA')).toBeInTheDocument()
  })

  it('renders TPSA row labeled "极性表面积 TPSA"', () => {
    render(<LipinskiCard data={makeSuccessData()} />)
    expect(screen.getByText('极性表面积 TPSA')).toBeInTheDocument()
  })

  it('shows "参考值" label for the TPSA row (isReference=true)', () => {
    render(<LipinskiCard data={makeSuccessData()} />)
    expect(screen.getByText('参考值')).toBeInTheDocument()
  })

  it('displays threshold values with ≤ prefix', () => {
    render(<LipinskiCard data={makeSuccessData()} />)
    // MW threshold = 500
    expect(screen.getByText('≤ 500')).toBeInTheDocument()
  })
})

// ── Footer ─────────────────────────────────────────────────────────────────────

describe('LipinskiCard – footer', () => {
  it('shows positive footer when lip pass', () => {
    render(<LipinskiCard data={makeSuccessData({ lipinski_pass: true })} />)
    expect(screen.getByText(/符合 Lipinski 五规则/)).toBeInTheDocument()
  })

  it('shows violation count in footer', () => {
    render(<LipinskiCard data={makeSuccessData({ lipinski_pass: false, violations: 3 })} />)
    expect(screen.getByText(/3 条 Lipinski 违规/)).toBeInTheDocument()
  })

  it('always shows TPSA disclaimer note', () => {
    render(<LipinskiCard data={makeSuccessData()} />)
    expect(screen.getByText(/TPSA 为参考值/)).toBeInTheDocument()
  })
})

import { describe, expect, it } from 'vitest'
import { parseLipinskiToolCalls, toLipinskiResponse } from '@/lib/chem-parsers'
import type { SSETurn } from '@/lib/sse-types'

describe('toLipinskiResponse', () => {
  it('converts descriptor payloads into Lipinski cards', () => {
    const result = toLipinskiResponse({
      type: 'descriptors',
      is_valid: true,
      smiles: 'CCO',
      name: 'Ethanol',
      descriptors: {
        tpsa: 20.23,
      },
      lipinski: {
        pass: true,
        violations: 0,
        criteria: {
          molecular_weight: { value: 46.07, threshold: 500, pass: true },
          log_p: { value: -0.31, threshold: 5, pass: true },
          h_bond_donors: { value: 1, threshold: 5, pass: true },
          h_bond_acceptors: { value: 1, threshold: 10, pass: true },
        },
      },
      structure_image: 'base64-image',
    })

    expect(result).toMatchObject({
      type: 'lipinski',
      is_valid: true,
      name: 'Ethanol',
      lipinski_pass: true,
      violations: 0,
      properties: {
        molecular_weight: { value: 46.07, threshold: 500, pass: true },
        tpsa: { value: 20.23, unit: 'Å²' },
      },
    })
  })

  it('passes through already-normalized Lipinski payloads', () => {
    const result = toLipinskiResponse({
      type: 'lipinski',
      is_valid: true,
      smiles: 'CCO',
      name: 'Ethanol',
      lipinski_pass: true,
      violations: 0,
      structure_image: 'base64-image',
      properties: {
        molecular_weight: { value: 46.07, threshold: 500, pass: true },
        log_p: { value: -0.31, threshold: 5, pass: true },
        h_bond_donors: { value: 1, threshold: 5, pass: true },
        h_bond_acceptors: { value: 1, threshold: 10, pass: true },
        tpsa: { value: 20.23, unit: 'Å²' },
      },
    })

    expect(result).toMatchObject({
      type: 'lipinski',
      is_valid: true,
      name: 'Ethanol',
    })
  })

  it('returns invalid response objects for structured backend errors', () => {
    expect(
      toLipinskiResponse({
        is_valid: false,
        error: 'Invalid SMILES',
      }),
    ).toEqual({
      is_valid: false,
      error: 'Invalid SMILES',
    })
  })

  it('rejects unrelated payloads', () => {
    expect(toLipinskiResponse({ type: 'similarity', is_valid: true })).toBeNull()
  })
})

describe('parseLipinskiToolCalls', () => {
  it('filters out incomplete and unrelated tool outputs', () => {
    const toolCalls: SSETurn['toolCalls'] = [
      {
        tool: 'tool_compute_descriptors',
        input: { smiles: 'CCO' },
        done: true,
        output: {
          type: 'descriptors',
          is_valid: true,
          smiles: 'CCO',
          name: 'Ethanol',
          descriptors: { tpsa: 20.23 },
          lipinski: {
            pass: true,
            violations: 0,
            criteria: {
              molecular_weight: { value: 46.07, threshold: 500, pass: true },
              log_p: { value: -0.31, threshold: 5, pass: true },
              h_bond_donors: { value: 1, threshold: 5, pass: true },
              h_bond_acceptors: { value: 1, threshold: 10, pass: true },
            },
          },
          structure_image: 'base64-image',
        },
      },
      {
        tool: 'tool_compute_descriptors',
        input: { smiles: 'CCC' },
        done: false,
      },
      {
        tool: 'tool_validate_smiles',
        input: { smiles: 'CCC' },
        done: true,
        output: { canonical_smiles: 'CCC' },
      },
    ]

    const result = parseLipinskiToolCalls(toolCalls)

    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({
      type: 'lipinski',
      is_valid: true,
      name: 'Ethanol',
    })
  })
})
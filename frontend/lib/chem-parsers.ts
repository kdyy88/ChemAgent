import type { LipinskiResponse } from '@/lib/chem-api'
import type { SSETurn } from '@/lib/sse-types'

type CriterionValue = {
  value: number
  threshold?: number
  pass?: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function toCriterion(value: unknown): CriterionValue | null {
  if (!isRecord(value)) return null
  const nextValue = toNumber(value.value)
  if (nextValue === null) return null

  const threshold = toNumber(value.threshold)
  return {
    value: nextValue,
    threshold: threshold ?? undefined,
    pass: typeof value.pass === 'boolean' ? value.pass : undefined,
  }
}

export function toLipinskiResponse(output: unknown): LipinskiResponse | null {
  if (!isRecord(output)) return null

  if (output.is_valid === false && typeof output.error === 'string') {
    return { is_valid: false, error: output.error }
  }

  if (output.type === 'lipinski' && output.is_valid === true) {
    return output as LipinskiResponse
  }

  if (output.type !== 'descriptors' || output.is_valid !== true) return null

  const descriptors = isRecord(output.descriptors) ? output.descriptors : null
  const lipinski = isRecord(output.lipinski) ? output.lipinski : null
  const criteria = lipinski && isRecord(lipinski.criteria) ? lipinski.criteria : null

  if (!descriptors || !lipinski || !criteria) return null

  const mw = toCriterion(criteria.molecular_weight)
  const logP = toCriterion(criteria.log_p)
  const hbd = toCriterion(criteria.h_bond_donors)
  const hba = toCriterion(criteria.h_bond_acceptors)
  const tpsaValue = toNumber(descriptors.tpsa)

  if (!mw || !logP || !hbd || !hba || tpsaValue === null) return null

  return {
    type: 'lipinski',
    is_valid: true,
    smiles: typeof output.smiles === 'string' ? output.smiles : '',
    name: typeof output.name === 'string' ? output.name : '',
    properties: {
      molecular_weight: mw,
      log_p: logP,
      h_bond_donors: hbd,
      h_bond_acceptors: hba,
      tpsa: { value: tpsaValue, unit: 'Å²' },
    },
    lipinski_pass: Boolean(lipinski.pass),
    violations: toNumber(lipinski.violations) ?? 0,
    structure_image: typeof output.structure_image === 'string' ? output.structure_image : '',
  }
}

export function parseLipinskiToolCalls(toolCalls: SSETurn['toolCalls']): LipinskiResponse[] {
  return toolCalls
    .filter((toolCall) => toolCall.done && toolCall.tool === 'tool_compute_descriptors' && toolCall.output)
    .map((toolCall) => toLipinskiResponse(toolCall.output))
    .filter((card): card is LipinskiResponse => card !== null)
}
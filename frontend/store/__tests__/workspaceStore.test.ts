import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { useWorkspaceStore } from '../workspaceStore'

// Reset the store between each test
beforeEach(() => {
  useWorkspaceStore.setState({
    navMode: 'business',
    activeFunctionId: null,
    currentSmiles: '',
    currentName: '',
  })
})

describe('workspaceStore – initial state', () => {
  it('navMode defaults to "business"', () => {
    expect(useWorkspaceStore.getState().navMode).toBe('business')
  })

  it('activeFunctionId defaults to null', () => {
    expect(useWorkspaceStore.getState().activeFunctionId).toBeNull()
  })

  it('currentSmiles defaults to empty string', () => {
    expect(useWorkspaceStore.getState().currentSmiles).toBe('')
  })

  it('currentName defaults to empty string', () => {
    expect(useWorkspaceStore.getState().currentName).toBe('')
  })
})

describe('workspaceStore – setNavMode()', () => {
  it('switches to "software"', () => {
    useWorkspaceStore.getState().setNavMode('software')
    expect(useWorkspaceStore.getState().navMode).toBe('software')
  })

  it('switches back to "business"', () => {
    useWorkspaceStore.getState().setNavMode('software')
    useWorkspaceStore.getState().setNavMode('business')
    expect(useWorkspaceStore.getState().navMode).toBe('business')
  })
})

describe('workspaceStore – setActiveFunctionId()', () => {
  it('sets the active function id', () => {
    useWorkspaceStore.getState().setActiveFunctionId('validate')
    expect(useWorkspaceStore.getState().activeFunctionId).toBe('validate')
  })

  it('resets to null', () => {
    useWorkspaceStore.getState().setActiveFunctionId('descriptors')
    useWorkspaceStore.getState().setActiveFunctionId(null)
    expect(useWorkspaceStore.getState().activeFunctionId).toBeNull()
  })

  it('accepts all valid FunctionId values', () => {
    const ids = ['validate', 'salt-strip', 'descriptors', 'mol-properties', 'similarity',
      'substructure', 'scaffold', 'partial-charge', 'convert', 'conformer', 'pdbqt', 'sdf-batch'] as const
    for (const id of ids) {
      useWorkspaceStore.getState().setActiveFunctionId(id)
      expect(useWorkspaceStore.getState().activeFunctionId).toBe(id)
    }
  })
})

describe('workspaceStore – setSmiles()', () => {
  it('sets the current SMILES', () => {
    useWorkspaceStore.getState().setSmiles('CCO')
    expect(useWorkspaceStore.getState().currentSmiles).toBe('CCO')
  })

  it('overwrites the previous value', () => {
    useWorkspaceStore.getState().setSmiles('CCO')
    useWorkspaceStore.getState().setSmiles('C1=CC=CC=C1')
    expect(useWorkspaceStore.getState().currentSmiles).toBe('C1=CC=CC=C1')
  })

  it('clears SMILES when set to empty string', () => {
    useWorkspaceStore.getState().setSmiles('CCO')
    useWorkspaceStore.getState().setSmiles('')
    expect(useWorkspaceStore.getState().currentSmiles).toBe('')
  })
})

describe('workspaceStore – setName()', () => {
  it('sets the current molecule name', () => {
    useWorkspaceStore.getState().setName('Aspirin')
    expect(useWorkspaceStore.getState().currentName).toBe('Aspirin')
  })

  it('overwrites the previous name', () => {
    useWorkspaceStore.getState().setName('Aspirin')
    useWorkspaceStore.getState().setName('Caffeine')
    expect(useWorkspaceStore.getState().currentName).toBe('Caffeine')
  })
})

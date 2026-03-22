import { create } from 'zustand'

export type NavMode = 'software' | 'business'
export type FunctionId =
  | 'validate' | 'salt-strip'                    // 数据清洗
  | 'descriptors' | 'mol-properties'              // 物化性质
  | 'similarity' | 'substructure' | 'scaffold'    // 结构分析
  | 'partial-charge'                               // 电荷分析
  | 'convert' | 'conformer' | 'pdbqt'             // 3D 与对接
  | 'sdf-batch'                                    // 批量处理

interface WorkspaceState {
  navMode: NavMode
  activeFunctionId: FunctionId | null
  currentSmiles: string
  currentName: string
  setNavMode: (mode: NavMode) => void
  setActiveFunctionId: (id: FunctionId | null) => void
  setSmiles: (smiles: string) => void
  setName: (name: string) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  navMode: 'business',
  activeFunctionId: null,
  currentSmiles: '',
  currentName: '',
  setNavMode: (mode) => set({ navMode: mode }),
  setActiveFunctionId: (id) => set({ activeFunctionId: id }),
  setSmiles: (smiles) => set({ currentSmiles: smiles }),
  setName: (name) => set({ currentName: name }),
}))

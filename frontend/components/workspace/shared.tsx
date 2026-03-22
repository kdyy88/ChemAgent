import { AlertCircle } from 'lucide-react'

const EXAMPLES = [
  { label: 'Aspirin',    smiles: 'CC(=O)Oc1ccccc1C(=O)O' },
  { label: 'Ibuprofen',  smiles: 'CC(C)Cc1ccc(cc1)C(C)C(=O)O' },
  { label: 'Caffeine',   smiles: 'Cn1cnc2c1c(=O)n(c(=O)n2C)C' },
  { label: 'Paclitaxel', smiles: 'O=C(O[C@@H]1C[C@]2(OC(=O)c3ccccc3)[C@@H](O)C[C@@H](O)[C@]2(C)[C@@H](OC(C)=O)[C@@H]1OC(=O)[C@@H](O)[C@@H](NC(=O)c1ccccc1)c1ccccc1)c1ccccc1' },
]

export function ExampleChips({
  onSelect,
}: {
  onSelect: (smiles: string, label: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {EXAMPLES.map((ex) => (
        <button
          key={ex.label}
          onClick={() => onSelect(ex.smiles, ex.label)}
          className="rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
        >
          {ex.label}
        </button>
      ))}
    </div>
  )
}

export function NetworkErrorAlert({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-3">
      <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
      <div className="text-sm text-destructive font-medium">
        <p>{message}</p>
      </div>
    </div>
  )
}

export function FieldLabel({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="text-xs font-medium text-muted-foreground mb-1 block">
      {children}
      {required && <span className="text-destructive ml-0.5">*</span>}
      {!required && <span className="opacity-50 ml-1">(可选)</span>}
    </label>
  )
}

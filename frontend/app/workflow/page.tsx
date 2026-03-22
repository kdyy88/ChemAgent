import Link from 'next/link'
import { ArrowLeft, FlaskConical } from 'lucide-react'
import { Button } from '@/components/ui/button'
// Client component wrapper that owns dynamic(ssr:false) — required because
// next/dynamic with ssr:false is not allowed directly in Server Components.
import AgentFlowEditorDynamic from '@/components/orchestrator/AgentFlowEditorDynamic'

export default function WorkflowPage() {
  return (
    <main className="h-dvh flex flex-col bg-background">
      {/* Header — fixed 64px (h-16), matching the calc(100vh-64px) in AgentFlowEditor */}
      <header className="h-16 shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="h-full px-4 flex items-center gap-3">
          {/* Brand mark */}
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <FlaskConical className="h-4 w-4 text-primary-foreground" />
          </div>

          {/* Title */}
          <div className="flex-1">
            <h1 className="text-sm font-semibold leading-none">Agent Workflow Editor</h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              Drag &amp; drop to build multi-agent pipelines · Save exports a{' '}
              <code className="font-mono">.waldiez.json</code>
            </p>
          </div>

          {/* Back to chat */}
          <Button variant="ghost" size="sm" asChild className="gap-1.5 text-muted-foreground hover:text-foreground">
            <Link href="/">
              <ArrowLeft className="h-4 w-4" />
              <span className="hidden sm:inline text-xs">Back to Chat</span>
            </Link>
          </Button>
        </div>
      </header>

      {/* Canvas — AgentFlowEditor handles its own height via h-[calc(100vh-64px)] */}
      <AgentFlowEditorDynamic />
    </main>
  )
}

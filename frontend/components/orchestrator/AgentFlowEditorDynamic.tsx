'use client'

// dynamic() with ssr:false must live in a Client Component in Next.js App Router.
// This thin wrapper exists solely for that constraint; the page stays a Server Component.
import dynamic from 'next/dynamic'

const AgentFlowEditor = dynamic(
  () => import('@/components/orchestrator/AgentFlowEditor'),
  { ssr: false }
)

export default function AgentFlowEditorDynamic() {
  return <AgentFlowEditor />
}

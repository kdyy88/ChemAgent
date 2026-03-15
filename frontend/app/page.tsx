import { FlaskConical } from 'lucide-react'
import { MessageList } from '@/components/chat/MessageList'
import { ChatInput } from '@/components/chat/ChatInput'

export default function Home() {
  return (
    <main className="flex flex-col h-[100dvh] bg-background">
      {/* Header */}
      <header className="shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <FlaskConical className="h-4 w-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-sm font-semibold leading-none">ChemAgent</h1>
            <p className="text-xs text-muted-foreground mt-0.5">AI Chemistry Expert</p>
          </div>
        </div>
      </header>

      {/* Chat area */}
      <div className="flex-1 overflow-hidden">
        <MessageList />
      </div>

      {/* Input bar */}
      <footer className="shrink-0 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-5xl mx-auto px-4 py-3">
          <ChatInput />
        </div>
      </footer>
    </main>
  )
}

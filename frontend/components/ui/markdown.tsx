import { cn } from "@/lib/utils"
import { marked } from "marked"
import { memo, useId, useMemo } from "react"
import ReactMarkdown, { Components } from "react-markdown"
import remarkBreaks from "remark-breaks"
import remarkGfm from "remark-gfm"
import { CodeBlock, CodeBlockCode } from "./code-block"

export type MarkdownProps = {
  children: string
  id?: string
  className?: string
  components?: Partial<Components>
}

import { Button } from "@/components/ui/button"
import { useWorkspaceStore } from "@/store/workspaceStore"

function parseMarkdownIntoBlocks(markdown: string): string[] {
  const tokens = marked.lexer(markdown)
  return tokens.map((token) => token.raw)
}

function extractLanguage(className?: string): string {
  if (!className) return "plaintext"
  const match = className.match(/language-(\w+)/)
  return match ? match[1] : "plaintext"
}

const INITIAL_COMPONENTS: Partial<Components> = {
  code: function CodeComponent({ className, children, ...props }) {
    const isInline =
      !props.node?.position?.start.line ||
      props.node?.position?.start.line === props.node?.position?.end.line

    if (isInline) {
      return (
        <span
          className={cn(
            "bg-primary-foreground rounded-sm px-1 font-mono text-sm",
            className
          )}
          {...props}
        >
          {children}
        </span>
      )
    }

    const language = extractLanguage(className)

    return (
      <CodeBlock className={className}>
        <CodeBlockCode code={children as string} language={language} />
      </CodeBlock>
    )
  },
  pre: function PreComponent({ children }) {
    return <>{children}</>
  },
  a: function AComponent({ href, children, ...props }) {
    if (href?.startsWith('action:apply-smiles:')) {
      const smiles = href.replace('action:apply-smiles:', '')
      return (
        <Button 
          variant="outline" 
          size="sm" 
          className="my-2 bg-primary/10 hover:bg-primary/20 text-primary border-primary/30"
          onClick={(e) => {
            e.preventDefault()
            useWorkspaceStore.getState().setSmiles(smiles)
          }}
        >
          {children || 'Apply to Workspace'}
        </Button>
      )
    }
    // Guard: bare/relative hrefs (e.g. Chinese text used as link target) would
    // trigger Next.js client-side navigation to a non-existent route → 404.
    // Render them as plain styled text instead.
    const isSafeHref =
      !href ||
      href.startsWith('http://') ||
      href.startsWith('https://') ||
      href.startsWith('mailto:') ||
      href.startsWith('#') ||
      href.startsWith('/') ||
      href.startsWith('action:')
    if (!isSafeHref) {
      return (
        <span className="underline decoration-dotted cursor-default" title={href}>
          {children}
        </span>
      )
    }
    return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
  }
}

const MemoizedMarkdownBlock = memo(
  function MarkdownBlock({
    content,
    components = INITIAL_COMPONENTS,
  }: {
    content: string
    components?: Partial<Components>
  }) {
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    )
  },
  function propsAreEqual(prevProps, nextProps) {
    return prevProps.content === nextProps.content
  }
)

MemoizedMarkdownBlock.displayName = "MemoizedMarkdownBlock"

function MarkdownComponent({
  children,
  id,
  className,
  components = INITIAL_COMPONENTS,
}: MarkdownProps) {
  const generatedId = useId()
  const blockId = id ?? generatedId
  
  // Intercept special tag <ApplySmiles smiles="..." />
  const processedChildren = children.replace(
    /<ApplySmiles\s+smiles="([^"]+)"\s*(?:><\/ApplySmiles>|\/>)/g,
    (_, smiles) => `[应用到工作台（Apply to Workspace）](action:apply-smiles:${smiles})`
  )

  const blocks = useMemo(() => parseMarkdownIntoBlocks(processedChildren), [processedChildren])

  return (
    <div className={className}>
      {blocks.map((block, index) => (
        <MemoizedMarkdownBlock
          key={`${blockId}-block-${index}`}
          content={block}
          components={components}
        />
      ))}
    </div>
  )
}

const Markdown = memo(MarkdownComponent)
Markdown.displayName = "Markdown"

export { Markdown }

"use client"

import { CHEM_LANG_IDS, CHEM_LANGS, type ChemLangId } from "@/lib/shiki-chem-langs"
import { cn } from "@/lib/utils"
import React, { useEffect, useState } from "react"
import { bundledLanguages, getSingletonHighlighter } from "shiki"

/** Languages bundled in Shiki. */
const BUNDLED = new Set(Object.keys(bundledLanguages))

async function highlightCode(code: string, language: string, theme: string): Promise<string> {
  const isChem = (CHEM_LANG_IDS as readonly string[]).includes(language)
  const isKnown = isChem || BUNDLED.has(language)
  const lang = isKnown ? language : "text"

  const highlighter = await getSingletonHighlighter({ langs: [], themes: [theme] })

  // Load the language if not already registered
  const loaded = highlighter.getLoadedLanguages()
  if (!loaded.includes(lang)) {
    if (isChem) {
      await highlighter.loadLanguage(CHEM_LANGS[language as ChemLangId])
    } else if (lang !== "text") {
      await highlighter.loadLanguage(lang as never)
    }
  }

  return highlighter.codeToHtml(code, { lang: loaded.includes(lang) ? lang : "text", theme })
}

export type CodeBlockProps = {
  children?: React.ReactNode
  className?: string
} & React.HTMLProps<HTMLDivElement>

function CodeBlock({ children, className, ...props }: CodeBlockProps) {
  return (
    <div
      className={cn(
        "not-prose flex w-full flex-col overflow-clip border",
        "border-border bg-card text-card-foreground rounded-xl",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export type CodeBlockCodeProps = {
  code: string
  language?: string
  theme?: string
  className?: string
} & React.HTMLProps<HTMLDivElement>

function CodeBlockCode({
  code,
  language = "tsx",
  theme = "github-light",
  className,
  ...props
}: CodeBlockCodeProps) {
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function highlight() {
      if (!code) {
        if (!cancelled) setHighlightedHtml("<pre><code></code></pre>")
        return
      }

      // code comes from LLM/tool output only — not raw user input
      try {
        const html = await highlightCode(code, language, theme)
        if (!cancelled) setHighlightedHtml(html)
      } catch {
        // Language not bundled in Shiki — fall back to plain text highlight
        const html = await highlightCode(code, "text", theme)
        if (!cancelled) setHighlightedHtml(html)
      }
    }
    highlight()

    return () => { cancelled = true }
  }, [code, language, theme])

  const classNames = cn(
    "w-full overflow-x-auto text-[13px] [&>pre]:px-4 [&>pre]:py-4",
    className
  )

  // SSR fallback: render plain code if not hydrated yet
  return highlightedHtml ? (
    <div
      className={classNames}
      dangerouslySetInnerHTML={{ __html: highlightedHtml }}
      {...props}
    />
  ) : (
    <div className={classNames} {...props}>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  )
}

export type CodeBlockGroupProps = React.HTMLAttributes<HTMLDivElement>

function CodeBlockGroup({
  children,
  className,
  ...props
}: CodeBlockGroupProps) {
  return (
    <div
      className={cn("flex items-center justify-between", className)}
      {...props}
    >
      {children}
    </div>
  )
}

export { CodeBlockGroup, CodeBlockCode, CodeBlock }

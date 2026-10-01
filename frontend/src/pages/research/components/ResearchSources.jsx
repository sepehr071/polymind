import { useMemo } from 'react'
import { ExternalLink, Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { dedupeCitations, isGroundingRedirectUrl } from '@/utils/citations'
import { cn } from '@/lib/utils'

/**
 * Citation list — human domain labels only; never show Vertex redirect paths.
 */
export default function ResearchSources({ citations, className, compact = false }) {
  const { t } = useTranslation('research')

  const items = useMemo(() => {
    if (!Array.isArray(citations) || !citations.length) return []
    const resolved = dedupeCitations(
      citations.map((c) => ({
        url: c.url,
        title: c.title,
        content: c.snippet || c.content,
        snippet: c.snippet,
      })),
    )
    return resolved.map((r, i) => ({
      index: i + 1,
      href: r.href,
      domain: r.domain,
      // Prefer short domain chip over long page titles for list density
      label: r.domain || r.title || t('sourcesUntitled'),
      title: r.title && r.title !== r.domain ? r.title : '',
      snippet: r.snippet || '',
    }))
  }, [citations, t])

  if (!items.length) {
    return (
      <p className={cn('text-sm text-muted-foreground', className)}>
        {t('sourcesEmpty')}
      </p>
    )
  }

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold flex items-center gap-1.5">
          <Globe className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          {t('sources')}
        </h3>
        <span className="text-xs text-muted-foreground">
          {t('sourcesCount', { count: items.length })}
        </span>
      </div>
      <ol className={cn('space-y-2', compact && 'space-y-1.5')}>
        {items.map((c) => {
          const href = c.href && !isGroundingRedirectUrl(c.href) ? c.href : (c.domain ? `https://${c.domain}` : '')
          const inner = (
            <>
              <span className="shrink-0 font-medium tabular-nums text-muted-foreground group-hover:text-accent">
                [{c.index}]
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-foreground group-hover:text-accent break-words" dir="ltr">
                  {c.label}
                </span>
                {c.title && c.title !== c.label && !isGroundingRedirectUrl(c.title) && (
                  <span className="mt-0.5 block text-[11px] text-muted-foreground line-clamp-2" dir="auto">
                    {c.title}
                  </span>
                )}
              </span>
              {href && (
                <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-50 group-hover:opacity-100" aria-hidden />
              )}
            </>
          )
          return (
            <li
              key={`${c.index}-${c.label}-${href}`}
              id={`research-source-${c.index}`}
              className="rounded-lg border border-border/50 bg-bg-2/50 px-3 py-2 text-sm scroll-mt-24"
            >
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-start gap-2 text-accent hover:underline"
                  dir="ltr"
                  title={href}
                >
                  {inner}
                </a>
              ) : (
                <div className="flex items-start gap-2" dir="ltr">
                  {inner}
                </div>
              )}
              {c.snippet && !compact && (
                <p className="mt-1.5 text-xs text-muted-foreground line-clamp-2" dir="auto">
                  {c.snippet}
                </p>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

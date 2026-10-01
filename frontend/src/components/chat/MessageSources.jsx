import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe, ExternalLink } from 'lucide-react'
import { dedupeCitations } from '../../utils/citations'

/* ═══════════════════════════════════════════════════════════════════════
   MessageSources — web-search url_citation list under assistant replies.
   Extracted from ChatWindow so the read-only shared-snapshot view reuses it.
   ═══════════════════════════════════════════════════════════════════════ */
const MessageSources = memo(function MessageSources({ annotations }) {
  const { t } = useTranslation('chat')

  if (!Array.isArray(annotations) || annotations.length === 0) return null

  const sources = dedupeCitations(
    annotations
      .map((a) => {
        if (!a || typeof a !== 'object') return null
        if (a.type && a.type !== 'url_citation') return null
        // Nested chat-completions shape, or the flat Responses-API shape.
        if (a.url_citation && typeof a.url_citation === 'object') return a.url_citation
        return a.url ? a : null
      })
      .filter(Boolean)
  )

  if (sources.length === 0) return null

  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-foreground-tertiary mb-2">
        <Globe className="h-3.5 w-3.5" />
        <span>{t('window.sources')}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {sources.map((s, idx) => (
          <a
            key={s.domain || s.href}
            href={s.href}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-1.5 rounded-full border border-border bg-background-secondary px-2.5 py-1 text-xs text-foreground-secondary hover:bg-background-tertiary hover:text-foreground transition-colors"
          >
            <span className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full bg-background-tertiary text-[10px] font-medium tabular-nums text-foreground-tertiary group-hover:bg-background">
              {idx + 1}
            </span>
            <span className="truncate max-w-[14rem]" dir="auto" title={s.href}>
              {s.title && s.title !== s.domain ? s.title : s.domain}
            </span>
            <ExternalLink className="h-3 w-3 flex-shrink-0 opacity-50 group-hover:opacity-100" />
          </a>
        ))}
      </div>
    </div>
  )
})

export default MessageSources

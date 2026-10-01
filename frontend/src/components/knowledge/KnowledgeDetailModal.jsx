import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { X, Copy, Check, Star, Pencil, Folder, ExternalLink } from 'lucide-react'
import MarkdownRenderer from '../chat/MarkdownRenderer'
import { knowledgeService } from '../../services/knowledgeService'
import { getTextDirection, containsRTL } from '../../utils/rtl'
import { fmtDate } from '../../utils/dateLocale'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '../ui/dialog'

export default function KnowledgeDetailModal({ item, folders = [], onClose, onEdit }) {
  const { t } = useTranslation('knowledge')
  const [copied, setCopied] = useState(false)

  // List rows ship only a truncated ``content_preview`` (the full ``content``
  // Text column is projected out for payload size). Fetch the full item on
  // open; the preview paints instantly while the per-id GET resolves.
  const { data: full } = useQuery({
    queryKey: ['knowledge', item?._id],
    queryFn: () => knowledgeService.get(item._id),
    enabled: !!item?._id,
    staleTime: 60_000,
  })

  if (!item) return null

  const content = full?.item?.content ?? item.content ?? item.content_preview ?? ''

  // Find folder name if item has folder_id
  const folder = item.folder_id
    ? folders.find(f => f._id === item.folder_id)
    : null

  // Source link: an internal chat conversation (or absolute in-app path) routes
  // through react-router so it stays an SPA transition (a raw <a href> triggered
  // a full page reload). An external http(s) source URL stays a real <a>
  // (target/rel) — only internal links are converted.
  const sourceUrl = item.source?.url
  const isExternalSource = typeof sourceUrl === 'string' && /^https?:\/\//i.test(sourceUrl)
  const internalSourceTo = item.source?.conversation_id
    ? `/chat/${item.source.conversation_id}`
    : (typeof sourceUrl === 'string' && sourceUrl.startsWith('/') ? sourceUrl : null)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  const handleEdit = () => {
    onClose()
    onEdit?.(item)
  }

  return (
    <Dialog open={!!item} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent
        showClose={false}
        className="w-full max-w-4xl max-h-[90vh] p-0 gap-0 overflow-hidden flex flex-col"
      >
        {/* Accessible name/description for the dialog (visual title lives in the
            styled header below to preserve the RTL-aware truncation + favorite star). */}
        <DialogTitle className="sr-only">{item.title}</DialogTitle>
        <DialogDescription className="sr-only">{t('detail.from', { type: item.source?.type || '' })}</DialogDescription>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <h3
              className={`font-semibold text-foreground truncate ${containsRTL(item.title) ? 'font-persian' : ''}`}
              title={item.title}
              dir={getTextDirection(item.title)}
            >
              {item.title}
            </h3>
            {item.is_favorite && (
              <Star className="h-4 w-4 text-warning fill-current flex-shrink-0" />
            )}
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            <button
              onClick={handleCopy}
              className="p-2 rounded-lg hover:bg-background-tertiary text-foreground-secondary hover:text-foreground transition-colors"
              title={t('detail.copy')}
            >
              {copied ? (
                <Check className="h-4 w-4 text-success" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </button>
            {onEdit && (
              <button
                onClick={handleEdit}
                className="p-2 rounded-lg hover:bg-background-tertiary text-foreground-secondary hover:text-foreground transition-colors"
                title={t('detail.edit')}
              >
                <Pencil className="h-4 w-4" />
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-background-tertiary text-foreground-secondary hover:text-foreground transition-colors"
              title={t('detail.close')}
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Metadata bar */}
        <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-background-secondary/50 flex-shrink-0 flex-wrap">
          {item.source?.type && (
            <span className="text-xs text-foreground-tertiary capitalize">
              {t('detail.from', { type: item.source.type })}
            </span>
          )}
          {folder && (
            <span className="flex items-center gap-1 text-xs text-foreground-tertiary">
              <Folder className="h-3 w-3" style={{ color: folder.color }} />
              {folder.name}
            </span>
          )}
          {item.created_at && (
            <span className="text-xs text-foreground-tertiary">
              {fmtDate(new Date(item.created_at), "MMM d, yyyy 'at' HH:mm")}
            </span>
          )}
          {internalSourceTo && (
            <Link
              to={internalSourceTo}
              className="flex items-center gap-1 text-xs text-accent hover:text-accent-hover transition-colors"
              title={t('detail.view_source')}
            >
              <ExternalLink className="h-3 w-3" />
              {t('detail.view_source')}
            </Link>
          )}
          {!internalSourceTo && isExternalSource && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-accent hover:text-accent-hover transition-colors"
              title={t('detail.view_source')}
            >
              <ExternalLink className="h-3 w-3" />
              {t('detail.view_source')}
            </a>
          )}
        </div>

        {/* Tags */}
        {item.tags && item.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 px-4 py-2 border-b border-border flex-shrink-0">
            {item.tags.map((tag) => (
              <span
                key={tag}
                className="px-2 py-0.5 text-xs bg-accent/10 text-accent rounded-full"
              >
                #{tag}
              </span>
            ))}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          <div
            className="markdown-content prose prose-invert max-w-none"
            dir={getTextDirection(content)}
          >
            <MarkdownRenderer content={content || ''} />
          </div>
        </div>

        {/* Notes section (if present) */}
        {item.notes && (
          <div className="px-4 py-3 border-t border-border bg-background-secondary/30 flex-shrink-0">
            <div className="text-xs font-medium text-foreground-tertiary mb-1">{t('detail.notes_label')}</div>
            <p
              className={`text-sm text-foreground-secondary whitespace-pre-wrap ${containsRTL(item.notes) ? 'font-persian' : ''}`}
              dir={getTextDirection(item.notes)}
            >
              {item.notes}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

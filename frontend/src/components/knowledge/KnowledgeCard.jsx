import { memo } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Star, Pencil, Trash2, ExternalLink, Folder, FolderInput } from 'lucide-react'
import { cn } from '../../utils/cn'
import { getTextDirection, containsRTL } from '../../utils/rtl'
import { fmtDate } from '../../utils/dateLocale'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import HoverLift from '@/components/ui/hover-lift'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

function KnowledgeCard({
  item,
  folders = [],
  onEdit,
  onDelete,
  onToggleFavorite,
  onTagClick,
  onMoveToFolder,
  onViewDetail
}) {
  const { t } = useTranslation('knowledge')
  const { confirm, confirmDialog } = useConfirmDelete()

  const handleDelete = async () => {
    const ok = await confirm({
      title: t('card.delete_confirm_title'),
      description: t('card.delete_confirm_desc', { title: item.title }),
      confirmLabel: t('card.delete'),
      destructive: true,
    })
    if (ok) onDelete(item._id)
  }

  // Find folder name if item has folder_id
  const folder = item.folder_id
    ? folders.find(f => f._id === item.folder_id)
    : null

  // Source link: an internal chat conversation routes through react-router so
  // it stays an SPA transition (a raw <a href> triggered a full page reload).
  // An external source URL stays a real <a> (target/rel) — only internal links
  // are converted.
  const sourceUrl = item.source?.url
  const isExternalSource = typeof sourceUrl === 'string' && /^https?:\/\//i.test(sourceUrl)
  // Only treat a source URL as an in-app route when it's an absolute path
  // ('/...'). A bare domain or arbitrary non-http string would otherwise become
  // a relative SPA path and dead-end on the 404 page.
  const internalSourceTo = item.source?.conversation_id
    ? `/chat/${item.source.conversation_id}`
    : (typeof sourceUrl === 'string' && sourceUrl.startsWith('/') ? sourceUrl : null)
  return (
    <HoverLift y={-3} className="group">
      <Card className="overflow-hidden rounded-2xl transition-colors hover:border-border-strong">
      {/* Content - clickable area */}
      <div className="p-4">
        {/* Header with title and favorite */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <h3
            className={`text-sm font-bold text-foreground line-clamp-1 ${containsRTL(item.title) ? 'font-persian' : ''}`}
            title={item.title}
            dir={getTextDirection(item.title)}
          >
            <button
              type="button"
              className="text-start w-full cursor-pointer hover:text-accent transition-colors"
              onClick={() => onViewDetail?.(item)}
            >
              {item.title}
            </button>
          </h3>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onToggleFavorite(item._id, item.is_favorite)}
            className={cn(
              'h-8 w-8 flex-shrink-0',
              item.is_favorite
                ? 'text-warning hover:text-warning/80'
                : 'text-foreground-tertiary hover:text-foreground-secondary'
            )}
            title={item.is_favorite ? t('card.fav_remove') : t('card.fav_add')}
            aria-label={item.is_favorite ? t('card.fav_remove') : t('card.fav_add')}
          >
            <Star className={cn('h-4 w-4', item.is_favorite && 'fill-current')} />
          </Button>
        </div>

        {/* Content preview - clickable */}
        <button
          type="button"
          className={`text-sm text-foreground-secondary line-clamp-3 mb-3 whitespace-pre-wrap cursor-pointer hover:text-foreground transition-colors text-start w-full ${containsRTL(item.content_preview) ? 'font-persian' : ''}`}
          onClick={() => onViewDetail?.(item)}
          dir={getTextDirection(item.content_preview)}
        >
          {item.content_preview}
        </button>

        {/* Tags */}
        {item.tags && item.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {item.tags.map((tag) => (
              <button
                key={tag}
                onClick={() => onTagClick?.(tag)}
                className="px-2 py-0.5 text-xs bg-accent/10 text-accent rounded-full hover:bg-accent/20 transition-colors"
              >
                #{tag}
              </button>
            ))}
          </div>
        )}

        {/* Metadata */}
        <div className="flex items-center gap-2 text-xs text-foreground-tertiary flex-wrap">
          {item.source?.type && (
            <span>
              {t(`source_types.${item.source.type}`, { defaultValue: item.source.type })}
            </span>
          )}
          {folder && (
            <>
              <span>•</span>
              <span className="flex items-center gap-1">
                <Folder className="h-3 w-3" style={{ color: folder.color }} />
                {folder.name}
              </span>
            </>
          )}
          {item.created_at && (
            <>
              <span>•</span>
              <span>{fmtDate(new Date(item.created_at), 'MMM d, yyyy')}</span>
            </>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="px-4 py-2 border-t border-border bg-background-secondary/40 flex items-center gap-1 opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 transition-opacity">
        {internalSourceTo && (
          <Button asChild variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs">
            <Link to={internalSourceTo} title={t('card.source')}>
              <ExternalLink className="h-3 w-3" />
              {t('card.source')}
            </Link>
          </Button>
        )}
        {!internalSourceTo && isExternalSource && (
          <Button asChild variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs">
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" title={t('card.source')}>
              <ExternalLink className="h-3 w-3" />
              {t('card.source')}
            </a>
          </Button>
        )}
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onMoveToFolder?.(item)}
          className="h-8 w-8 max-md:h-10 max-md:w-10 text-foreground-secondary hover:text-foreground"
          title={t('card.move_to_folder')}
          aria-label={t('card.move_to_folder')}
        >
          <FolderInput className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onEdit(item)}
          className="h-8 w-8 max-md:h-10 max-md:w-10 text-foreground-secondary hover:text-foreground"
          title={t('card.edit')}
          aria-label={t('card.edit')}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleDelete}
          className="h-8 w-8 max-md:h-10 max-md:w-10 text-foreground-secondary hover:text-error hover:bg-error/10"
          title={t('card.delete')}
          aria-label={t('card.delete')}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      {confirmDialog}
      </Card>
    </HoverLift>
  )
}

export default memo(KnowledgeCard)

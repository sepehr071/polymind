import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Image as ImageIcon, Download, Heart, Trash2, Pencil, Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { CostValue } from '@/components/ui/CostValue'
import { CreditValue } from '@/components/ui/CreditValue'
import { canSeePrice } from '@/utils/money'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import useMediaQuery from '@/hooks/useMediaQuery'
import { imageService } from '../../services/imageService'
import { cn } from '../../utils/cn'
import { fmtDate } from '../../utils/dateLocale'
import { fmtNumber } from '../../utils/persianLocale'

/**
 * Clean image detail modal — the de-cluttered W2 surface.
 *
 * Shows ONLY: large preview, prompt, negative prompt (when present), aspect
 * ratio, reference-image count (when > 0), created date, and the actions
 * Download / Favorite / Delete / Continue editing. The old technical rows
 * (model id, seed, generation id, source/workflow-run, raw "other metadata"
 * JSON) are intentionally gone — those are debug noise for an end-user gallery.
 *
 * The big preview uses the MEDIUM (~1024px) rendition fetched by id (same as the
 * studio canvas) — NOT the 256px list thumb (too small → renders tiny) and NOT
 * the multi-MB full base64 (heavy). The thumb is the instant placeholder; the
 * preview swaps in. Download fetches the full payload via the page's handler.
 *
 * @param {object} props
 * @param {boolean} props.open
 * @param {object|null} props.image Serialized image row (thumb-only).
 * @param {() => void} props.onClose
 * @param {(loadedData?: string) => void} props.onDownload Fetches full by id when no payload is passed.
 * @param {boolean} [props.isDownloading] In-flight lock from {@link useImageDownload}.
 * @param {() => void} props.onToggleFavorite
 * @param {() => void} props.onDelete
 * @param {(image: object) => void} props.onContinueEditing Opens the image's
 *   edit thread in the Generate tab (existing thread when `conversation_id` is
 *   set, else seeds a new thread with this image as the edit parent).
 */
export default function ImageDetailModal({
  open, image, onClose, onDownload, onToggleFavorite, onDelete, onContinueEditing,
  isDownloading = false,
}) {
  const { t } = useTranslation('dashboard')
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const { user } = useAuth()
  const { workspaces } = useWorkspace()
  // Tier gate (utils/money): price viewers see the $ cost row; everyone else
  // sees a Polymind Credits row. Never leak a $ figure to a normal user.
  const priceVisible = canSeePrice(user, workspaces)

  // Medium preview by id (cached, immutable per image). Hook runs before the
  // early return — gated by `enabled` so a null image / closed modal is a no-op.
  const previewQuery = useQuery({
    queryKey: ['imagePreview', image?._id],
    queryFn: () => imageService.getImagePreview(image._id),
    enabled: !!image?._id && open,
    staleTime: Infinity,
  })

  if (!image) return null

  const settings = image.settings || {}
  const metadata = image.metadata || {}
  const inputImagesCount = settings.input_images_count
  const aspectRatio = image.aspect_ratio || metadata.aspect_ratio || settings.aspect_ratio
  // Per-image tokens — top-level field (new), falling back to raw provider usage.
  const tokensTotal = image.tokens?.total ?? metadata.usage?.total_tokens ?? null
  // Prefer the medium (~1024px) WebP rendition over the multi-MB full base64
  // (matches the docstring); tiny list thumb is the last-resort placeholder.
  const previewSrc = previewQuery.data?.preview || image.image_data || image.thumb

  // One inner layout, rendered inside either a Dialog (≥md) or a bottom Sheet
  // (<md) — never duplicated.
  const body = (
    <>
      <div className="flex-1 min-w-0 bg-black/80 flex items-center justify-center p-4">
        {previewSrc ? (
          <img
            src={previewSrc}
            alt={image.prompt}
            decoding="async"
            className="max-w-full max-h-full object-contain rounded-lg"
          />
        ) : (
          <Skeleton className="h-40 w-40 rounded-lg" />
        )}
      </div>

      <div className="md:w-96 md:border-s border-border bg-background-secondary flex flex-col shrink-0 max-h-[40vh] md:max-h-none md:h-full">
        <div className="px-5 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-2 mb-1">
            <IconTile icon={ImageIcon} tone="amber" size="md" />
            <h2 className="text-sm font-semibold text-foreground">{t('imageHistory.imageDetails')}</h2>
          </div>
          {image.created_at && (
            <p className="text-[11px] text-foreground-tertiary">
              {fmtDate(new Date(image.created_at), 'PPpp')}
            </p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          <DetailRow label={t('imageHistory.prompt')}>
            <p dir="auto" className="whitespace-pre-wrap leading-relaxed">{image.prompt || '—'}</p>
          </DetailRow>

          {image.negative_prompt && (
            <DetailRow label={t('imageHistory.negativePrompt')}>
              <p dir="auto" className="whitespace-pre-wrap leading-relaxed text-foreground-secondary">
                {image.negative_prompt}
              </p>
            </DetailRow>
          )}

          {aspectRatio && (
            <DetailRow label={t('imageHistory.aspectRatio')}>
              <span dir="ltr">{aspectRatio}</span>
            </DetailRow>
          )}

          {(inputImagesCount != null && inputImagesCount > 0) && (
            <DetailRow label={t('imageHistory.referenceImages')}>
              {fmtNumber(inputImagesCount)}
            </DetailRow>
          )}

          {tokensTotal != null && (
            <DetailRow label={t('imageHistory.tokens')}>
              <span dir="ltr">{fmtNumber(tokensTotal)}</span>
            </DetailRow>
          )}

          {priceVisible ? (
            <DetailRow label={t('imageHistory.cost')}>
              <CostValue usd={image.cost_usd} className="tabular-nums" />
            </DetailRow>
          ) : (
            <DetailRow label={t('imageHistory.credits')}>
              <CreditValue credits={image.credits} className="tabular-nums" />
            </DetailRow>
          )}
        </div>

        <div className="px-5 py-4 border-t border-border flex flex-col sm:flex-row sm:flex-wrap gap-2 shrink-0">
          {onContinueEditing && (
            <Button
              variant="default"
              onClick={() => onContinueEditing(image)}
              className="w-full sm:flex-1 sm:w-auto sm:min-w-[140px]"
            >
              <Pencil className="h-4 w-4" />
              {t('imageStudio.continueEditing')}
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => onDownload()}
            disabled={isDownloading}
            aria-busy={isDownloading}
            className="w-full sm:flex-1 sm:w-auto sm:min-w-[120px]"
          >
            {isDownloading
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Download className="h-4 w-4" />}
            {isDownloading ? t('imageHistory.downloading') : t('imageHistory.download')}
          </Button>
          <Button
            variant="secondary"
            onClick={onToggleFavorite}
            className="w-full sm:flex-1 sm:w-auto sm:min-w-[100px]"
          >
            <Heart className={cn('h-4 w-4', image.is_favorite && 'fill-current text-destructive')} />
            {image.is_favorite ? t('imageHistory.unfavorite') : t('imageHistory.favorite')}
          </Button>
          <Button
            variant="destructive"
            size="icon"
            onClick={onDelete}
            className="w-full sm:w-10"
            aria-label={t('imageHistory.delete')}
            title={t('imageHistory.delete')}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </>
  )

  // <md: full-height bottom sheet. The accessible Title/Description live inside
  // the sheet/dialog (visually hidden) since the panel already shows the heading.
  if (!isDesktop) {
    return (
      <Sheet open={open} onOpenChange={(o) => { if (!o) onClose() }}>
        <SheetContent
          side="bottom"
          className="h-[92dvh] p-0 gap-0 overflow-hidden flex flex-col"
        >
          <SheetTitle className="sr-only">{t('imageHistory.imageDetails')}</SheetTitle>
          <SheetDescription className="sr-only">{image.prompt || t('imageHistory.imageDetails')}</SheetDescription>
          {body}
        </SheetContent>
      </Sheet>
    )
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        aria-label={t('imageHistory.imageDetails')}
        className="w-[95vw] max-w-7xl h-[90vh] p-0 gap-0 overflow-hidden flex flex-col md:flex-row"
      >
        {/* Radix requires a Title/Description for aria-modal labelling; visually
            hidden here since the metadata panel already shows the heading. */}
        <DialogTitle className="sr-only">{t('imageHistory.imageDetails')}</DialogTitle>
        <DialogDescription className="sr-only">{image.prompt || t('imageHistory.imageDetails')}</DialogDescription>
        {body}
      </DialogContent>
    </Dialog>
  )
}

function DetailRow({ label, children }) {
  if (children == null || children === '') return null
  return (
    <div className="space-y-1">
      <span className="text-xs text-foreground-tertiary">{label}</span>
      <div className="text-sm text-foreground break-words">{children}</div>
    </div>
  )
}

import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Image as ImageIcon,
  Search,
  Download,
  Heart,
  Trash2,
  Loader2,
  CheckSquare,
  Square,
  X,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { imageService } from '../../services/imageService'
import LazyImageTile from './LazyImageTile'
import EmptyState from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { cn } from '../../utils/cn'
import { fmtNumber } from '@/utils/persianLocale'
import { fmtDistanceToNowSafe } from '@/utils/dateLocale'
import { prettifyModelName } from '@/utils/modelName'
import useDebouncedValue from '@/hooks/useDebouncedValue'
import { useImageDownload } from '@/hooks/useImageDownload'
import toast from 'react-hot-toast'

const LIMIT = 24

// Default viewport-driven grid track count. Extended past 2xl for ultra-wide
// displays. The History tab uses this; the studio side pane passes a denser
// override (it is a fixed ~22rem column, not the full viewport, so viewport
// breakpoints would otherwise pack 6 columns into 352px).
const DEFAULT_GRID_CLASS =
  'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 min-[1800px]:grid-cols-7 min-[2200px]:grid-cols-8'

/**
 * The shared rich image grid: search box + favorites-only toggle + paginated
 * grid of {@link LazyImageTile} tiles + select-mode bulk-delete toolbar +
 * delete confirm. Lifted out of the retired ImageHistoryPage so both the studio
 * History tab and any future surface share one implementation + one cache key.
 *
 * The React-Query key is the canonical `['imageHistory', { page, limit,
 * favoritesOnly, search }]` shape so a generate-then-`invalidateQueries(['imageHistory'])`
 * refreshes whatever page is mounted. Both `favoritesOnly` and the debounced
 * `search` are SERVER-side filters (backend `favorites=`/`search=` query params,
 * ILIKE on prompt — `total`/`pages` reflect them), so the key value drives the
 * actual fetch.
 *
 * @param {object} props
 * @param {(image: object) => void} props.onZoom Opens the detail modal for a tile.
 * @param {string} [props.gridClassName] Override for the responsive column
 *   tracks (defaults to DEFAULT_GRID_CLASS). The studio side pane passes a
 *   2-column class because it is a fixed-width column, not the full viewport.
 * @param {boolean} [props.compact] Glance variant for the studio side pane:
 *   hides the search/favorites/select toolbar and the pagination footer so the
 *   pane is a tiles-only "recent images" strip, not a second full gallery.
 * @param {'tiles'|'cards'} [props.variant] `cards` is the Gallery page: caption
 *   under a cover crop, 8 per page, prototype column counts.
 */
export default function ImageGrid({ onZoom, gridClassName, compact = false, variant = 'tiles' }) {
  const cards = variant === 'cards'
  const limit = cards ? 8 : LIMIT
  const tracks = gridClassName || (cards
    ? 'grid-cols-2 md:grid-cols-3 xl:grid-cols-4'
    : DEFAULT_GRID_CLASS)
  const { t } = useTranslation('dashboard')
  const queryClient = useQueryClient()
  const { download: downloadImage, isDownloading } = useImageDownload()

  const [page, setPage] = useState(1)
  // Live input value (keeps typing snappy); the debounced value drives the query
  // + cache key so a keystroke doesn't refetch on every character.
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [isSelectMode, setIsSelectMode] = useState(false)
  const [selectedImages, setSelectedImages] = useState(new Set())
  // Pending destructive confirm: { type: 'single', id } | { type: 'bulk' } | null
  const [pendingDelete, setPendingDelete] = useState(null)

  // The result set changes when the active filters change → snap back to page 1
  // so we never request a now-out-of-range page.
  useEffect(() => { setPage(1) }, [debouncedSearch, favoritesOnly])

  const historyKey = ['imageHistory', { page, limit, favoritesOnly, search: debouncedSearch }]

  const { data, isLoading, error } = useQuery({
    queryKey: historyKey,
    queryFn: () => imageService.getHistory({
      page,
      limit,
      // Backend reads the `favorites` query param (string 'true'/'false');
      // omit when off so it isn't sent at all.
      favorites: favoritesOnly ? 'true' : undefined,
      // Server-side ILIKE filter on prompt; omit when empty.
      search: debouncedSearch || undefined,
    }),
  })

  const favoriteMutation = useMutation({
    mutationFn: imageService.toggleFavorite,
    // Optimistically reflect the toggle so the heavy base64 page isn't refetched
    // on every click. In the Favorites-only view, un-favoriting must REMOVE the
    // row (it no longer belongs to this filtered set) and decrement the total,
    // not flip it in place; everywhere else just flip the flag.
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: historyKey })
      const previous = queryClient.getQueryData(historyKey)
      queryClient.setQueryData(historyKey, (old) => {
        if (!old?.images) return old
        const row = old.images.find(img => img._id === id)
        const becomingUnfavorite = row?.is_favorite
        if (favoritesOnly && becomingUnfavorite) {
          return {
            ...old,
            images: old.images.filter(img => img._id !== id),
            total: Math.max(0, (old.total || 0) - 1),
          }
        }
        return {
          ...old,
          images: old.images.map(img =>
            img._id === id ? { ...img, is_favorite: !img.is_favorite } : img
          ),
        }
      })
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) queryClient.setQueryData(historyKey, context.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: imageService.deleteImage,
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: historyKey })
      const previous = queryClient.getQueryData(historyKey)
      queryClient.setQueryData(historyKey, (old) => {
        if (!old?.images) return old
        return {
          ...old,
          images: old.images.filter(img => img._id !== id),
          total: Math.max(0, (old.total || 0) - 1),
        }
      })
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) queryClient.setQueryData(historyKey, context.previous)
      toast.error(t('imageHistory.failedToDeleteImage'))
    },
    onSuccess: () => {
      toast.success(t('imageHistory.imageDeleted'))
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (ids) => imageService.bulkDelete(ids),
    onMutate: async (ids) => {
      await queryClient.cancelQueries({ queryKey: historyKey })
      const previous = queryClient.getQueryData(historyKey)
      const idSet = new Set(ids)
      queryClient.setQueryData(historyKey, (old) => {
        if (!old?.images) return old
        const removed = old.images.filter(img => idSet.has(img._id)).length
        return {
          ...old,
          images: old.images.filter(img => !idSet.has(img._id)),
          total: Math.max(0, (old.total || 0) - removed),
        }
      })
      return { previous }
    },
    onError: (_err, _ids, context) => {
      if (context?.previous) queryClient.setQueryData(historyKey, context.previous)
      toast.error(t('imageHistory.failedToDeleteSome'))
    },
    onSuccess: () => {
      setSelectedImages(new Set())
      setIsSelectMode(false)
      toast.success(t('imageHistory.imagesDeleted'))
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
    },
  })

  const toggleImageSelection = (id) => {
    setSelectedImages(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAllImages = () => {
    if (data?.images) setSelectedImages(new Set(data.images.map(img => img._id)))
  }

  const clearSelection = () => setSelectedImages(new Set())

  const exitSelectMode = () => {
    setIsSelectMode(false)
    setSelectedImages(new Set())
  }

  const handleBulkDelete = () => {
    if (selectedImages.size === 0) return
    setPendingDelete({ type: 'bulk' })
  }

  const confirmPendingDelete = () => {
    if (!pendingDelete) return
    if (pendingDelete.type === 'bulk') {
      bulkDeleteMutation.mutate(Array.from(selectedImages))
    } else if (pendingDelete.type === 'single') {
      deleteMutation.mutate(pendingDelete.id)
    }
    setPendingDelete(null)
  }

  const getImageSettings = useCallback((image) => {
    const settings = []
    if (image.aspect_ratio) settings.push(image.aspect_ratio)
    else if (image.settings?.aspect_ratio) settings.push(image.settings.aspect_ratio)
    return settings.join(' • ')
  }, [])

  // Search + favorites are now server-side filters, so the page payload IS the
  // filtered set — render it directly (no client-side narrowing).
  const images = data?.images || []
  const totalImages = data?.total || 0
  const totalPages = Math.ceil(totalImages / limit)
  const rangeFrom = totalImages ? (page - 1) * limit + 1 : 0
  const rangeTo = Math.min(page * limit, totalImages)

  // After a delete/bulk-delete empties the current page (and we're not on the
  // first), step back so the user lands on a populated page rather than a void.
  useEffect(() => {
    if (!isLoading && !error && images.length === 0 && page > 1) {
      setPage(p => Math.max(1, p - 1))
    }
  }, [isLoading, error, images.length, page])

  return (
    <div className="space-y-4">
      {/* Toolbar — search + favorites + select-mode controls. Hidden in the
          compact side-pane variant (glance-only, no second search/select). */}
      {!compact && (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-foreground-tertiary" />
            <Input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t(cards ? 'gallery.searchPlaceholder' : 'imageHistory.searchPlaceholder')}
              aria-label={t(cards ? 'gallery.searchPlaceholder' : 'imageHistory.searchPlaceholder')}
              className="ps-10 pe-9"
            />
            {search && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSearch('')}
                aria-label={t('imageHistory.clear')}
                title={t('imageHistory.clear')}
                className="absolute end-1.5 top-1/2 -translate-y-1/2 h-7 w-7"
              >
                <X className="h-4 w-4 text-foreground-tertiary" />
              </Button>
            )}
          </div>

          {/* Segmented All | Favorites control — canonical segmented filter:
              1px line + radius11 + pad4 hover-bg container; active = surface
              fill + small shadow; inactive = foreground-secondary. */}
          <div className="flex items-center gap-1 p-1 rounded-[11px] border border-border bg-background-tertiary shrink-0">
            <button
              type="button"
              onClick={() => setFavoritesOnly(false)}
              aria-pressed={!favoritesOnly}
              className={cn(
                'flex items-center justify-center px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                !favoritesOnly
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-foreground-secondary hover:text-foreground'
              )}
            >
              {t('imageHistory.all')}
            </button>
            <button
              type="button"
              onClick={() => setFavoritesOnly(true)}
              aria-pressed={favoritesOnly}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                favoritesOnly
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-foreground-secondary hover:text-foreground'
              )}
            >
              <Heart className={cn('h-3.5 w-3.5', favoritesOnly && 'fill-current text-accent')} />
              {t('imageHistory.favorites')}
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 flex-wrap">
          <span className="text-sm text-foreground-tertiary">
            {t('imageHistory.imagesCount', { count: totalImages, display: fmtNumber(totalImages) })}
          </span>

          <div className="flex items-center gap-2">
            {isSelectMode && (
              <>
                <Button variant="secondary" size="sm" onClick={selectAllImages}>
                  {t('imageHistory.selectAll')}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={clearSelection}
                  disabled={selectedImages.size === 0}
                >
                  {t('imageHistory.clear')}
                </Button>
                {selectedImages.size > 0 && (
                  <>
                    <span className="text-sm text-foreground-secondary">
                      {t('imageHistory.selected', { count: selectedImages.size })}
                    </span>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={handleBulkDelete}
                      disabled={bulkDeleteMutation.isPending}
                    >
                      {bulkDeleteMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                      {t('imageHistory.delete')}
                    </Button>
                  </>
                )}
              </>
            )}
            <Button
              variant={isSelectMode ? 'default' : 'secondary'}
              size="sm"
              onClick={isSelectMode ? exitSelectMode : () => setIsSelectMode(true)}
            >
              {isSelectMode ? (
                <>
                  <X className="h-4 w-4" />
                  {t('imageHistory.cancel')}
                </>
              ) : (
                <>
                  <CheckSquare className="h-4 w-4" />
                  {t('imageHistory.select')}
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
      )}

      {/* Grid / states */}
      {isLoading && (
        <div
          className={cn('grid', cards ? 'gap-3' : 'gap-4', tracks)}
          role="status"
          aria-label={t('imageHistory.loadingImages')}
        >
          {Array.from({ length: limit }).map((_, i) => (
            <Skeleton key={i} className="aspect-square w-full" />
          ))}
        </div>
      )}

      {error && !isLoading && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <p className="text-foreground-secondary mb-2">{t('imageHistory.failedToLoad')}</p>
            <Button
              variant="link"
              size="sm"
              onClick={() => queryClient.refetchQueries({ queryKey: ['imageHistory'] })}
            >
              {t('imageHistory.tryAgain')}
            </Button>
          </div>
        </div>
      )}

      {!isLoading && !error && images.length === 0 && (
        debouncedSearch ? (
          <EmptyState
            icon={ImageIcon}
            title={t('imageHistory.noMatchingImages')}
            description={t('imageHistory.tryDifferentQuery')}
          />
        ) : favoritesOnly ? (
          <EmptyState
            icon={ImageIcon}
            title={t('imageHistory.noFavoriteImages')}
            description={t('imageHistory.markFavoritesHere')}
          />
        ) : (
          <EmptyState
            icon={ImageIcon}
            title={t('imageEmptyState.title')}
            description={t('imageHistory.generateInStudio')}
          />
        )
      )}

      {!isLoading && !error && images.length > 0 && (
        <>
          <div className={cn('grid', cards ? 'gap-3' : 'gap-4', tracks)}>
            {images.map((image) => (
              <ImageGridTile
                key={image._id}
                image={image}
                cards={cards}
                isSelectMode={isSelectMode}
                isSelected={selectedImages.has(image._id)}
                onSelectToggle={() => toggleImageSelection(image._id)}
                onZoom={() => onZoom?.(image)}
                onDownload={(loadedData) => downloadImage(image, loadedData)}
                isDownloading={isDownloading}
                onFavorite={() => favoriteMutation.mutate(image._id)}
                onDelete={() => setPendingDelete({ type: 'single', id: image._id })}
                getImageSettings={getImageSettings}
                t={t}
              />
            ))}
          </div>

          {!compact && cards && totalImages > 0 && (
            <div className="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
              <div className="text-[11px] text-foreground-tertiary">
                {totalPages <= 1
                  ? t('imageHistory.imagesCount', { count: totalImages, display: fmtNumber(totalImages) })
                  : t('gallery.range', {
                    from: fmtNumber(rangeFrom),
                    to: fmtNumber(rangeTo),
                    total: fmtNumber(totalImages),
                  })}
              </div>
              {totalPages > 1 && (
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    aria-label={t('imageHistory.prevPage')}
                    className="h-8 w-8"
                  >
                    <ChevronLeft className="h-4 w-4 rtl:rotate-180" />
                  </Button>
                  <span className="px-2 text-xs text-foreground-secondary">
                    {t('imageHistory.pageOf', { page: fmtNumber(page), total: fmtNumber(totalPages) })}
                  </span>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    aria-label={t('imageHistory.nextPage')}
                    className="h-8 w-8"
                  >
                    <ChevronRight className="h-4 w-4 rtl:rotate-180" />
                  </Button>
                </div>
              )}
            </div>
          )}

          {!compact && !cards && totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <Button
                variant="outline"
                size="icon"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                aria-label={t('imageHistory.prevPage')}
                title={t('imageHistory.prevPage')}
                className="h-9 w-9 rtl:rotate-180"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-sm text-foreground-secondary px-4">
                {t('imageHistory.pageOf', { page: fmtNumber(page), total: fmtNumber(totalPages) })}
              </span>
              <Button
                variant="outline"
                size="icon"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                aria-label={t('imageHistory.nextPage')}
                title={t('imageHistory.nextPage')}
                className="h-9 w-9 rtl:rotate-180"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </>
      )}

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => { if (!open) setPendingDelete(null) }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingDelete?.type === 'bulk'
                ? t('imageHistory.deleteSelectedConfirm.title')
                : t('imageHistory.deleteImageConfirm.title')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete?.type === 'bulk'
                ? t('imageHistory.deleteSelectedConfirm.message', { count: selectedImages.size })
                : t('imageHistory.deleteImageConfirm.message')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {pendingDelete?.type === 'bulk'
                ? t('imageHistory.deleteSelectedConfirm.cancel')
                : t('imageHistory.deleteImageConfirm.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmPendingDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {pendingDelete?.type === 'bulk'
                ? t('imageHistory.deleteSelectedConfirm.confirm')
                : t('imageHistory.deleteImageConfirm.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function ImageGridTile({
  image, cards = false, isSelectMode, isSelected, onSelectToggle, onZoom,
  onDownload, isDownloading, onFavorite, onDelete, getImageSettings, t,
}) {
  // Track the tile's loaded payload so its download button can reuse it without
  // a second fetch (the by-id query is also cached under ['image', id]).
  const [loadedData, setLoadedData] = useState(image.image_data || null)

  if (cards) {
    const model = prettifyModelName(image.model_id || image.model || '')
    const when = fmtDistanceToNowSafe(image.created_at)
    return (
      <button
        type="button"
        onClick={isSelectMode ? onSelectToggle : onZoom}
        className={cn(
          'group overflow-hidden rounded-[18px] bg-background-secondary text-start ring-1 ring-border',
          'shadow-[0_10px_28px_-14px_rgb(15_23_42/0.14)] dark:shadow-none',
          isSelectMode && isSelected && 'ring-2 ring-accent',
        )}
      >
        <div className="relative aspect-square overflow-hidden bg-background-tertiary">
          <LazyImageTile
            id={image._id}
            fallbackData={image.image_data}
            thumb={image.thumb}
            onLoaded={setLoadedData}
            alt={image.prompt?.slice(0, 120) || t('imageHistory.imageAlt')}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.03]"
          />
          {isSelectMode && (
            <div className="absolute top-2 start-2 rounded-md bg-background-secondary p-0.5">
              {isSelected
                ? <CheckSquare className="h-6 w-6 text-accent" />
                : <Square className="h-6 w-6 text-foreground-secondary" />}
            </div>
          )}
          {image.is_favorite && !isSelectMode && (
            <span className="absolute top-2 start-2 grid h-6 w-6 place-items-center rounded-md bg-background-secondary/90">
              <Heart className="h-3.5 w-3.5 fill-current text-destructive" />
            </span>
          )}
        </div>
        <div className="p-3">
          <div className="line-clamp-2 text-[13px] font-semibold leading-5 text-foreground">
            {image.prompt}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-foreground-tertiary">
            {model && <span dir="ltr">{model}</span>}
            {model && when && <span>·</span>}
            {when && <span>{when}</span>}
          </div>
        </div>
      </button>
    )
  }

  return (
    <div
      className={cn(
        'relative group bg-background-tertiary rounded-xl overflow-hidden aspect-square cursor-pointer',
        'transition-all duration-200 ease-out hover:-translate-y-[3px] hover:shadow-[0_12px_28px_-12px_hsl(var(--accent)/0.45)]',
        isSelectMode && isSelected && 'ring-2 ring-accent'
      )}
      onClick={isSelectMode ? onSelectToggle : onZoom}
    >
      <LazyImageTile
        id={image._id}
        fallbackData={image.image_data}
        thumb={image.thumb}
        onLoaded={setLoadedData}
        alt={image.prompt?.slice(0, 120) || t('imageHistory.imageAlt')}
        loading="lazy"
        decoding="async"
        className="w-full h-full object-contain"
      />

      {isSelectMode && (
        // Always visible (never hover-gated) so touch users can tell what's
        // selectable; a dark backing chip keeps the glyph legible over bright
        // images.
        <div className="absolute top-2 start-2 rounded-md bg-black/45 p-0.5 backdrop-blur-sm">
          {isSelected ? (
            <CheckSquare className="h-6 w-6 text-accent" />
          ) : (
            <Square className="h-6 w-6 text-white" />
          )}
        </div>
      )}

      {!isSelectMode && (
        // Overlay reveals on hover, on keyboard focus of any inner button
        // (focus-within), and is always visible on touch/coarse-pointer devices.
        <div className="absolute inset-0 bg-black/60 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100">
          <div className="absolute bottom-0 start-0 end-0 p-2 bg-black/70">
            <p className="text-xs text-white truncate">{image.prompt}</p>
            <p className="text-xs text-white/70" dir="ltr">{getImageSettings(image)}</p>
          </div>
          <div className="absolute top-2 end-2 flex gap-1">
            <button
              type="button"
              disabled={isDownloading}
              onClick={(e) => { e.stopPropagation(); onDownload(loadedData) }}
              className="p-1.5 bg-white/20 rounded-lg hover:bg-white/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black/60 transition-colors disabled:opacity-50 disabled:pointer-events-none"
              aria-label={isDownloading ? t('imageHistory.downloading') : t('imageHistory.download')}
              aria-busy={isDownloading || undefined}
              title={isDownloading ? t('imageHistory.downloading') : t('imageHistory.download')}
            >
              {isDownloading
                ? <Loader2 className="h-4 w-4 text-white animate-spin" />
                : <Download className="h-4 w-4 text-white" />}
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onFavorite() }}
              className="p-1.5 bg-white/20 rounded-lg hover:bg-white/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black/60 transition-colors"
              aria-pressed={!!image.is_favorite}
              aria-label={image.is_favorite ? t('imageHistory.unfavorite') : t('imageHistory.favorite')}
              title={image.is_favorite ? t('imageHistory.unfavorite') : t('imageHistory.favorite')}
            >
              <Heart
                className={cn(
                  'h-4 w-4',
                  image.is_favorite ? 'text-destructive fill-current' : 'text-white'
                )}
              />
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDelete() }}
              className="p-1.5 bg-white/20 rounded-lg hover:bg-white/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black/60 transition-colors"
              aria-label={t('imageHistory.delete')}
              title={t('imageHistory.delete')}
            >
              <Trash2 className="h-4 w-4 text-white" />
            </button>
          </div>
        </div>
      )}

      {image.is_favorite && !isSelectMode && (
        <div className="absolute top-2 start-2 p-1 bg-black/40 rounded">
          <Heart className="h-3 w-3 text-destructive fill-current" />
        </div>
      )}
    </div>
  )
}

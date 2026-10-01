import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Download, Heart, Copy, Loader2,
  AlertCircle, X,
} from 'lucide-react'
import { imageService } from '../../services/imageService'
import LazyImageTile from './LazyImageTile'
import ImageStudioEmptyState from './ImageStudioEmptyState'
import { CostValue } from '@/components/ui/CostValue'
import { CreditValue } from '@/components/ui/CreditValue'
import { canSeePrice } from '@/utils/money'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/tooltip'
import { cn } from '../../utils/cn'
import { fmtNumber } from '../../utils/persianLocale'
import { fmtDate } from '../../utils/dateLocale'

const THREADS_KEY = ['imageThreads']

/**
 * State machine for the conversational image-edit Generate tab.
 *
 * Owns: the thread list, the active thread + its ordered turns, the optimistic
 * turn (a pending tile inserted BEFORE the request and swapped for the real
 * image on success — mirrors the chat optimistic-first pattern), the inline
 * stream error, and the right-pane focused image.
 *
 * CONVERSATION BY DEFAULT — there is no explicit "edit" arming. The `focused`
 * image (the one in the canvas) IS the base for the next turn: every follow-up
 * prompt edits it (sent as `parent_image_id`). Selecting a filmstrip version
 * rebases to it; an explicit New image (or starting a fresh thread) clears the
 * focus → the next prompt generates from scratch. A Variation re-rolls the same
 * prompt with NO parent (`generate({ noParent: true })`).
 *
 * The composer form (prompt / style / aspect / negative / refs / model) and the
 * DLP/budget gates live in the page; the page calls {@link generate} with the
 * already-scanned payload. The hook forwards `conversation_id` (active thread,
 * omitted to start a new one), `parent_image_id` (the focused image unless
 * `noParent`), and `config_id` (when an image assistant drives the thread).
 *
 * @param {object} opts
 * @param {string|null} [opts.configId] Image-assistant id bound to NEW threads.
 */
export function useImageThread({ configId = null } = {}) {
  const queryClient = useQueryClient()

  // null = brand-new (unsaved) thread; otherwise the active thread's id.
  const [activeId, setActiveId] = useState(null)
  // Optimistic + confirmed turns for the active thread, oldest → newest. Each
  // turn: { tempId|_id, prompt, negative_prompt, image|null, pending, failed }.
  const [turns, setTurns] = useState([])
  // The image currently large in the right pane (a confirmed turn's image). This
  // doubles as the edit base: the next generate sends it as parent_image_id
  // unless noParent. null = fresh generate (new thread / New image).
  const [focused, setFocused] = useState(null)
  // Inline error banner copy (null = none). Never a toast — matches chat.
  const [streamError, setStreamError] = useState(null)
  const [isGenerating, setIsGenerating] = useState(false)

  // List of the caller's threads (cover thumbs only, newest activity first).
  const threadsQuery = useQuery({
    queryKey: THREADS_KEY,
    queryFn: () => imageService.getThreads({ page: 1, limit: 50 }),
    staleTime: 30_000,
  })

  // Load a thread's turns when one is selected.
  const threadQuery = useQuery({
    queryKey: ['imageThread', activeId],
    queryFn: () => imageService.getThread(activeId),
    enabled: !!activeId,
  })

  // Sync confirmed turns from the server when the active thread loads/changes.
  // Guarded by a ref so an in-flight optimistic turn isn't clobbered by a
  // background refetch.
  // EDGE CASE: the {id,count} signature only re-syncs on a turn-COUNT change —
  // an in-place edit of an existing turn (same count) won't re-pull. Acceptable
  // today (turns are append-only) but revisit if turns become mutable.
  const lastSyncedRef = useRef({ id: null, count: -1 })
  const serverImages = threadQuery.data?.images
  useEffect(() => {
    if (!activeId) return
    if (!serverImages) return
    const sig = { id: activeId, count: serverImages.length }
    if (lastSyncedRef.current.id === sig.id && lastSyncedRef.current.count === sig.count) {
      return
    }
    lastSyncedRef.current = sig
    // Stable order: chronological, then batch_index so an N-variant turn keeps
    // its variants adjacent and in order (server may not pre-sort within a batch).
    const ordered = [...serverImages].sort((a, b) => {
      const ta = a.created_at || ''
      const tb = b.created_at || ''
      if (ta !== tb) return ta < tb ? -1 : 1
      return (a.settings?.batch_index ?? 0) - (b.settings?.batch_index ?? 0)
    })
    setTurns(ordered.map((img) => ({
      _id: img._id,
      prompt: img.prompt,
      negative_prompt: img.negative_prompt,
      image: img,
      pending: false,
      failed: false,
    })))
    // Focus the newest confirmed image of the loaded thread.
    const newest = ordered[ordered.length - 1]
    if (newest) setFocused(newest)
  }, [activeId, serverImages])

  const activeThread = threadQuery.data?.conversation || null

  const selectThread = useCallback((id) => {
    setStreamError(null)
    setFocused(null)
    setTurns([])
    lastSyncedRef.current = { id: null, count: -1 }
    setActiveId(id)
  }, [])

  const startNewThread = useCallback(() => {
    setStreamError(null)
    setFocused(null)
    setTurns([])
    lastSyncedRef.current = { id: null, count: -1 }
    setActiveId(null)
  }, [])

  // Open an existing image's thread (Continue editing from the gallery).
  const openImageThread = useCallback((image) => {
    setStreamError(null)
    setFocused(null)
    setTurns([])
    lastSyncedRef.current = { id: null, count: -1 }
    if (image?.conversation_id) {
      // Existing thread — load it; the newest turn becomes the focus (= base).
      setActiveId(image.conversation_id)
    } else {
      // Orphan image — start a fresh thread focused on this image so the next
      // generate continues from it (focus IS the edit base).
      setActiveId(null)
      setFocused(image)
    }
  }, [])

  /**
   * Optimistic-first handoff (mirrors chat's useChatStream): insert the pending
   * tile + flip isGenerating the INSTANT the user clicks, BEFORE the page's DLP
   * pre-flight await. Returns the tempId the page threads back into {@link
   * generate}. If the scan blocks/cancels, the page calls {@link discardTurn}.
   * Keeping this ahead of DLP is what removes the dead "nothing happens" window.
   *
   * @param {{prompt:string, negative_prompt?:string, aspectRatio?:string}} turn
   * @returns {string} tempId
   */
  const prepareTurn = useCallback(({ prompt, negative_prompt = '', aspectRatio = '1:1' }) => {
    const tempId = `tmp_${Date.now()}`
    setStreamError(null)
    setIsGenerating(true)
    setTurns((prev) => [...prev, {
      tempId,
      prompt,
      negative_prompt,
      aspectRatio: aspectRatio || '1:1',
      image: null,
      pending: true,
      failed: false,
    }])
    return tempId
  }, [])

  // Roll back a prepared turn (DLP blocked / cancelled). Flow is single-flight
  // (canSend blocks while generating) so clearing isGenerating is safe.
  const discardTurn = useCallback((tempId) => {
    setTurns((prev) => prev.filter((tr) => tr.tempId !== tempId))
    setIsGenerating(false)
  }, [])

  /**
   * Append a turn: optimistic prompt + pending tile FIRST, then the request,
   * then swap in the real image (or mark failed for the inline retry banner).
   *
   * The next turn edits the FOCUSED image by default (sent as parent_image_id);
   * pass `{ noParent: true }` for a fresh generate (first turn / Variation).
   *
   * @param {object} payload Already-scanned generate body (prompt, model,
   *   negative_prompt, aspect_ratio, input_images, dlp_* ...).
   * @param {object} [opts]
   * @param {boolean} [opts.noParent] Skip parent chaining (fresh generate).
   * @param {string} [opts.tempId] Reuse a tile already inserted by prepareTurn
   *   (optimistic-first). Omit to insert one now (legacy callers).
   * @param {number} [opts.count] Expected variant count (n). Reserved for an
   *   optional multi-pending-tile UX; the response's images[] is authoritative.
   */
  const generate = useCallback(async (payload, { noParent = false, tempId: preparedId, count = 1 } = {}) => {
    const tempId = preparedId || `tmp_${Date.now()}`
    const np = payload.negative_prompt || ''
    if (!preparedId) {
      // No prepared tile (legacy path) — insert it now.
      setStreamError(null)
      setIsGenerating(true)
      setTurns((prev) => [...prev, {
        tempId,
        prompt: payload.prompt,
        negative_prompt: np,
        aspectRatio: payload.aspect_ratio || '1:1',
        image: null,
        pending: true,
        failed: false,
      }])
    }
    // Multi-variant UX: when n>1 is known up front, insert the extra n-1 pending
    // tiles now so the filmstrip shows N skeletons immediately. They're swapped
    // for variants[1..] on success (or cleared if the backend returns fewer).
    const extraTempIds = []
    if (count > 1) {
      for (let i = 1; i < count; i++) extraTempIds.push(`${tempId}_v${i}`)
      setTurns((prev) => [
        ...prev,
        ...extraTempIds.map((id) => ({
          tempId: id,
          prompt: payload.prompt,
          negative_prompt: np,
          aspectRatio: payload.aspect_ratio || '1:1',
          image: null,
          pending: true,
          failed: false,
        })),
      ])
    }

    try {
      const body = {
        ...payload,
        conversation_id: activeId || undefined,
        // Conversation by default: the focused image is the edit base unless
        // this is a fresh generate (first turn → focused null, or Variation).
        parent_image_id: noParent ? undefined : (focused?._id || undefined),
        config_id: configId || undefined,
      }
      const data = await imageService.generateImage(body)
      // N-variant response: data.images[] holds every variant of this turn (1+);
      // data.image / data.image_data are the FIRST variant (back-compat). Attach
      // the first variant's full base64 so the tile/right-pane paint instantly.
      const variants = Array.isArray(data.images) && data.images.length > 0
        ? data.images
        : (data.image ? [data.image] : [])
      const firstImage = variants[0]
        ? { ...variants[0], image_data: variants[0].image_data || data.image_data }
        : null
      const toTurn = (img) => ({
        _id: img._id,
        prompt: img.prompt,
        negative_prompt: img.negative_prompt,
        image: img,
        pending: false,
        failed: false,
      })
      const extraVariants = variants.slice(1)
      setTurns((prev) => {
        // Swap the optimistic tile → first variant. Extra variants reuse the
        // pre-inserted pending tiles (extraTempIds[i] ↔ extraVariants[i]) when
        // present, else append (e.g. backend returned MORE than n requested).
        let next = prev.map((tr) => {
          if (tr.tempId === tempId && firstImage) return toTurn(firstImage)
          const slot = extraTempIds.indexOf(tr.tempId)
          if (slot >= 0 && extraVariants[slot]) return toTurn(extraVariants[slot])
          return tr
        })
        // Drop any unfilled extra pending tiles (backend returned fewer than n).
        next = next.filter((tr) => !(extraTempIds.includes(tr.tempId) && tr.pending))
        // Variants with no pre-inserted slot → append.
        const overflow = extraVariants.slice(extraTempIds.length).map(toTurn)
        return overflow.length ? [...next, ...overflow] : next
      })
      // The first variant becomes the next base.
      const realImage = firstImage
      if (realImage) setFocused(realImage)

      // Adopt the (possibly new) thread id + refresh the list cover/order.
      const newId = data.conversation_id
      if (newId && newId !== activeId) {
        lastSyncedRef.current = { id: newId, count: -1 }
        setActiveId(newId)
      }
      queryClient.invalidateQueries({ queryKey: THREADS_KEY })
      // The gallery + this thread's turns changed server-side.
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
      if (newId) queryClient.invalidateQueries({ queryKey: ['imageThread', newId] })

      return { ok: true, image: realImage, conversation_id: newId }
    } catch (error) {
      // Mark the optimistic tile (+ any pre-inserted variant tiles) failed +
      // surface an inline banner (never a toast). The page decides whether the
      // error is budget/DLP first.
      const failedIds = new Set([tempId, ...extraTempIds])
      setTurns((prev) => prev.map((tr) =>
        failedIds.has(tr.tempId) ? { ...tr, pending: false, failed: true } : tr
      ))
      return { ok: false, error }
    } finally {
      setIsGenerating(false)
    }
  }, [activeId, focused, configId, queryClient])

  const setBanner = useCallback((msg) => setStreamError(msg || null), [])

  // Single source of truth for a turn's 1-based version number. Both the canvas
  // caption and the filmstrip badge derive their "Version N" from this so they
  // can never disagree; the page reuses it for the composer's base-version hint.
  const versionOf = useCallback((imageId) => {
    if (!imageId) return null
    const idx = turns.findIndex((tr) => tr.image && tr.image._id === imageId)
    return idx >= 0 ? idx + 1 : null
  }, [turns])

  // Flip is_favorite on the focused canvas image + matching filmstrip turn.
  // Invalidating ['imageThread'] does NOT resync: the effect keys on turn
  // *count*, and a favorite toggle does not change count — so without this
  // the canvas heart stays stale while the history grid (separate cache) updates.
  const patchFavorite = useCallback((imageId, isFavorite) => {
    if (!imageId) return
    setFocused((prev) => (
      prev?._id === imageId ? { ...prev, is_favorite: isFavorite } : prev
    ))
    setTurns((prev) => prev.map((tr) => (
      tr.image?._id === imageId
        ? { ...tr, image: { ...tr.image, is_favorite: isFavorite } }
        : tr
    )))
  }, [])

  return {
    threads: threadsQuery.data?.threads || [],
    threadsLoading: threadsQuery.isLoading,
    activeId,
    activeThread,
    threadLoading: !!activeId && threadQuery.isLoading,
    turns,
    focused,
    setFocused,
    streamError,
    setBanner,
    isGenerating,
    selectThread,
    startNewThread,
    openImageThread,
    prepareTurn,
    discardTurn,
    generate,
    versionOf,
    patchFavorite,
  }
}

/**
 * Image-first Generate-tab body: a large hero CANVAS over a horizontal
 * FILMSTRIP of the session's versions. No studio sidebar — sessions live in the
 * page header (SessionSwitcher); the composer (pill) sits below. This owns no
 * form state; all generate plumbing flows through {@link useImageThread}.
 *
 * Canvas    — the focused version large + a floating action cluster
 *             (Download · Favorite · Variation). Generating → spinner; empty →
 *             CTA. The focused version's prompt shows as a muted caption beneath.
 *             The image is the MEDIUM preview rendition (~1024px), fetched on
 *             demand, with the 256px thumb as the instant placeholder — sharp
 *             without pushing full base64 into the DOM. There is no explicit
 *             "Edit" — the focused image IS the next prompt's edit base.
 * Filmstrip — oldest→newest thumb buttons; selected (= the base) gets the accent
 *             ring + a "base" badge, pending = spinner, failed = error tile.
 *             Click → focus/rebase in the canvas. Plain scroll row (no
 *             react-virtual / auto-animate).
 */
export default function ImageThread({
  thread,
  onDownload,
  isDownloading = false,
  onFavorite,
  onVariation,
  onPickPrompt,
  onPickTemplate,
}) {
  const { t } = useTranslation('dashboard')
  const { user } = useAuth()
  const { workspaces } = useWorkspace()
  // Tier gate (utils/money): admin / team-owner sees the $ price chip; everyone
  // else sees a Polymind Credits chip. Never leak a $ figure to a normal user.
  const priceVisible = canSeePrice(user, workspaces)

  const {
    threadLoading,
    turns, focused, setFocused,
    streamError, setBanner, isGenerating,
    versionOf,
  } = thread

  // Medium (~1024px) rendition for the hero canvas — sharp, on demand, cached
  // forever (immutable per image). The 256px thumb paints instantly while it
  // loads; full base64 NEVER touches the canvas.
  const previewQuery = useQuery({
    queryKey: ['imagePreview', focused?._id],
    queryFn: () => imageService.getImagePreview(focused._id),
    enabled: !!focused?._id,
    staleTime: Infinity,
  })
  const canvasSrc = previewQuery.data?.preview || focused?.thumb

  // 1-based version index of the focused turn (for the caption "Version N") —
  // single-sourced through the hook's versionOf so caption + filmstrip agree.
  const focusedVersion = versionOf(focused?._id)
  const empty = turns.length === 0 && !isGenerating && !threadLoading
  const pendingTurn = turns.find((turn) => turn.pending)
  const generating = isGenerating || !!pendingTurn
  const showFrame = generating || threadLoading

  return (
    <div className="flex flex-col min-h-0 h-full">
      {streamError && (
        <div role="alert" className="mb-3 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            {typeof streamError === 'string' ? (
              <p>{streamError}</p>
            ) : (
              <>
                <p className="font-medium">{streamError.title}</p>
                {streamError.description && (
                  <p className="mt-0.5 text-xs leading-5 text-destructive/90">{streamError.description}</p>
                )}
              </>
            )}
          </div>
          <button
            onClick={() => setBanner(null)}
            className="p-0.5 rounded hover:bg-destructive/20"
            aria-label={t('imageHistory.clear')}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* CANVAS — the hero. The focused version dominates the screen. */}
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center">
        <div className="relative flex-1 min-h-0 w-full flex items-center justify-center">
          {showFrame ? (
            <GeneratingFrame
              aspect={pendingTurn?.aspectRatio || '1:1'}
              label={generating ? t('imageStudio.generating') : t('imageStudio.loadingSession')}
              showProgress={generating}
            />
          ) : focused ? (
            <>
              {/* MEDIUM preview (never full base64): thumb placeholder swaps to
                  the ~1024px rendition when the query resolves — no blank flash. */}
              <img
                src={canvasSrc}
                alt={focused.prompt}
                decoding="async"
                /* `max-h-full` (NOT `max-h-[60vh]`): a viewport unit decouples
                   the image from its `flex-1 min-h-0` slot, so on short layouts
                   the image overflowed its box and bled over the filmstrip
                   sibling. `max-h-full` clamps it to the slot. */
                className="max-h-full max-w-full rounded-xl object-contain shadow-lg"
              />

            </>
          ) : (
            // Teaching empty state — its own scrollable region (the hero
            // template gallery can run tall), filling the centered canvas slot.
            <div className="h-full w-full overflow-y-auto">
              <ImageStudioEmptyState
                onPickPrompt={onPickPrompt}
                onPickTemplate={onPickTemplate}
                disabled={isGenerating}
              />
            </div>
          )}
        </div>

        {/* Action bar — centered UNDER the image. It used to float absolutely
            at the canvas container's corner, but `object-contain` centers the
            image inside a full-width slot, so on narrow images the cluster
            hovered alone in empty space where nobody saw it. */}
        {focused && !empty && !showFrame && (
          <div className="mt-3 flex items-center gap-1 rounded-full bg-background-elevated p-1 shadow-md border border-border">
            <CanvasAction
              label={isDownloading ? t('imageHistory.downloading') : t('imageHistory.download')}
              onClick={() => onDownload?.(focused)}
              disabled={isDownloading}
            >
              {isDownloading
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <Download className="h-4 w-4" />}
            </CanvasAction>
            <CanvasAction
              label={focused.is_favorite ? t('imageHistory.unfavorite') : t('imageHistory.favorite')}
              onClick={() => onFavorite?.(focused)}
            >
              <Heart className={cn('h-4 w-4', focused.is_favorite && 'fill-current text-destructive')} />
            </CanvasAction>
            <CanvasAction
              label={t('imageStudio.variation')}
              onClick={() => onVariation?.(focused)}
            >
              <Copy className="h-4 w-4" />
            </CanvasAction>
          </div>
        )}

        {/* Version + time isolated from the prompt so mixed FA/EN/digits
            don't reorder inside one bidi paragraph. */}
        {focused && !empty && !showFrame && (
          <div className="mt-2 max-w-[768px] w-full px-4 flex flex-col items-center gap-1">
            {(focusedVersion != null || focused.created_at) && (
              <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-0.5 text-xs text-foreground-tertiary">
                {focusedVersion != null && (
                  <bdi className="font-medium text-foreground-secondary tabular-nums">
                    {t('imageStudio.versionN', { n: focusedVersion })}
                  </bdi>
                )}
                {focused.created_at && (
                  <time dateTime={focused.created_at} dir="ltr" className="tabular-nums">
                    {fmtDate(new Date(focused.created_at), 'PPpp')}
                  </time>
                )}
              </div>
            )}
            {focused.prompt && (
              <p dir="auto" className="text-center text-sm text-foreground-tertiary line-clamp-2">
                {focused.prompt}
              </p>
            )}
          </div>
        )}

        {/* Per-image tokens + price/credits chip — muted, LTR for numerals. For
            an N-variant turn the per-row figure is the per-variant share; the
            batch total (when the backend reports it) is appended for context.
            Price viewers see $ cost; everyone else sees Polymind Credits. */}
        {focused && !empty && !showFrame && (focused.cost_usd != null || focused.credits != null || focused.tokens?.total != null) && (() => {
          // Batch total in the viewer's tier: $ for price viewers, else credits.
          const batchTotalCost = focused.metadata?.batch?.total_cost_usd
          const batchTotalCredits = focused.credits_total ?? focused.metadata?.batch?.total_credits
          const batchN = focused.settings?.batch_n ?? 1
          const moneyShown = priceVisible ? focused.cost_usd != null : focused.credits != null
          const batchTotalShown = priceVisible ? batchTotalCost != null : batchTotalCredits != null
          return (
            <p
              dir="ltr"
              className="mt-1 flex items-center justify-center gap-2 text-xs text-foreground-tertiary tabular-nums"
            >
              {focused.tokens?.total != null && (
                <span>{t('imageHistory.tokensN', { n: fmtNumber(focused.tokens.total) })}</span>
              )}
              {moneyShown && focused.tokens?.total != null && <span aria-hidden>·</span>}
              {moneyShown && (priceVisible ? (
                <CostValue usd={focused.cost_usd} />
              ) : (
                <CreditValue credits={focused.credits} />
              ))}
              {batchN > 1 && batchTotalShown && (
                <>
                  <span aria-hidden>·</span>
                  <span className="inline-flex items-center gap-1">
                    {t('imageStudio.batchTotalCost')}{' '}
                    {priceVisible ? (
                      <CostValue usd={batchTotalCost} />
                    ) : (
                      <CreditValue credits={batchTotalCredits} />
                    )}
                  </span>
                </>
              )}
            </p>
          )
        })()}
      </div>

      {/* FILMSTRIP — horizontal scroll of the session's versions. */}
      {(turns.length > 0 || isGenerating) && (
        <div className="shrink-0 mt-3 flex snap-x gap-2 overflow-x-auto pb-2">
          {turns.map((turn, i) => (
            <FilmstripItem
              key={turn._id || turn.tempId}
              turn={turn}
              // Single-sourced version: confirmed turns resolve through the
              // hook's versionOf; pending/failed tiles (no image yet) fall back
              // to their position so the spinner/error tile still numbers.
              version={versionOf(turn.image?._id) ?? (i + 1)}
              isFocused={!!turn.image && focused?._id === turn.image._id}
              onSelect={() => turn.image && setFocused(turn.image)}
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function cssAspect(ratio) {
  const match = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(ratio || '')
  if (!match || Number(match[2]) === 0) return '1 / 1'
  return `${match[1]} / ${match[2]}`
}

function GeneratingFrame({ aspect, label, showProgress }) {
  const css = cssAspect(aspect)
  const [w, h] = css.split('/').map((n) => Number(n.trim()))
  const portrait = h > w
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!showProgress) return undefined
    const started = Date.now()
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [showProgress])

  return (
    <div className="flex h-full w-full items-center justify-center" aria-busy="true" aria-live="polite">
      <div
        className={cn(
          'relative flex max-h-full max-w-full flex-col justify-end overflow-hidden rounded-xl animate-shimmer',
          portrait ? 'h-full w-auto min-w-[12rem]' : 'h-auto w-[min(100%,36rem)] min-h-48',
        )}
        style={{ aspectRatio: css }}
      >
        <div className="relative flex flex-col items-center gap-2 px-4 pb-4">
          <span className="text-sm text-foreground-secondary">{label}</span>
          {showProgress && (
            <>
              <span dir="ltr" className="text-xs tabular-nums text-foreground-tertiary">
                {fmtNumber(elapsed)}s
              </span>
              <div dir="ltr" className="h-1 w-2/3 overflow-hidden rounded-full bg-background/70">
                <div className="animate-indeterminate h-full w-1/3 rounded-full bg-accent" />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// A floating icon button over the canvas (Download / Favorite / Variation).
function CanvasAction({ label, onClick, disabled, children }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          aria-label={label}
          aria-busy={disabled || undefined}
          className={cn(
            'h-9 w-9 rounded-full flex items-center justify-center transition-colors',
            'text-foreground-secondary hover:bg-background-tertiary hover:text-foreground',
            disabled && 'pointer-events-none opacity-50',
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

// One version in the filmstrip — a square thumb button. Pending = spinner tile,
// failed = error tile, ready = the image (selected gets the accent ring).
function FilmstripItem({ turn, version, isFocused, onSelect, t }) {
  if (turn.pending) {
    return (
      <div className="h-20 w-20 shrink-0 snap-start rounded-lg bg-background-tertiary flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-foreground-tertiary" />
      </div>
    )
  }
  if (turn.failed) {
    return (
      <div className="h-20 w-20 shrink-0 snap-start rounded-lg border border-destructive/30 bg-destructive/5 flex flex-col items-center justify-center gap-0.5 text-destructive text-[10px] px-1 text-center">
        <AlertCircle className="h-4 w-4" />
        {t('imageStudio.turnFailed')}
      </div>
    )
  }
  if (!turn.image) return null

  // N-variant turn: settings.batch_n > 1 means this tile is one of a batch; the
  // k/n badge tells the user these siblings belong to a single generate.
  const batchN = turn.image.settings?.batch_n ?? 1
  const batchIndex = turn.image.settings?.batch_index
  const inBatch = batchN > 1 && batchIndex != null

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={t('imageStudio.versionN', { n: version })}
      className={cn(
        'relative h-20 w-20 shrink-0 snap-start rounded-lg overflow-hidden bg-background-tertiary transition-shadow',
        isFocused ? 'ring-2 ring-accent' : 'hover:ring-2 hover:ring-accent/40',
      )}
    >
      <LazyImageTile
        id={turn.image._id}
        fallbackData={turn.image.image_data}
        thumb={turn.image.thumb}
        alt={turn.prompt}
        loading="lazy"
        decoding="async"
        className="h-full w-full object-contain"
      />
      {/* The focused tile is the edit base — mark it so the user sees what the
          next prompt will edit. */}
      {isFocused && (
        <span className="absolute top-0.5 start-0.5 rounded bg-accent px-1 text-[9px] font-medium leading-tight text-accent-foreground">
          {t('imageStudio.baseBadge')}
        </span>
      )}
      {/* Batch k/n badge (top-end) for an N-variant turn; otherwise the plain
          version index (bottom-end). */}
      {inBatch ? (
        <span className="absolute top-0.5 end-0.5 rounded bg-black/55 px-1 text-[9px] leading-tight text-white" dir="ltr">
          {t('imageStudio.batchOf', { index: batchIndex + 1, total: batchN })}
        </span>
      ) : (
        <span className="absolute bottom-0.5 end-0.5 rounded bg-black/55 px-1 text-[9px] leading-tight text-white" dir="ltr">
          {version}
        </span>
      )}
    </button>
  )
}

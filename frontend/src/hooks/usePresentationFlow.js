import { useCallback, useEffect, useRef, useState } from 'react'
import {
  streamOutline,
  streamRender,
  savePresentation,
} from '@/services/presentationService'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'

/**
 * Stage state machine driving the presentation page:
 *   brief      — composing the topic/brief (initial + after a failed outline)
 *   outlining  — outline SSE in flight
 *   outline    — outline ready, user editing before render
 *   rendering  — render SSE in flight (imaging + pptx)
 *   ready      — .pptx file artifact available for download
 *
 * Budget (HTTP 402) is caught FIRST in every error path per the CLAUDE.md
 * contract: feed the parsed error to `handleBudgetError`; if it's a budget /
 * credit refusal the hook opens the hard-block modal and we swallow the error
 * (no generic message). Otherwise fall through to a surfaced `error` string.
 */
export const STAGE = {
  BRIEF: 'brief',
  OUTLINING: 'outlining',
  OUTLINE: 'outline',
  RENDERING: 'rendering',
  READY: 'ready',
}

const INITIAL_PROGRESS = { phase: null, done: 0, total: 0 }

export default function usePresentationFlow() {
  const [stage, setStage] = useState(STAGE.BRIEF)
  const [id, setId] = useState(null)
  const [outline, setOutline] = useState(null)
  const [progress, setProgress] = useState(INITIAL_PROGRESS)
  const [warnings, setWarnings] = useState([])
  const [file, setFile] = useState(null)
  const [error, setError] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  // Holds the active stream handle ({ abort }) so we can cancel an in-flight
  // outline/render on reset or unmount. Aborting prevents an orphaned reader
  // from writing into a stage we've already left.
  const streamRef = useRef(null)

  // Budget-first error router. Returns nothing; sets `error` only for non-budget
  // failures. `handleBudgetError` keys on the body's `code`
  // (budget_exceeded / insufficient_credits) — a 402 carries it.
  const onErr = useCallback(
    (e) => {
      if (handleBudgetError?.(e)) return // budget / credit refusal — modal shown
      const raw = String(e?.error || e?.message || 'error')
      // fetch() aborts mid-SSE (CDN idle / tab sleep) surface as Failed to fetch
      if (/failed to fetch|networkerror|network error|load failed|stream timed out/i.test(raw)) {
        setError('connection_lost')
        return
      }
      setError(raw)
    },
    [handleBudgetError],
  )

  const start = useCallback(
    (brief) => {
      streamRef.current?.abort()
      setError(null)
      setWarnings([])
      setProgress(INITIAL_PROGRESS)
      setStage(STAGE.OUTLINING)
      streamRef.current = streamOutline(brief, {
        onStatus: (st) => setProgress((prev) => ({ ...prev, ...st })),
        onWarning: (w) =>
          setWarnings((prev) => [...prev, w?.message || w?.error || String(w || '')]),
        onOutline: (d) => {
          setId(d.id)
          setOutline(d.outline)
        },
        onDone: () => setStage(STAGE.OUTLINE),
        onError: (e) => {
          onErr(e)
          setStage(STAGE.BRIEF)
        },
      })
    },
    [onErr],
  )

  const render = useCallback(
    async (editedOutline) => {
      // No deck id (outline never persisted) -> there's nothing to render and
      // POSTing to `/presentations/null/render` would 404. Bounce to OUTLINE.
      if (!id) {
        setError('no outline')
        setStage(STAGE.OUTLINE)
        return
      }
      streamRef.current?.abort()
      setError(null)
      setWarnings([])
      setProgress(INITIAL_PROGRESS)
      setFile(null)
      setStage(STAGE.RENDERING)

      // Persist the edited outline first (non-fatal — the render body also
      // carries it, so the .pptx is correct even if the save fails). A budget /
      // DLP refusal would surface on the render stream instead.
      if (id) {
        try {
          await savePresentation(id, { outline: editedOutline })
        } catch {
          /* non-fatal */
        }
      }

      streamRef.current = streamRender(
        id,
        { outline: editedOutline },
        {
          onStatus: setProgress,
          onWarning: (w) => setWarnings((prev) => [...prev, w]),
          onFile: setFile,
          onDone: () => setStage(STAGE.READY),
          onError: (e) => {
            onErr(e)
            setStage(STAGE.OUTLINE)
          },
        },
      )
    },
    [id, onErr],
  )

  const reset = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    setStage(STAGE.BRIEF)
    setId(null)
    setOutline(null)
    setFile(null)
    setWarnings([])
    setProgress(INITIAL_PROGRESS)
    setError(null)
  }, [])

  // Abort any in-flight stream on unmount so an orphaned reader can't setState
  // on an unmounted component (React warning) or pin the backend SSE worker.
  useEffect(() => () => streamRef.current?.abort(), [])

  return {
    STAGE,
    stage,
    id,
    outline,
    setOutline,
    progress,
    warnings,
    file,
    error,
    start,
    render,
    reset,
    budgetModal,
  }
}

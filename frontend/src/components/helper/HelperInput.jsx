import { useRef, useEffect, useCallback, useImperativeHandle, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { ArrowUp, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { streamHelper } from '../../services/helperService'
import { dlpService } from '../../services/dlpService'
import { useWorkspace } from '../../context/WorkspaceContext'
import { useProject } from '../../context/ProjectContext'
import DLPViolationModal from '../dlp/DLPViolationModal'
import { useBudgetBlock } from '../../hooks/useBudgetBlock'
import { cn } from '../../utils/cn'

/**
 * Composer for the helper rail.
 *
 * Textarea auto-resizes between 40px and 160px. Enter sends, Shift+Enter
 * inserts a newline. Disabled while a request is streaming.
 *
 * DLP integration mirrors the chat composer (see
 * `frontend/src/pages/chat/hooks/useChatStream.js`):
 *
 *   1. Pre-flight `POST /api/dlp/scan` BEFORE calling `streamHelper`.
 *   2. `action=allow`             -> stream directly.
 *   3. `action=warn`              -> non-blocking toast, stream.
 *   4. `action=block`             -> modal (modify, or scrub-and-send). No stream.
 *      Stale `require_confirm` / `dlp_confirm_required` is a block.
 *
 * Scan failure is non-fatal — never block the user on infra outages.
 */
export default function HelperInput({
  value,
  onChange,
  onMessageStart,
  onMessageChunk,
  onMessageComplete,
  onMessageError,
  onDlpBlock,
  streaming,
  disabled,
  abortRef,
  submitRef,
}) {
  const { t, i18n } = useTranslation('helper')
  const location = useLocation()
  const textareaRef = useRef(null)

  const { currentWorkspace } = useWorkspace()
  const { currentProject } = useProject()
  const workspaceId = currentWorkspace?._id || null
  const projectId = currentProject?._id || null

  // Budget/credit 402 catcher (hard block — no resend). Intercepts the helper
  // stream's message_error before the generic error path.
  const { handleBudgetError, budgetModal } = useBudgetBlock()

  // DLP modal state — owned here so a single component handles pre-flight +
  // server-side dlp events uniformly.
  const [dlpModal, setDlpModal] = useState({
    open: false,
    matches: [],
    highestAction: 'warn',
    pendingText: '',
    redactedPreview: null,
    redactable: false,
  })

  // Manual auto-resize (avoids pulling in react-textarea-autosize for a single
  // textarea). Capped so the composer never devours the rail.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [value])

  // Run the stream. Redact resubmits with dlp_redact. Confirm does not unlock a send.
  const runStream = useCallback(
    async (text, { dlpConfirmed = false, dlpRedact = false, dlpConfirmToken = null } = {}) => {
      const page_context = { route: location.pathname }

      const { abort } = await streamHelper(
        { message: text, page_context, dlp_confirmed: dlpConfirmed, dlp_redact: dlpRedact, dlp_confirm_token: dlpConfirmToken },
        (event) => {
          switch (event.type) {
            case 'message_start':
              // Server confirmed; nothing extra to do — rail already showed the user bubble.
              break
            case 'message_chunk':
              onMessageChunk?.(event)
              break
            case 'message_complete':
              onMessageComplete?.(event)
              break
            case 'dlp_block':
            case 'dlp_confirm_required':
              // Server rejected after we already streamed optimistically.
              // Stale dlp_confirm_required is a block. Redaction still applies.
              setDlpModal((prev) => ({
                open: true,
                matches: event.matches || [],
                highestAction: 'block',
                pendingText: text,
                redactedPreview: event.redacted_preview ?? null,
                redactable: !!event.redactable,
                confirmToken: event.confirm_token ?? prev.confirmToken ?? null,
              }))
              onDlpBlock?.(event)
              break
            case 'message_error':
            case 'error':
              // Budget/credit ceiling reached (402) — hard-block modal, no
              // resend. Swallow the generic error path so only the modal shows.
              if (handleBudgetError(event)) break
              onMessageError?.(event)
              break
            default:
              // Forward unknown event types for forward-compat
              break
          }
        },
      )

      if (abortRef) {
        abortRef.current = abort
      }
    },
    [
      location.pathname,
      onMessageChunk,
      onMessageComplete,
      onMessageError,
      onDlpBlock,
      abortRef,
      handleBudgetError,
    ],
  )

  const submit = useCallback(async (override) => {
    // `override` lets retry / suggestion chips submit a specific string without
    // waiting for the controlled `value` to round-trip through React state.
    const text = (typeof override === 'string' ? override : value || '').trim()
    if (!text || streaming || disabled) return

    // ---- Pre-flight DLP scan ------------------------------------------
    // Best-effort: a scan failure (infra outage, 5xx) should NOT block the
    // user. The backend `dlp_gate` is the defense-in-depth fallback.
    if (workspaceId) {
      try {
        const scanRes = await dlpService.scan(text, workspaceId, 'helper', projectId)
        const result = scanRes?.result
        const action = result?.highest_action
        if (action && action !== 'allow' && result?.matches?.length) {
          if (scanRes.auto_redact) {
            // Workspace redact mode → server auto-redacts; skip the modal and
            // stream straight through with dlp_redact:true (frictionless).
            toast.success(t('dlp.autoRedacted', 'Sensitive info was redacted before sending'))
            onMessageStart?.(text)
            await runStream(text, { dlpRedact: true })
            return
          }
          if (action === 'warn') {
            toast(t('dlp.warn'), { icon: 'i' })
            // proceed without modal
          } else {
            // block / redact, and stale require_confirm (treated as block).
            // Stop. Scrub-and-send resubmits with dlp_redact. No send-anyway.
            setDlpModal({
              open: true,
              matches: result.matches,
              highestAction: action === 'require_confirm' ? 'block' : action,
              pendingText: text,
              redactedPreview: scanRes?.redacted_preview ?? null,
              redactable: !!scanRes?.redactable,
              confirmToken: scanRes?.confirm_token ?? null,
            })
            return
          }
        }
      } catch (err) {
        // Swallow — backend dlp_gate is the authoritative fallback.
        if (typeof console !== 'undefined' && console?.error) {
          console.error('DLP pre-flight scan failed:', err)
        }
      }
    }

    onMessageStart?.(text)
    await runStream(text)
  }, [
    value,
    streaming,
    disabled,
    workspaceId,
    projectId,
    t,
    onMessageStart,
    runStream,
  ])

  // Expose an imperative submit so the page can fire a specific message (retry
  // the last failed turn, or a clicked starter-prompt chip) without round-trip.
  useImperativeHandle(submitRef, () => ({ submit }), [submit])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  // Modal handlers ------------------------------------------------------
  const closeDlpModal = useCallback(() => {
    setDlpModal((prev) => ({ ...prev, open: false }))
  }, [])

  const handleDlpModify = useCallback(() => {
    // Keep the text in the composer for the user to edit; just dismiss.
    closeDlpModal()
  }, [closeDlpModal])

  const handleDlpRedactSend = useCallback(async () => {
    if (!dlpModal.redactable) return // safety — button is hidden when not redactable
    const text = dlpModal.pendingText
    closeDlpModal()
    if (!text) return
    onMessageStart?.(text)
    // Redaction neutralizes blocks too — no dlp_confirmed needed.
    await runStream(text, { dlpRedact: true })
  }, [dlpModal.redactable, dlpModal.pendingText, closeDlpModal, onMessageStart, runStream])

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
        className="p-3"
      >
        {/* Canonical chat composer pill: single rounded surface, 1px line,
            soft shadow, 2px-accent + accent-soft ring on focus-within. Flat
            (not glass) — this lives on a content page. */}
        <div
          className={cn(
            'flex items-end gap-2 rounded-[28px] border border-border bg-background px-3 py-2',
            'shadow-[0_1px_2px_-1px_rgb(15_23_42_/_0.10),0_2px_8px_-2px_rgb(15_23_42_/_0.08)]',
            'transition-colors focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/15',
          )}
        >
          <textarea
            ref={textareaRef}
            value={value || ''}
            onChange={(e) => onChange?.(e.target.value)}
            onKeyDown={handleKeyDown}
            dir={i18n.dir()}
            rows={1}
            disabled={disabled || streaming}
            placeholder={t('placeholder')}
            className={cn(
              'flex-1 resize-none border-0 bg-transparent px-2 py-1.5',
              'text-[15px] leading-[1.5] text-foreground placeholder:text-foreground-tertiary',
              'focus:outline-none focus:ring-0',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'min-h-[36px] max-h-[160px]',
            )}
            aria-label={t('composerAria')}
          />
          <button
            type="submit"
            disabled={disabled || streaming || !(value || '').trim()}
            aria-label={t('send')}
            className={cn(
              'mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all duration-200',
              disabled || streaming || !(value || '').trim()
                ? 'cursor-not-allowed bg-background-tertiary text-foreground-tertiary opacity-50'
                : 'bg-accent text-accent-foreground shadow-lg shadow-accent/25 hover:bg-accent/90',
            )}
          >
            {streaming ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-5 w-5" />
            )}
          </button>
        </div>
      </form>

      <DLPViolationModal
        isOpen={dlpModal.open}
        onClose={closeDlpModal}
        matches={dlpModal.matches}
        highestAction={dlpModal.highestAction}
        redactedPreview={dlpModal.redactedPreview}
        redactable={dlpModal.redactable}
        onModify={handleDlpModify}
        onRedactSend={handleDlpRedactSend}
      />

      {budgetModal}
    </>
  )
}

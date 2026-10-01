import { useCallback, useMemo, useState, createElement } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { dlpService } from '../services/dlpService'
import { useWorkspace } from '../context/WorkspaceContext'
import { useProject } from '../context/ProjectContext'
import DLPViolationModal from '../components/dlp/DLPViolationModal'

/**
 * Shared DLP pre-flight confirmation hook.
 *
 * Centralises the chat/helper pattern for surfaces (arena, debate,
 * automate-agent) that don't have the chat composer's bespoke state
 * machine but still need to honour workspace Content Safety policy.
 *
 * Usage:
 *
 *   const { scan, dlpModal } = useDlpConfirm({ source: 'arena' })
 *   const ok = await scan(userText)
 *   if (!ok) return                 // user dismissed / blocked
 *   await streamArena({ ..., dlp_confirmed: ok.confirmed }, handlers)
 *   // render in JSX:
 *   { dlpModal }
 *
 * `scan` returns:
 *   - `{ confirmed: false }`             on `allow`/`warn` (warn surfaces a toast only)
 *   - `{ confirmed: false, redact: true }` after user clicks "Redact & send"
 *   - `null`                             if user closed / clicked "Modify" / hit `block`
 *                                        (stale `require_confirm` is a block — never `{ confirmed: true }`)
 *
 * Callers forward `dlp_redact: result.redact` (only when truthy) into the
 * stream payload so the backend scrubs sensitive spans server-side.
 *
 * Scan-endpoint failures resolve to `{ confirmed: false }` — the backend
 * `dlp_gate` is the authoritative defence-in-depth fallback.
 *
 * @param {Object} opts
 * @param {'arena'|'debate'|'automate'|'image_prompt'} opts.source - Backend source tag.
 */
export function useDlpConfirm({ source }) {
  const { t } = useTranslation('dlp')
  const { currentWorkspace } = useWorkspace()
  const { currentProject } = useProject()
  const workspaceId = currentWorkspace?._id || null
  const projectId = currentProject?._id || null

  // Pending modal carries the matches, highest action, and a `resolve` so the
  // caller's awaited promise unblocks once the user dismisses or confirms.
  const [modal, setModal] = useState(null)

  const scan = useCallback(
    async (text, attachments = null) => {
      const value = (text || '').trim()
      const hasAttachments = Array.isArray(attachments) && attachments.length > 0
      // Empty prompt alone is a no-op; empty prompt + files still scans attachment text.
      if (!value && !hasAttachments) return { confirmed: false }
      if (!workspaceId) return { confirmed: false }

      let result
      let redactedPreview = null
      let redactable = false
      let confirmToken = null
      try {
        const res = await dlpService.scan(
          value,
          workspaceId,
          source,
          projectId,
          hasAttachments ? attachments : null,
        )
        result = res?.result
        redactedPreview = res?.redacted_preview ?? null
        redactable = !!res?.redactable
        confirmToken = res?.confirm_token ?? null
      } catch (err) {
        // Best-effort — backend dlp_gate covers the gap.
        if (typeof console !== 'undefined' && console?.error) {
          console.error('DLP pre-flight scan failed:', err)
        }
        return { confirmed: false }
      }

      const action = result?.highest_action
      if (!action || action === 'allow' || !result?.matches?.length) {
        return { confirmed: false }
      }

      if (action === 'warn') {
        // Non-blocking — surface a calm toast then proceed (no modal). Shared by
        // arena / debate / automate, so this one key softens all three at once.
        toast(t('toast.warn'), { icon: 'i' })
        return { confirmed: false }
      }

      // block / redact, and stale require_confirm (treated as block). Await the
      // choice. "Send anyway" is gone — resolve null, same as cancel.
      const highestAction = action === 'require_confirm' ? 'block' : action
      return new Promise((resolve) => {
        setModal({
          matches: result.matches,
          highestAction,
          redactedPreview,
          redactable,
          confirmToken,
          resolve,
        })
      })
    },
    [workspaceId, projectId, source, t],
  )

  const handleClose = useCallback(() => {
    setModal((current) => {
      if (current) current.resolve(null)
      return null
    })
  }, [])

  const handleModify = useCallback(() => {
    setModal((current) => {
      if (current) current.resolve(null)
      return null
    })
  }, [])

  const handleSendAnyway = useCallback(() => {
    // Modal no longer offers this. If a caller still wires it, cancel — never
    // `{ confirmed: true }`.
    setModal((current) => {
      if (current) current.resolve(null)
      return null
    })
  }, [])

  const handleRedactSend = useCallback(() => {
    setModal((current) => {
      if (!current) return null
      if (!current.redactable) {
        // Safety — button is hidden when not redactable but guard anyway.
        current.resolve(null)
        return null
      }
      // Redaction neutralizes blocks too — no `confirmed` needed; the backend
      // scrubs the sensitive spans server-side when `dlp_redact` is set.
      current.resolve({ confirmed: false, redact: true })
      return null
    })
  }, [])

  // Render the modal as JSX the page can drop into its tree.
  const dlpModal = useMemo(
    () =>
      createElement(DLPViolationModal, {
        isOpen: !!modal,
        onClose: handleClose,
        onModify: handleModify,
        onSendAnyway: handleSendAnyway,
        onRedactSend: handleRedactSend,
        matches: modal?.matches || [],
        highestAction: modal?.highestAction || 'warn',
        redactedPreview: modal?.redactedPreview || null,
        redactable: !!modal?.redactable,
      }),
    [modal, handleClose, handleModify, handleSendAnyway, handleRedactSend],
  )

  return { scan, dlpModal }
}

export default useDlpConfirm

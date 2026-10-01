import { useState, useEffect, useRef, useCallback } from 'react'
import { chatService } from '../../../services/chatService'
import api from '../../../services/api'
import toast from 'react-hot-toast'
import i18n from '../../../i18n'

export function chatActionError(error, fallbackKey) {
  if (error === 'Message not found or not regeneratable') {
    return i18n.t('chat:messageActions.regenUnavailable')
  }
  if (error === 'No user message found') {
    return i18n.t('chat:messageActions.regenNoPrompt')
  }
  if (error === 'Config not found') {
    return i18n.t('chat:messageActions.regenConfigMissing')
  }
  return error || i18n.t(fallbackKey)
}

/** Cheap identity for shared-chat poll thrash: skip setMessages when unchanged. */
function messagesFingerprint(msgs) {
  if (!msgs?.length) return '0'
  const last = msgs[msgs.length - 1]
  return `${msgs.length}:${last?._id || ''}:${(last?.content || '').length}:${last?.updated_at || last?.created_at || ''}`
}

export function useChatMessages({
  conversationId,
  conversationData,
  queryClient,
  onBudgetExceeded,
  onDLPViolation,
}) {
  const [messages, setMessages] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingMessageId, setStreamingMessageId] = useState(null)
  const [streamingContent, setStreamingContent] = useState('')

  // Ref to skip query overwrite right after streaming ends
  const justFinishedStreamingRef = useRef(false)

  // Always-current messages snapshot for callbacks that need a synchronous
  // read (optimistic edit revert) without adding `messages` to their deps.
  const messagesRef = useRef([])
  useEffect(() => { messagesRef.current = messages }, [messages])

  // Failed-send marker, owned by useChatStream (object | null). While set, the
  // conversationData sync below must not run — the failed optimistic bubble was
  // never persisted, so a refetch would silently wipe the message the retry
  // banner points at.
  const streamErrorRef = useRef(null)

  // Tracks the previous conversationId so the sync effect below can tell a real
  // conversation SWITCH (sidebar click) apart from a same-conversation re-run or
  // the new-chat id assignment (null → id).
  const prevConversationIdRef = useRef(conversationId)

  // Load messages from conversation
  useEffect(() => {
    const prevId = prevConversationIdRef.current
    prevConversationIdRef.current = conversationId
    // A real conversation SWITCH (sidebar click to a different chat), as opposed
    // to a same-conversation re-run or the new-chat null→id promotion (prevId null).
    const isRealSwitch = prevId != null && prevId !== conversationId

    // The guards below pertain to the PREVIOUS conversation's just-streamed /
    // failed-send state — discard them so they can't block the new conversation.
    if (isRealSwitch) {
      justFinishedStreamingRef.current = null
      streamErrorRef.current = null
      // Reset isStreaming on a real switch so an in-flight EDIT/REGENERATE on the
      // conversation being left (blocking awaits — no abort controller, so the
      // stream hook's switch-abort can't catch them) can't keep the destination's
      // load gated. The new-chat null→id promotion has prevId==null → skipped.
      setIsStreaming(false)
    }

    // Don't overwrite streaming messages with stale query data
    if (isStreaming) return

    // A failed send is pending retry/dismiss — keep its optimistic bubble.
    if (streamErrorRef.current) return

    // Skip overwrite right after streaming ends (query data may be stale) — but
    // ONLY for the conversation that just streamed. A stream finishing after the
    // user switched away holds a DIFFERENT id here, so it can't block this view.
    if (justFinishedStreamingRef.current && justFinishedStreamingRef.current === conversationId) {
      // Delay reset to survive multiple React Query updates
      setTimeout(() => {
        justFinishedStreamingRef.current = null
      }, 1000)
      return
    }

    if (conversationData?.messages) {
      // Data for the current conversation is ready (cached or freshly fetched).
      // Shared chats poll ~5s; identical payloads still get a new array identity
      // from React Query and would thrash the virtualizer. Real switches always
      // apply; same-conversation polls only apply when content fingerprint moves.
      // A stop commits partial assistant text locally before the server row
      // (still the empty placeholder) is readable. Don't let that refetch
      // blank the reply.
      const next = conversationData.messages.map((m) => {
        if (m?.content) return m
        const local = messagesRef.current.find((x) => x._id === m._id)
        if (local?.content) return { ...m, content: local.content }
        return m
      })
      if (
        !isRealSwitch &&
        messagesFingerprint(next) === messagesFingerprint(messagesRef.current)
      ) {
        return
      }
      setMessages(next)
    } else if (!conversationId || isRealSwitch) {
      // Nothing to show yet: the empty new-chat (!conversationId) OR a switch to a
      // conversation whose GET is still in flight. Clear so the previous thread
      // doesn't linger — the fetch re-runs this effect to populate. ChatPage no
      // longer remounts on /chat/<id1> → /chat/<id2>, so this single effect is the
      // sole owner of `messages` on a switch; there is deliberately NO separate
      // clear effect (a second writer would wipe the cached-data load above and
      // strand the view on the empty state).
      setMessages([])
    }
  }, [conversationData, conversationId, isStreaming])

  const handleEditMessage = useCallback(async (messageId, newContent) => {
    if (!conversationId) return

    // Prevent editing messages with temporary IDs (not yet saved to DB)
    if (messageId.toString().startsWith('temp-')) {
      toast.error(i18n.t('common:runtime.branches.waitForSave'))
      return
    }

    const snapshot = messagesRef.current
    if (snapshot.findIndex(m => m._id === messageId) === -1) return

    // Apply a server payload ({message, assistant_message?}) to local state AND
    // the query cache. The cache patch matters: when isStreaming flips false the
    // sync effect re-runs against the cached conversation, which is still the
    // PRE-edit list — without the patch the deleted tail flashes back until the
    // invalidate's refetch lands.
    const applyResult = (payload) => {
      setMessages(prev => {
        const next = prev.map(m => (m._id === messageId ? payload.message : m))
        return payload.assistant_message ? [...next, payload.assistant_message] : next
      })
      queryClient.setQueryData(['conversation', conversationId], (old) => {
        if (!old?.messages) return old
        const idx = old.messages.findIndex(m => m._id === messageId)
        if (idx === -1) return old
        const msgs = old.messages
          .slice(0, idx + 1)
          .map(m => (m._id === messageId ? payload.message : m))
        if (payload.assistant_message) msgs.push(payload.assistant_message)
        return { ...old, messages: msgs }
      })
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    }

    // Optimistic ChatGPT-style transition: swap the bubble text + truncate the
    // tail IMMEDIATELY (regenerate deletes it server-side anyway), so the
    // thinking dots render right under the edited turn while the blocking
    // regenerate round-trip runs. The snapshot above reverts pre-persist failures.
    setMessages(prev => {
      const idx = prev.findIndex(m => m._id === messageId)
      if (idx === -1) return prev
      return prev.slice(0, idx + 1).map(m =>
        m._id === messageId ? { ...m, content: newContent, is_edited: true } : m
      )
    })
    setIsStreaming(true)

    const runEdit = async (extra = {}) => {
      return chatService.editMessage(messageId, newContent, true, extra)
    }

    try {
      const result = await runEdit()
      applyResult(result)
    } catch (error) {
      const data = error.response?.data
      // Budget 402 — hard block modal, no resend.
      if (onBudgetExceeded?.(data)) {
        setMessages(snapshot)
        justFinishedStreamingRef.current = conversationId
        setIsStreaming(false)
        return
      }
      // DLP block (stale confirm counts as block). Resubmit only on scrub.
      const dlpCode = data?.code
      if (
        onDLPViolation &&
        (dlpCode === 'dlp_confirm_required' || dlpCode === 'dlp_blocked') &&
        Array.isArray(data?.matches)
      ) {
        const rawAction = data.highest_action || 'block'
        const decision = await onDLPViolation({
          matches: data.matches,
          highestAction: rawAction === 'require_confirm' || dlpCode === 'dlp_confirm_required' ? 'block' : rawAction,
          text: newContent,
          redactedPreview: data.redacted_preview ?? null,
          redactable: !!data.redactable,
        })
        if (decision?.redact) {
          try {
            const result = await runEdit({
              dlp_redact: true,
            })
            applyResult(result)
            justFinishedStreamingRef.current = conversationId
            setIsStreaming(false)
            return
          } catch (retryErr) {
            const rd = retryErr.response?.data
            if (onBudgetExceeded?.(rd)) {
              setMessages(snapshot)
              justFinishedStreamingRef.current = conversationId
              setIsStreaming(false)
              return
            }
            if (rd?.message) applyResult(rd)
            else setMessages(snapshot)
            toast.error(chatActionError(rd?.error, 'common:runtime.chat.editFailed'))
            justFinishedStreamingRef.current = conversationId
            setIsStreaming(false)
            return
          }
        }
        // User dismissed / modify — restore optimistic edit.
        setMessages(snapshot)
        justFinishedStreamingRef.current = conversationId
        setIsStreaming(false)
        return
      }
      if (data?.message) {
        // Completion failed AFTER the edit + tail-delete persisted (backend 500
        // carries the updated message + an error assistant turn) — reconcile to
        // server truth instead of restoring a tail that no longer exists.
        applyResult(data)
      } else {
        // Edit never persisted (network drop / 4xx) — restore exactly what was.
        setMessages(snapshot)
      }
      toast.error(chatActionError(data?.error, 'common:runtime.chat.editFailed'))
    } finally {
      // Same contract as the send path: skip the stale-cache sync that fires
      // when isStreaming flips false — applyResult already wrote fresh truth.
      // Scoped to this conversation so it can't block a switched-to view.
      justFinishedStreamingRef.current = conversationId
      setIsStreaming(false)
    }
  }, [conversationId, queryClient, onBudgetExceeded, onDLPViolation])

  const handleRegenerateMessage = useCallback(async (messageId, configId = null) => {
    if (!conversationId) return

    const applyRegen = (result) => {
      setMessages(prev => prev.map(m =>
        m._id === messageId ? result.message : m
      ))
      queryClient.setQueryData(['conversation', conversationId], (old) => {
        if (!old?.messages) return old
        return {
          ...old,
          messages: old.messages.map(m => (m._id === messageId ? result.message : m)),
        }
      })
    }

    const runRegen = (extra = {}) => chatService.regenerateMessage(messageId, configId, extra)

    try {
      setIsStreaming(true)
      const result = await runRegen()
      applyRegen(result)
      toast.success(i18n.t('common:runtime.chat.regenerated'))
    } catch (error) {
      const data = error.response?.data
      if (onBudgetExceeded?.(data)) {
        justFinishedStreamingRef.current = conversationId
        setIsStreaming(false)
        return
      }
      const dlpCode = data?.code
      if (
        onDLPViolation &&
        (dlpCode === 'dlp_confirm_required' || dlpCode === 'dlp_blocked') &&
        Array.isArray(data?.matches)
      ) {
        const rawAction = data.highest_action || 'block'
        const decision = await onDLPViolation({
          matches: data.matches,
          highestAction: rawAction === 'require_confirm' || dlpCode === 'dlp_confirm_required' ? 'block' : rawAction,
          text: '',
          redactedPreview: data.redacted_preview ?? null,
          redactable: !!data.redactable,
        })
        if (decision?.redact) {
          try {
            const result = await runRegen({
              dlp_redact: true,
            })
            applyRegen(result)
            toast.success(i18n.t('common:runtime.chat.regenerated'))
            justFinishedStreamingRef.current = conversationId
            setIsStreaming(false)
            return
          } catch (retryErr) {
            const rd = retryErr.response?.data
            if (onBudgetExceeded?.(rd)) {
              justFinishedStreamingRef.current = conversationId
              setIsStreaming(false)
              return
            }
            toast.error(chatActionError(rd?.error, 'common:runtime.chat.regenerateFailed'))
            justFinishedStreamingRef.current = conversationId
            setIsStreaming(false)
            return
          }
        }
        justFinishedStreamingRef.current = conversationId
        setIsStreaming(false)
        return
      }
      toast.error(chatActionError(data?.error, 'common:runtime.chat.regenerateFailed'))
    } finally {
      justFinishedStreamingRef.current = conversationId
      setIsStreaming(false)
    }
  }, [conversationId, queryClient, onBudgetExceeded, onDLPViolation])

  // Thumbs up/down on an assistant message. Optimistically patches
  // message.metadata.feedback, then persists; reverts on error.
  // rating ∈ 'up' | 'down' | null (null clears).
  const handleMessageFeedback = useCallback(async (messageId, rating) => {
    if (!conversationId) return

    // Capture prior value for revert. Read from the functional updater so we
    // never close over a stale `messages` snapshot.
    let prevRating = null
    setMessages(prev => prev.map(m => {
      if (m._id !== messageId) return m
      prevRating = m.metadata?.feedback ?? null
      return { ...m, metadata: { ...(m.metadata || {}), feedback: rating } }
    }))

    try {
      await chatService.submitMessageFeedback(messageId, rating)
    } catch (error) {
      // Revert the optimistic patch
      setMessages(prev => prev.map(m =>
        m._id === messageId
          ? { ...m, metadata: { ...(m.metadata || {}), feedback: prevRating } }
          : m
      ))
      toast.error(i18n.t('chat:messageActions.feedbackError'))
    }
  }, [conversationId])

  // Handle file upload for chat attachments. Three paths:
  //  - small images (< ~1.5MB)  → inline base64 data-URL (no server storage)
  //  - ZIP archives → disk-backed upload that returns the archive's extracted
  //    text PLUS its inner images as sibling `extra_attachments` (see below)
  //  - everything else (PDF / office / text / large images) → disk-backed
  //    upload via /uploads/file; backend extracts text and injects it server-side
  //    keyed by upload_id (we do NOT carry extracted text in the payload).
  //
  // Returns either a single attachment object OR an array of attachment objects
  // (ZIP yields the archive chip + one image chip per extracted picture). The
  // optional `staging` controller lets the caller drop an immediate placeholder
  // (the archive's "opening… reading files" chip) before the upload resolves and
  // reconcile it once the full response lands.
  const handleFileUpload = useCallback(async (file, staging = null) => {
    // Cap matches backend CHAT_UPLOAD_MAX_BYTES (32MB)
    const maxSize = 32 * 1024 * 1024
    if (file.size > maxSize) {
      toast.error(i18n.t('common:runtime.chat.fileTooLarge'))
      return null
    }

    // Extension fallback — browser MIME is empty/unreliable for some types
    // (e.g. .csv often has no or an odd MIME on Windows; .zip varies too).
    const ext = (file.name.split('.').pop() || '').toLowerCase()
    const allowedExts = [
      'jpg', 'jpeg', 'png', 'gif', 'webp',
      'pdf', 'doc', 'docx', 'xls', 'xlsx', 'xlsm', 'ppt', 'pptx',
      'csv', 'txt', 'md', 'html', 'htm', 'json', 'xml',
      'tsv', 'jsonl', 'parquet',
      'zip',
      // Audio / video — read natively by multimodal models (Gemini). Capability
      // gating + auto-switch happen in the composer; these just clear the guard.
      'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'aiff',
      'mp4', 'webm', 'mov', 'mpeg', 'mpg'
    ]
    const allowedMimes = [
      'image/jpeg', 'image/png', 'image/gif', 'image/webp',
      'application/pdf',
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/vnd.ms-excel.sheet.macroEnabled.12',
      'application/vnd.ms-powerpoint',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      'text/csv', 'text/plain', 'text/markdown', 'text/html', 'application/json',
      'text/xml', 'application/xml',
      'text/tab-separated-values', 'application/x-ndjson',
      'application/zip', 'application/x-zip-compressed',
      'audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/mp4', 'audio/x-m4a',
      'audio/ogg', 'audio/flac', 'audio/aac', 'audio/aiff',
      'video/mp4', 'video/webm', 'video/quicktime', 'video/mpeg'
    ]
    const mimeOk = file.type && allowedMimes.includes(file.type)
    const extOk = allowedExts.includes(ext)
    if (!mimeOk && !extOk) {
      toast.error(i18n.t('common:runtime.chat.unsupportedFileType'))
      return null
    }

    const isZip = ext === 'zip' ||
      ['application/zip', 'application/x-zip-compressed'].includes(file.type || '')
    const isImage = !isZip && ((file.type || '').startsWith('image/') ||
      ['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext))
    const inlineThreshold = 1.5 * 1024 * 1024

    // ZIP path: stage an "opening" placeholder right away (the chip shows a
    // spinner while the archive is read), then POST the archive and read the
    // FULL response — `chatService.uploadFile` only returns `.upload` and DROPS
    // the sibling `extra_attachments`, so we hit the axios instance directly.
    if (isZip) {
      const placeholderId = `zip-${Date.now()}-${Math.random().toString(36).slice(2)}`
      staging?.addPlaceholder?.({
        placeholder_id: placeholderId,
        name: file.name,
        type: 'zip',
        mime_type: file.type || 'application/zip',
        size: file.size,
        status: 'opening'
      })

      try {
        const formData = new FormData()
        formData.append('file', file)
        const { data } = await api.post('/uploads/file', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })

        const up = data.upload || {}
        const extras = Array.isArray(data.extra_attachments) ? data.extra_attachments : []

        const archiveAttachment = {
          placeholder_id: placeholderId,
          name: up.original_name || file.name,
          type: 'zip',
          mime_type: file.type || 'application/zip',
          size: up.size ?? file.size,
          url: up.url,
          upload_id: up.id,
          is_pdf: false,
          extraction_status: up.extraction_status ?? null,
          extracted_chars: up.extracted_chars ?? 0,
          // `zip_entries` may be absent — downstream chip handles undefined.
          zip_entries: Array.isArray(up.zip_entries) ? up.zip_entries : undefined,
          image_count: extras.length,
          status: 'ready'
        }

        // Each extracted image becomes a normal image chip (same shape the inline
        // / disk-backed image paths produce) so the model actually sees them.
        const imageAttachments = extras.map((img) => ({
          name: img.original_name,
          type: 'image',
          mime_type: img.mime_type || 'image/png',
          size: img.size ?? 0,
          url: img.thumbnail_url || img.url,
          upload_id: img.id,
          is_pdf: false,
          extraction_status: null,
          extracted_chars: 0
        }))

        // Swap the placeholder for the real archive chip, then append the image
        // chips. Returning the array also covers callers without a staging hook.
        staging?.replacePlaceholder?.(placeholderId, [archiveAttachment, ...imageAttachments])
        return [archiveAttachment, ...imageAttachments]
      } catch (error) {
        staging?.removePlaceholder?.(placeholderId)
        toast.error(
          error.response?.data?.error || i18n.t('common:runtime.chat.fileProcessFailed')
        )
        return null
      }
    }

    try {
      // Small images stay inline as base64 — avoids a round-trip + server storage.
      if (isImage && file.size < inlineThreshold) {
        const base64 = await chatService.fileToBase64(file)
        return {
          name: file.name,
          type: file.type,
          mime_type: file.type,
          size: file.size,
          url: base64, // data:image/png;base64,...
          upload_id: null,
          is_pdf: false,
          extraction_status: null,
          extracted_chars: 0
        }
      }

      // Everything else → disk-backed upload (server-side text extraction).
      // Audio/video are always disk-backed (never the inline-image path); the
      // is_audio/is_video booleans let the backend formatter branch reliably
      // instead of re-deriving from MIME/extension.
      const up = await chatService.uploadFile(file)
      return {
        name: up.original_name || file.name,
        type: file.type,
        mime_type: file.type || up.mime_type || '',
        size: up.size ?? file.size,
        url: up.url, // /api/uploads/{id}
        upload_id: up.id,
        is_pdf: ext === 'pdf' || file.type === 'application/pdf',
        is_audio: /\.(mp3|wav|m4a|ogg|flac|aac|aiff)$/i.test(file.name) || (file.type || '').startsWith('audio/'),
        is_video: /\.(mp4|webm|mov|mpeg|mpg)$/i.test(file.name) || (file.type || '').startsWith('video/'),
        extraction_status: up.extraction_status ?? null,
        extracted_chars: up.extracted_chars ?? 0
      }
    } catch (error) {
      toast.error(
        error.response?.data?.error || i18n.t('common:runtime.chat.fileProcessFailed')
      )
      return null
    }
  }, [])

  return {
    messages,
    setMessages,
    isStreaming,
    setIsStreaming,
    streamingContent,
    setStreamingContent,
    streamingMessageId,
    setStreamingMessageId,
    justFinishedStreamingRef,
    streamErrorRef,
    handleEditMessage,
    handleRegenerateMessage,
    handleMessageFeedback,
    handleFileUpload
  }
}

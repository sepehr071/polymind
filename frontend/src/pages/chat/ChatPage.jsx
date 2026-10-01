import { useState, useEffect, useCallback, useMemo, useRef, Suspense } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Loader2, X, RefreshCw, WifiOff } from 'lucide-react'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { chatService, configService } from '../../services/chatService'
import { useProject } from '../../context/ProjectContext'
import ChatWindow from '../../components/chat/ChatWindow'
import ChatEmptyState from '../../components/chat/ChatEmptyState'
import ChatInput from '../../components/chat/ChatInput'
import ChatHeader from '../../components/chat/ChatHeader'
import DLPViolationModal from '../../components/dlp/DLPViolationModal'
import DLPFirstRunNote from '../../components/dlp/DLPFirstRunNote'
import ErrorBoundary from '../../components/common/ErrorBoundary'
import { useBudgetBlock } from '../../hooks/useBudgetBlock'
import { useOnlineStatus } from '../../hooks/useOnlineStatus'
import { useAuth } from '../../context/AuthContext'
import { hasFeature } from '../../utils/featureFlags'
// Helpers are tiny + used eagerly → static import. The heavy CodeMirror-backed
// CodeCanvas component is lazy (see below) so it stays out of the chat chunk.
import { parseHtmlCode } from '../../components/chat/CodeCanvas/parse'
import { useChatMessages, useChatStream, useChatExport } from './hooks'
import { isQuickModel, getModelIdFromQuick, findDefaultModel, QUICK_MODEL_IDS } from '../../constants/models'
import { takeDashboardChatConfig } from '../../utils/dashboardChatHandoff'
import { resolvePrivacyMode } from '../../constants/modelPrivacy'
import { PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Button } from '../../components/ui/button'
import lazyWithRetry from '../../utils/lazyWithRetry'

// Lazy-loaded only when the user opens the Code Canvas. Pulls CodeMirror + the
// language grammar barrel into a separate chunk instead of the always-loaded
// chat bundle. Use lazyWithRetry (NOT React.lazy) so chunk-load retry applies.
const CodeCanvas = lazyWithRetry(() => import('../../components/chat/CodeCanvas'))

export default function ChatPage() {
  const { t } = useTranslation('chat')
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { currentProject } = useProject()
  const projectId = currentProject?._id || null
  const { user } = useAuth()
  // Platform feature flag for the whole Code Canvas capability: gates the
  // CodeBlock Run button (onRunCode falsy → MarkdownRenderer hides it) and the
  // composer Tools → Canvas item. Default ON; toggled at /admin/features.
  const canvasEnabled = hasFeature(user, 'code_canvas_run')

  // Config state. A fresh /chat opened from the home composer keeps that pick.
  const [selectedConfigId, setSelectedConfigId] = useState(() => (
    conversationId ? null : takeDashboardChatConfig()
  ))

  // Narrow viewport: Code Canvas is a fixed overlay, so the grid has no canvas track.
  const isNarrow = useMediaQuery('(max-width: 767px)')

  // Code Canvas state — standalone overlay panel triggered by "Run" on HTML/CSS/JS blocks
  const [codeCanvasOpen, setCodeCanvasOpen] = useState(false)
  const [codeCanvasCode, setCodeCanvasCode] = useState({ html: '', css: '', js: '' })

  // DLP violation modal state.
  // The resolve() contract (consumed by useChatStream / useChatMessages):
  //   - false              -> dismissed / Modify / block
  //   - { redact: true }   -> "Redact & send"
  // Stale require_confirm is a block. Never resolve { confirmed: true }.
  const [dlpModal, setDlpModal] = useState(null) // { matches, highestAction, text, attachments, redactedPreview, redactable, resolve } | null
  const requestDLPDecision = useCallback(({ matches, highestAction, text = '', attachments = [], redactedPreview = null, redactable = false }) => {
    const action = highestAction === 'require_confirm' ? 'block' : highestAction
    return new Promise((resolve) => setDlpModal({ matches, highestAction: action, text, attachments, redactedPreview, redactable, resolve }))
  }, [])

  // Budget/credit 402 catcher (hard block — no resend). Threaded into
  // useChatStream as `onBudgetExceeded`, the same way DLP is threaded.
  const { handleBudgetError, budgetModal } = useBudgetBlock()

  // Composer restore (force-remount via key) when user clicks Modify on the DLP modal
  const [composerRestore, setComposerRestore] = useState({ text: '', files: [], key: 0 })
  const [privacyDismissed, setPrivacyDismissed] = useState(() => {
    try { return sessionStorage.getItem('polymind.privacy.banner.dismissed') === '1' } catch { return false }
  })

  // Prefill composer from sessionStorage (set by Workflow OutputActionBar's "Open in Chat").
  // Read once per conversation switch, then clear the key so refreshes don't repopulate.
  const composerPrefill = useMemo(() => {
    if (!conversationId) return ''
    try {
      const key = `chat_prefill_${conversationId}`
      const value = sessionStorage.getItem(key) || ''
      if (value) sessionStorage.removeItem(key)
      return value
    } catch {
      return ''
    }
  }, [conversationId])

  const handleRunCode = useCallback((code, language) => {
    const parsedCode = parseHtmlCode(code, language)
    setCodeCanvasCode(parsedCode)
    setCodeCanvasOpen(true)
  }, [])

  // Close Code Canvas on Escape
  useEffect(() => {
    if (!codeCanvasOpen) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setCodeCanvasOpen(false)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [codeCanvasOpen])

  // Shared-poll pause flag (read by refetchInterval; ref avoids stale closure).
  // isStreaming comes later from useChatMessages — assign ref.current after hook.
  const isStreamingRef = useRef(false)

  // Fetch conversation if ID is provided
  const {
    data: conversationData,
    isLoading: isLoadingConversation,
    isError: isConversationError,
    refetch: refetchConversation,
  } = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => chatService.getConversation(conversationId),
    enabled: !!conversationId,
    staleTime: 30000,
    // Team-shared chats poll (~5s) so a teammate's new messages appear. The
    // useChatMessages sync effect already skips overwrite while streaming /
    // mid-edit / failed-send, so this never clobbers an in-flight turn. Private
    // chats don't poll.
    //
    // Pause while tab hidden (document.hidden) or while we own a live stream —
    // stream path keeps cache warm via setQueryData; polling then only burns
    // network + forces message-array thrash. Fingerprint skip in useChatMessages
    // still guards when poll returns identical content.
    //
    // No refetch-on-window-focus (relies on the global `false` default): the
    // stream keeps this detail cache fresh via setQueryData, so an alt-tab
    // would otherwise re-pull the ENTIRE thread for no gain. Team-shared chats
    // already stay current via the 5s refetchInterval above.
    refetchInterval: (query) => {
      if (!query.state.data?.conversation?.share?.is_shared) return false
      if (typeof document !== 'undefined' && document.hidden) return false
      if (isStreamingRef.current) return false
      return 5000
    },
  })

  // Fetch user's configs (scoped to active project so the picker can group them)
  const { data: configsData } = useQuery({
    queryKey: ['configs', { projectId }],
    queryFn: () => configService.getConfigs(projectId ? { project_id: projectId } : undefined),
  })

  // Image-kind assistants (parameters.kind === 'image') belong to Image Studio,
  // not chat — filter them out of the persona/model picker list.
  // Memo: stable ref while configsData unchanged so memo(ChatHeader) can skip
  // token-level ChatPage re-renders.
  const configs = useMemo(
    () => (configsData?.configs || []).filter((c) => c.parameters?.kind !== 'image'),
    [configsData?.configs],
  )
  const conversation = conversationData?.conversation

  // Set initial config: existing conversation's config wins, else default to
  // the first quick model (Gemini). Custom configs no longer auto-select —
  // user can still pick them from the model chip dropdown.
  //
  // Sync ONLY when the loaded conversation changes (id), never on every
  // selectedConfigId change — otherwise picking a new model mid-conversation
  // re-runs this effect and immediately reverts to the convo's saved config
  // (the model picker looks dead). The ref tracks the last conv we synced.
  const syncedConvIdRef = useRef(undefined)
  useEffect(() => {
    const convId = conversation?._id || null
    if (syncedConvIdRef.current === convId) return
    syncedConvIdRef.current = convId
    if (conversation?.config_id) {
      setSelectedConfigId(conversation.config_id)
    } else if (!selectedConfigId && QUICK_MODEL_IDS.length > 0) {
      setSelectedConfigId(`quick:${QUICK_MODEL_IDS[0]}`)
    }
  }, [conversation, selectedConfigId])

  // Custom hooks
  const {
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
    handleMessageFeedback,
    handleFileUpload,
  } = useChatMessages({
    conversationId,
    conversationData,
    queryClient,
    onBudgetExceeded: handleBudgetError,
    onDLPViolation: requestDLPDecision,
  })

  // Keep shared-poll pause flag current (refetchInterval reads this, not state).
  isStreamingRef.current = isStreaming

  const {
    handleSendMessage,
    handleRegenerateMessage,
    handleStopGeneration,
    streamError,
    retryFailedSend,
    dismissStreamError,
    liveDataAnalysis,
  } = useChatStream({
    conversationId,
    selectedConfigId,
    navigate,
    queryClient,
    setMessages,
    setStreamingContent,
    setStreamingMessageId,
    setIsStreaming,
    justFinishedStreamingRef,
    streamErrorRef,
    onCanvasIntent: (parsed) => { setCodeCanvasCode(parsed); setCodeCanvasOpen(true) },
    projectId,
    onDLPViolation: requestDLPDecision,
    onBudgetExceeded: handleBudgetError,
  })

  // Dashboard hub hand-off: the QuickChatComposer stashes its draft in
  // sessionStorage then navigates here. On a BRAND-NEW chat (no conversationId)
  // we auto-send that draft exactly once through the SAME handleSendMessage the
  // composer's Send button calls — preserving the optimistic-first contract
  // (user bubble + isStreaming before DLP) verbatim; we just invoke the handler.
  //
  // The draft is read+cleared once on first mount (into a ref) so it survives
  // the deferred config-sync effect, then fired the moment selectedConfigId is
  // ready (handleSendMessage toasts + bails without a config). The `fired` guard
  // ensures it never double-sends.
  const dashboardDraftRef = useRef(undefined)
  const dashboardDraftFiredRef = useRef(false)
  if (dashboardDraftRef.current === undefined) {
    if (conversationId) {
      // Existing conversation — never consume the hub draft here.
      dashboardDraftRef.current = ''
    } else {
      try {
        const draft = sessionStorage.getItem('dashboard_chat_draft') || ''
        if (draft) sessionStorage.removeItem('dashboard_chat_draft')
        dashboardDraftRef.current = draft
      } catch {
        dashboardDraftRef.current = ''
      }
    }
  }
  useEffect(() => {
    if (conversationId) return
    if (dashboardDraftFiredRef.current) return
    const draft = dashboardDraftRef.current
    if (!draft || !selectedConfigId) return
    dashboardDraftFiredRef.current = true
    handleSendMessage(draft, [], null, {})
  }, [conversationId, selectedConfigId, handleSendMessage])

  // Live connectivity flag for the offline notice (banner above the composer).
  const isOnline = useOnlineStatus()

  // Dismissing a failed send restores the undelivered text + files into the
  // composer (same mechanism as the DLP "Modify" path) — nothing typed is lost.
  const dismissFailedSend = useCallback(() => {
    if (streamError) {
      setComposerRestore((prev) => ({
        text: streamError.content || '',
        files: streamError.attachments || [],
        key: prev.key + 1,
      }))
    }
    dismissStreamError()
  }, [streamError, dismissStreamError])

  // Refetch conversation lists when the active project CHANGES so the sidebar /
  // history view re-scopes to the new project (or "Unfiled"). The configs query
  // already keys on projectId, so React Query refetches it automatically — no
  // explicit invalidation needed. Skip the initial mount: the freshly-mounted
  // queries are already scoped correctly, so invalidating them on first render
  // is wasted network.
  const didMountProjectRef = useRef(false)
  useEffect(() => {
    if (!didMountProjectRef.current) {
      didMountProjectRef.current = true
      return
    }
    // Only the sidebar list keys off the active project. `conversations-history`
    // lives on the (unmounted) HistoryPage, and `recent-conversations`/`folders`
    // have no producers anywhere — invalidating them was dead weight.
    queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }, [projectId, queryClient])

  const { handleExport } = useChatExport(conversationId)

  // Stable ChatHeader props so memo(ChatHeader) skips token-level ChatPage renders.
  const handleExportMarkdown = useCallback(() => handleExport('markdown'), [handleExport])
  const handleExportJson = useCallback(() => handleExport('json'), [handleExport])
  const handleExportPdf = useCallback(() => handleExport('pdf'), [handleExport])
  const dismissPrivacy = useCallback(() => {
    try { sessionStorage.setItem('polymind.privacy.banner.dismissed', '1') } catch { /* quota */ }
    setPrivacyDismissed(true)
    window.dispatchEvent(new CustomEvent('chat:composer-focus'))
  }, [])
  const handleConversationMoved = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    queryClient.invalidateQueries({ queryKey: ['conversations-history'] })
    queryClient.invalidateQueries({ queryKey: ['recent-conversations'] })
  }, [queryClient, conversationId])
  const handleConversationRenamed = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    queryClient.invalidateQueries({ queryKey: ['conversations-history'] })
    queryClient.invalidateQueries({ queryKey: ['recent-conversations'] })
  }, [queryClient, conversationId])

  // Resolve selected config (handles quick models and regular configs)
  const selectedConfig = useMemo(() => {
    if (!selectedConfigId) return null
    if (isQuickModel(selectedConfigId)) {
      const modelId = getModelIdFromQuick(selectedConfigId)
      const model = findDefaultModel(modelId)
      if (model) {
        return {
          _id: selectedConfigId,
          name: model.name,
          avatar: { type: 'logo', value: model.logo },
          model_id: model.id,
          isQuickModel: true,
        }
      }
    }
    return configs.find((c) => c._id === selectedConfigId)
  }, [selectedConfigId, configs])

  const privacyMode = useMemo(() => {
    const modelId = isQuickModel(selectedConfigId)
      ? getModelIdFromQuick(selectedConfigId)
      : (selectedConfig?.model_id || null)
    return resolvePrivacyMode('model', { modelId })
  }, [selectedConfigId, selectedConfig])

  // Fresh chat → render the ChatGPT-signature centered empty state (greeting +
  // composer + suggestion cards as one vertically-centered block). Flips to the
  // normal docked layout the moment the first message exists or a stream starts.
  const isEmpty = messages.length === 0 && !isStreaming

  // Row cap is load-bearing: without it the chat column grows with content and
  // the composer drops below the viewport. History lives in the app sidebar.
  const shellStyle = { gridTemplateColumns: 'minmax(0, 1fr)', gridTemplateRows: 'minmax(0, 1fr)' }
  const renderWithRail = (content) => (
    <div className="grid h-full min-h-0" style={shellStyle}>
      <div className="flex min-h-0 min-w-0 flex-col">{content}</div>
    </div>
  )

  // Loading skeleton while fetching conversation — skip during active stream
  // or when optimistic messages are present, so the mid-stream GET that fires
  // right after a brand-new conversation is created doesn't tear down the
  // ChatWindow/StreamingTurn subtree (would otherwise read as a "page reload"
  // and the streamed chunks would render into a detached subtree).
  if (isLoadingConversation && !isStreaming && messages.length === 0) {
    // No fake header row: the global Header persists across the load, so the
    // chrome no longer swaps in/out. Just center the spinner.
    return renderWithRail(
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    )
  }

  // Error state when the conversation fetch fails — same guard as the loading
  // branch (skip during active stream / optimistic messages) so a mid-stream
  // GET failure doesn't tear down the live ChatWindow subtree.
  if (isConversationError && !isStreaming && messages.length === 0) {
    // No fake header row (global Header persists). Just the centered retry block.
    return renderWithRail(
      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-sm text-foreground-secondary">{t('common:errors.generic')}</p>
        <Button variant="outline" onClick={() => refetchConversation()}>
          <RefreshCw className="h-4 w-4 me-2" />
          {t('common:actions.retry')}
        </Button>
      </div>
    )
  }

  // Connection notice — rendered directly above the composer in both layout
  // branches, in the same 768px column. Two states:
  //  - offline: ambient warning while navigator.onLine is false (auto-clears)
  //  - failed send: inline error + Retry (resends the same payload — no
  //    retyping, no new chat) + Dismiss (restores text into the composer)
  const connectionNotice = (!isOnline || (streamError && !isStreaming)) && (
    <div className="px-3 md:px-4">
      <div className="mx-auto max-w-[768px]">
        {!isOnline ? (
          <div role="alert" className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 px-4 py-2.5 text-sm text-foreground">
            <WifiOff className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            <span>{t('connection.offline')}</span>
          </div>
        ) : (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-2 rounded-xl border border-error/30 bg-error/10 px-4 py-2 text-sm text-foreground"
          >
            <span className="flex min-w-0 items-center gap-2">
              <WifiOff className="h-4 w-4 shrink-0 text-error" aria-hidden="true" />
              <span className="min-w-0">
                {streamError.kind === 'network'
                  ? t('connection.lost')
                  : streamError.message || t('connection.sendFailed')}
              </span>
            </span>
            <span className="ms-auto flex shrink-0 items-center gap-1">
              <Button size="sm" variant="ghost" onClick={dismissFailedSend}>
                {t('connection.dismiss')}
              </Button>
              <Button size="sm" variant="outline" onClick={retryFailedSend}>
                <RefreshCw className="h-3.5 w-3.5 me-1.5" aria-hidden="true" />
                {t('common:actions.retry')}
              </Button>
            </span>
          </div>
        )}
      </div>
    </div>
  )

  // Single composer element reused across the empty/docked branches so its
  // props stay byte-identical (the alternative — duplicating the prop block —
  // drifts). The composer DOES remount on the empty→docked flip (different JSX
  // parent), which is acceptable: the flip happens at send, by which point
  // message/files/activeCommand are already cleared, and webSearch re-seeds from
  // localStorage. `key={composerRestore.key}` still drives the DLP-modal restore
  // remount, so "Modify" repopulates the composer from the centered state too.
  const composer = (
    <ChatInput
      key={composerRestore.key}
      onSend={(message, files, command, options) => {
        handleSendMessage(message, files, command, options)
      }}
      onFileUpload={handleFileUpload}
      onStop={() => handleStopGeneration(streamingMessageId)}
      isStreaming={isStreaming}
      disabled={!selectedConfigId}
      canvasEnabled={canvasEnabled}
      selectedConfig={selectedConfig}
      selectedConfigId={selectedConfigId}
      configs={configs}
      onSelectConfig={setSelectedConfigId}
      showModelPicker={isEmpty}
      initialMessage={composerRestore.text || composerPrefill}
      initialFiles={composerRestore.files}
    />
  )

  const composerColumn = (
    <div className="flex w-full flex-col gap-3">
      {!privacyDismissed && privacyMode && (
        <div className="px-3 md:px-4">
          <PrivacyBanner
            mode={privacyMode}
            onDismiss={dismissPrivacy}
            className="mx-auto max-w-[768px]"
          />
        </div>
      )}
      <DLPFirstRunNote />
      {connectionNotice}
      {composer}
    </div>
  )

  // Grid tracks for the full shell: [rail?] [content] [canvas?]. The rail track
  // only exists when the inline desktop rail is shown; the canvas track only when
  // Code Canvas is open on desktop (mobile canvas is a `fixed inset-0` overlay,
  // so it needs no track). Centering of the 768 thread happens INSIDE the content
  // column, so widening the content track never widens the reading lane.
  const canvasInlineTrack = codeCanvasOpen && !isNarrow ? ' auto' : ''
  const fullGridCols = `minmax(0, 1fr)${canvasInlineTrack}`

  return (
    <div className="grid h-full min-h-0" style={{ gridTemplateColumns: fullGridCols, gridTemplateRows: 'minmax(0, 1fr)' }}>
      <div className="flex min-h-0 min-w-0 flex-col">
        <ChatHeader
          conversation={conversation}
          onExportMarkdown={handleExportMarkdown}
          onExportJson={handleExportJson}
          onExportPdf={handleExportPdf}
          selectedConfig={selectedConfig}
          configs={configs}
          selectedConfigId={selectedConfigId}
          onSelectConfig={setSelectedConfigId}
          onConversationMoved={handleConversationMoved}
          onConversationRenamed={handleConversationRenamed}
        />
        {isEmpty ? (
          /* ChatGPT-signature fresh-chat layout: greeting + composer + cards as
             one vertically-centered block. ChatWindow is NOT rendered here. */
          /* Centering via my-auto on the child (NOT justify-center on this
             scroll container) — justify-center + overflow clips the top of
             over-tall content; auto margins center when there's room and
             degrade to normal scrolling when there isn't. */
          <div className="flex-1 min-h-0 overflow-y-auto flex flex-col py-8">
            <ChatEmptyState selectedConfig={selectedConfig}>
              {composerColumn}
            </ChatEmptyState>
          </div>
        ) : (
          <>
            <ChatWindow
              messages={messages}
              isStreaming={isStreaming}
              streamingContent={streamingContent}
              liveDataAnalysis={liveDataAnalysis}
              conversationId={conversationId}
              onEditMessage={handleEditMessage}
              onRegenerateMessage={handleRegenerateMessage}
              onFeedback={handleMessageFeedback}
              onRunCode={canvasEnabled ? handleRunCode : undefined}
              maxColumnWidth={768}
              showSenders={!!conversation?.share?.is_shared}
            />

            {composerColumn}

            {/* ChatGPT-style accuracy disclaimer — docked branch only (the
                centered empty state omits it). Outside the composer card,
                centered in the same column. dir="auto" keeps the Latin brand
                name correctly oriented inside the RTL Persian sentence. */}
            <p dir="auto" className="pb-2 text-center text-xs text-foreground-tertiary">
              {t('input.disclaimer')}
            </p>
          </>
        )}
      </div>

      {/* Code Canvas — standalone overlay panel docked to the inline-end edge.
          Sandbox is owned by CodeCanvas/CodePreview.jsx and stays at
          `sandbox="allow-scripts"` only (NO allow-same-origin per CLAUDE.md). */}
      {codeCanvasOpen && (
        <aside
          aria-label={t('codeCanvas.title')}
          // Consistent UI System: the docked Code Canvas is an in-flow content
          // column (md:static), so it's a FLAT surf2 surface with a border-inline
          // -start seam — not glass. The inline-start hairline mirrors in RTL.
          className="fixed inset-0 z-50 flex w-full flex-col border-s border-border bg-background-secondary md:static md:inset-auto md:z-auto md:h-full md:w-[440px] lg:w-[560px] xl:w-[660px] md:flex-shrink-0"
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-sm font-semibold text-foreground">
              {t('codeCanvas.title')}
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setCodeCanvasOpen(false)}
              aria-label={t('codeCanvas.close')}
              title={t('codeCanvas.close')}
              className="h-10 w-10 md:h-8 md:w-8"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">
            {/* Local boundary: an editor throw renders the friendly card INSIDE
                the panel (header + close above still work) instead of bubbling
                to the section-keyed boundary that blankets the whole chat. */}
            <ErrorBoundary>
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center">
                    <Loader2 className="h-6 w-6 animate-spin text-accent" />
                  </div>
                }
              >
                <CodeCanvas initialCode={codeCanvasCode} />
              </Suspense>
            </ErrorBoundary>
          </div>
        </aside>
      )}

      {/* DLP violation modal */}
      <DLPViolationModal
        isOpen={!!dlpModal}
        onClose={() => {
          if (dlpModal) {
            setComposerRestore((prev) => ({ text: dlpModal.text || '', files: dlpModal.attachments || [], key: prev.key + 1 }))
            dlpModal.resolve(false)
            setDlpModal(null)
          }
        }}
        onModify={() => {
          if (dlpModal) {
            setComposerRestore((prev) => ({ text: dlpModal.text || '', files: dlpModal.attachments || [], key: prev.key + 1 }))
            dlpModal.resolve(false)
            setDlpModal(null)
          }
        }}
        onRedactSend={() => { dlpModal?.resolve({ redact: true }); setDlpModal(null) }}
        matches={dlpModal?.matches || []}
        highestAction={dlpModal?.highestAction || 'warn'}
        redactedPreview={dlpModal?.redactedPreview || null}
        redactable={!!dlpModal?.redactable}
      />

      {/* Budget/credit exceeded modal */}
      {budgetModal}
    </div>
  )
}

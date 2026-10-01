import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Loader2, RefreshCw, BarChart3, Plus, FileSpreadsheet, FileDown,
  WifiOff, History, Search,
} from 'lucide-react'
import { chatService } from '../../services/chatService'
import { useProject } from '../../context/ProjectContext'
import ChatWindow from '../../components/chat/ChatWindow'
import { useChatMessages, useChatStream } from '../chat/hooks'
import { QUICK_MODEL_IDS } from '../../constants/models'
import { Button } from '../../components/ui/button'
import { IconTile } from '../../components/ui/icon-tile'
import HeaderSlot from '../../components/layout/HeaderSlot'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Input } from '../../components/ui/input'
import { Sheet, SheetContent, SheetTitle } from '../../components/ui/sheet'
import ConversationRow from '../../components/layout/sidebar/ConversationRow'
import { useConfirmDelete } from '../../hooks/useConfirmDelete'
import { useOnlineStatus } from '../../hooks/useOnlineStatus'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { cn } from '@/lib/utils'
import useDataConversations from '../../hooks/useDataConversations'
import { useBudgetBlock } from '../../hooks/useBudgetBlock'
import { buildDataReport, downloadMarkdown } from '../../utils/buildDataReport'
import DataComposer from './DataComposer'

const DATA_COMMAND = { intent: 'data' }

const STARTER_KEYS = [
  'starterSummarize',
  'starterMissing',
  'starterTopN',
  'starterChart',
]

/**
 * DataAnalyzerPage — always runs intent='data'.
 * Message area + composer stay siblings (anti-remount).
 */
export default function DataAnalyzerPage() {
  const { t, i18n } = useTranslation(['chat', 'layout', 'common'])
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { currentProject } = useProject()
  const projectId = currentProject?._id || null
  const isOnline = useOnlineStatus()
  const isLg = useMediaQuery('(min-width: 1024px)')
  const { confirm, confirmDialog } = useConfirmDelete()

  const [mobileRailOpen, setMobileRailOpen] = useState(false)
  const [composerRestore, setComposerRestore] = useState({ text: '', files: [], key: 0 })
  // Regenerate is REST (not live SSE tool frames) — show analyzing phase so the
  // UI doesn't look frozen while the server re-runs the tool loop.
  const [regenPhase, setRegenPhase] = useState(null)

  const selectedConfigId = useMemo(
    () => (QUICK_MODEL_IDS.length > 0 ? `quick:${QUICK_MODEL_IDS[0]}` : null),
    [],
  )

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
  })

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
    handleRegenerateMessage,
    handleMessageFeedback,
    handleFileUpload,
  } = useChatMessages({ conversationId, conversationData, queryClient })

  const onRegenerate = useCallback(
    async (messageId, configId = null) => {
      setRegenPhase('analyzing')
      try {
        await handleRegenerateMessage(messageId, configId)
      } finally {
        setRegenPhase(null)
      }
    },
    [handleRegenerateMessage],
  )

  const { handleBudgetError, budgetModal } = useBudgetBlock()

  const {
    handleSendMessage,
    handleStopGeneration,
    liveDataAnalysis,
    dataPhase,
    streamError,
    retryFailedSend,
    dismissStreamError,
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
    onCanvasIntent: () => {},
    projectId,
    onBudgetExceeded: handleBudgetError,
    conversationBasePath: '/data-analyzer',
  })

  const {
    search,
    setSearch,
    groups: pastGroups,
    pinned: pastPinned,
    conversations: pastConversations,
    isLoading: pastLoading,
    isError: pastError,
    refetch: refetchPast,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    activeConversationId,
    rename,
    togglePin,
    archive,
    remove,
  } = useDataConversations()

  const hasDataset = useMemo(
    () => messages.some((m) => m.role === 'user' && Array.isArray(m.attachments) && m.attachments.length > 0),
    [messages],
  )

  // Labels for sticky dataset strip (latest user turn with files).
  const datasetLabels = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i]
      if (m.role === 'user' && Array.isArray(m.attachments) && m.attachments.length > 0) {
        return m.attachments
          .map((a) => a.name || a.filename || a.original_name)
          .filter(Boolean)
      }
    }
    return []
  }, [messages])

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

  const pickStarter = useCallback((text) => {
    setComposerRestore((prev) => ({
      text,
      files: prev.files || [],
      key: prev.key + 1,
    }))
  }, [])

  const handleDelete = useCallback(
    async (conv) => {
      if (
        await confirm({
          title: t('layout:conversationList.deleteTitle'),
          description: t('layout:conversationList.deleteDescription'),
          destructive: true,
        })
      ) {
        remove(conv)
      }
    },
    [confirm, remove, t],
  )

  const didMountProjectRef = useRef(false)
  useEffect(() => {
    if (!didMountProjectRef.current) {
      didMountProjectRef.current = true
      return
    }
    queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }, [projectId, queryClient])

  const onSend = (text, fileList) => {
    handleSendMessage(text, fileList, DATA_COMMAND, {})
  }

  const showLoading = isLoadingConversation && !isStreaming && messages.length === 0
  const showError = isConversationError && !isStreaming && messages.length === 0
  const isEmpty = messages.length === 0 && !isStreaming

  const connectionNotice = (!isOnline || (streamError && !isStreaming)) && (
    <div className="px-3 md:px-4">
      <div className="mx-auto mb-2 max-w-[768px]">
        {!isOnline ? (
          <div className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 px-4 py-2.5 text-sm text-foreground">
            <WifiOff className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            <span>{t('chat:connection.offline')}</span>
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
                  ? t('chat:connection.lost')
                  : streamError.message || t('chat:connection.sendFailed')}
              </span>
            </span>
            <span className="ms-auto flex items-center gap-1">
              <Button size="sm" variant="ghost" onClick={dismissFailedSend}>
                {t('chat:connection.dismiss')}
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

  const railBody = (
    <DataRailBody
      t={t}
      search={search}
      setSearch={setSearch}
      pastLoading={pastLoading}
      pastError={pastError}
      refetchPast={refetchPast}
      pastConversations={pastConversations}
      pastPinned={pastPinned}
      pastGroups={pastGroups}
      activeConversationId={activeConversationId}
      rename={rename}
      togglePin={togglePin}
      archive={archive}
      handleDelete={handleDelete}
      hasNextPage={hasNextPage}
      fetchNextPage={fetchNextPage}
      isFetchingNextPage={isFetchingNextPage}
      onNavClick={() => setMobileRailOpen(false)}
    />
  )

  return (
    <div className="flex h-full">
      {/* Desktop rail */}
      <aside className="hidden lg:flex w-64 shrink-0 flex-col border-e border-border bg-background-secondary min-h-0">
        {railBody}
      </aside>

      {/* Mobile history sheet */}
      {!isLg && (
        <Sheet open={mobileRailOpen} onOpenChange={setMobileRailOpen}>
          <SheetContent
            side="start"
            className="flex w-[85vw] max-w-[20rem] flex-col gap-0 p-0 pt-[var(--safe-top)] pb-[var(--safe-bottom)]"
          >
            <SheetTitle className="sr-only">{t('chat:dataAnalyzer.pastAnalyses')}</SheetTitle>
            {railBody}
          </SheetContent>
        </Sheet>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <HeaderSlot side="start">
          <div className="flex min-w-0 items-center gap-2.5">
            <IconTile icon={BarChart3} tone="amber" size="md" />
            <span className="truncate text-[15px] font-bold leading-tight tracking-[-0.01em] text-foreground">
              {t('chat:dataAnalyzer.title')}
            </span>
          </div>
        </HeaderSlot>
        <HeaderSlot side="end">
          <div className="flex items-center gap-2">
            <PrivacyBadge mode="cloud" />
            {messages?.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const title = t('chat:dataAnalyzer.reportTitle')
                  const fname = i18n.language?.startsWith('fa')
                    ? 'گزارش-تحلیل-داده'
                    : 'data-analysis'
                  downloadMarkdown(buildDataReport(messages, { title }), fname)
                }}
              >
                <FileDown className="h-4 w-4 me-1.5" />
                {t('chat:dataAnalyzer.downloadReport')}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              className="lg:hidden"
              onClick={() => setMobileRailOpen(true)}
              aria-label={t('chat:dataAnalyzer.pastAnalyses')}
            >
              <History className="h-4 w-4 me-1.5" />
              {t('chat:dataAnalyzer.history')}
            </Button>
            <Button asChild variant="outline" size="sm" className="lg:hidden">
              <Link to="/data-analyzer">
                <Plus className="h-4 w-4 me-1.5" />
                {t('chat:dataAnalyzer.newAnalysis')}
              </Link>
            </Button>
          </div>
        </HeaderSlot>

        <div className="shrink-0 px-3 pt-2 md:px-4">
          <PrivacyBanner mode="cloud" className="mx-auto max-w-[768px]" />
        </div>

        <div className="flex-1 flex flex-col min-h-0">
          {showLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-accent" />
            </div>
          ) : showError ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 text-center">
              <p className="text-sm text-foreground-secondary">{t('common:errors.generic')}</p>
              <Button variant="outline" onClick={() => refetchConversation()}>
                <RefreshCw className="h-4 w-4 me-2" />
                {t('common:actions.retry')}
              </Button>
            </div>
          ) : isEmpty ? (
            <DataEmptyState t={t} onPickStarter={pickStarter} />
          ) : (
            <ChatWindow
              messages={messages}
              isStreaming={isStreaming || !!regenPhase}
              streamingContent={streamingContent}
              liveDataAnalysis={liveDataAnalysis}
              dataPhase={dataPhase || regenPhase}
              conversationId={conversationId}
              onEditMessage={handleEditMessage}
              onRegenerateMessage={onRegenerate}
              onFeedback={handleMessageFeedback}
              maxColumnWidth={1024}
              dataMode
            />
          )}

          {connectionNotice}

          <DataComposer
            key={composerRestore.key}
            onSend={onSend}
            onFileUpload={handleFileUpload}
            onStop={() => handleStopGeneration(streamingMessageId)}
            isStreaming={isStreaming}
            disabled={!selectedConfigId}
            hasDataset={hasDataset}
            datasetLabels={datasetLabels}
            initialMessage={composerRestore.text}
            initialFiles={composerRestore.files}
          />

          <p dir="auto" className="pb-2 text-center text-xs text-foreground-tertiary">
            {t('chat:dataAnalyzer.disclaimer')}
          </p>
        </div>
      </div>
      {budgetModal}
      {confirmDialog}
    </div>
  )
}

function DataRailBody({
  t,
  search,
  setSearch,
  pastLoading,
  pastError,
  refetchPast,
  pastConversations,
  pastPinned,
  pastGroups,
  activeConversationId,
  rename,
  togglePin,
  archive,
  handleDelete,
  hasNextPage,
  fetchNextPage,
  isFetchingNextPage,
  onNavClick,
}) {
  const scrollRef = useRef(null)
  const sentinelRef = useRef(null)

  useEffect(() => {
    const root = scrollRef.current
    const target = sentinelRef.current
    if (!root || !target || !hasNextPage) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { root, rootMargin: '120px' },
    )
    io.observe(target)
    return () => io.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  return (
    <>
      <div className="p-3">
        <Button asChild className="w-full gap-2 h-11">
          <Link
            to="/data-analyzer"
            aria-label={t('chat:dataAnalyzer.newAnalysis')}
            onClick={onNavClick}
          >
            <Plus className="h-5 w-5" />
            {t('chat:dataAnalyzer.newAnalysis')}
          </Link>
        </Button>
      </div>

      <div className="px-3 pb-1.5">
        <div className="relative">
          <Search className="pointer-events-none absolute inset-y-0 start-3 my-auto h-4 w-4 text-foreground-tertiary" />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('layout:conversationList.searchPlaceholder')}
            aria-label={t('layout:conversationList.searchPlaceholder')}
            className="ps-9 !min-h-[38px]"
          />
        </div>
      </div>

      <div className="px-3 pb-1 text-[11px] font-bold uppercase tracking-wide text-foreground-tertiary">
        {t('chat:dataAnalyzer.pastAnalyses')}
      </div>

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-2 pb-3">
        {pastLoading ? (
          <div className="flex justify-center py-6">
            <Loader2 className="h-4 w-4 animate-spin text-accent" />
          </div>
        ) : pastError ? (
          <div className="px-2 py-6 text-center">
            <p className="mb-2 text-xs text-foreground-tertiary">
              {t('layout:conversationList.loadError')}
            </p>
            <Button variant="ghost" size="sm" onClick={() => refetchPast()}>
              {t('layout:conversationList.retry')}
            </Button>
          </div>
        ) : pastConversations.length === 0 ? (
          <p className="px-2 py-4 text-xs text-foreground-tertiary">
            {search
              ? t('layout:conversationList.noResults')
              : t('chat:dataAnalyzer.noPastAnalyses')}
          </p>
        ) : (
          <>
            <RailList
              pinned={pastPinned}
              groups={pastGroups}
              activeId={activeConversationId}
              t={t}
              onNavClick={onNavClick}
              onRename={rename}
              onTogglePin={togglePin}
              onArchive={archive}
              onDelete={handleDelete}
            />
            <div ref={sentinelRef} className="h-4" aria-hidden="true" />
            {isFetchingNextPage && (
              <div className="flex justify-center py-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}

function DataEmptyState({ t, onPickStarter }) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center justify-center px-6 text-center">
      <div className="flex flex-col items-center gap-4 max-w-[520px]">
        <IconTile icon={FileSpreadsheet} tone="amber" size="lg" />
        <h2 className="text-xl md:text-2xl font-semibold text-foreground">
          {t('chat:dataAnalyzer.emptyTitle')}
        </h2>
        <p className="text-sm text-foreground-secondary">
          {t('chat:dataAnalyzer.emptyHint')}
        </p>
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          {STARTER_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => onPickStarter?.(t(`chat:dataAnalyzer.${key}`))}
              className={cn(
                'rounded-full border border-border bg-background-secondary px-3 py-1.5',
                'text-xs text-foreground-secondary transition-colors',
                'hover:border-accent/40 hover:bg-accent/5 hover:text-foreground',
              )}
            >
              {t(`chat:dataAnalyzer.${key}`)}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-foreground-tertiary">
          {t('chat:dataAnalyzer.formatsHint')}
        </p>
      </div>
    </div>
  )
}

function RailList({
  pinned,
  groups,
  activeId,
  t,
  onNavClick,
  onRename,
  onTogglePin,
  onArchive,
  onDelete,
}) {
  return (
    <div className="flex flex-col gap-1">
      {pinned.length > 0 && (
        <RailGroup
          label={t('layout:conversationList.pinned')}
          items={pinned}
          activeId={activeId}
          onNavClick={onNavClick}
          onRename={onRename}
          onTogglePin={onTogglePin}
          onArchive={onArchive}
          onDelete={onDelete}
        />
      )}
      {groups.map((g) => (
        <RailGroup
          key={g.key}
          label={g.label ?? t(`layout:conversationList.${bucketKeyToI18n(g.key)}`)}
          items={g.items}
          activeId={activeId}
          onNavClick={onNavClick}
          onRename={onRename}
          onTogglePin={onTogglePin}
          onArchive={onArchive}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}

function RailGroup({
  label,
  items,
  activeId,
  onNavClick,
  onRename,
  onTogglePin,
  onArchive,
  onDelete,
}) {
  return (
    <div>
      <div className="px-2 pb-1 text-[11px] font-bold uppercase tracking-wide text-foreground-tertiary">
        {label}
      </div>
      <ul className="flex flex-col">
        {items.map((conv) => (
          <ConversationRow
            key={conv._id}
            conversation={conv}
            active={conv._id === activeId}
            hrefBase="/data-analyzer"
            onNavClick={onNavClick}
            onRename={onRename}
            onTogglePin={onTogglePin}
            onArchive={onArchive}
            onDelete={onDelete}
          />
        ))}
      </ul>
    </div>
  )
}

function bucketKeyToI18n(key) {
  switch (key) {
    case 'today': return 'today'
    case 'yesterday': return 'yesterday'
    case 'prev7': return 'previous7Days'
    case 'prev30': return 'previous30Days'
    default: return key
  }
}

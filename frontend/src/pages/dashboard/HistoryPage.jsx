import { useState, useMemo, useEffect, memo } from 'react'
import { useQuery, useInfiniteQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Search,
  MessageSquare,
  Clock,
  Archive,
  Trash2,
  MoreVertical,
  FileText,
  User,
  Bot,
} from 'lucide-react'
import { chatService } from '../../services/chatService'
import { useProject } from '../../context/ProjectContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import { fmtDate } from '../../utils/dateLocale'
import { fmtNumber } from '../../utils/persianLocale'
import { cn } from '../../utils/cn'
import toast from 'react-hot-toast'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import EmptyState from '@/components/ui/empty-state'
import { StaggerContainer, StaggerItem } from '@/components/ui/animated-container'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'

function useDebouncedValue(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export default function HistoryPage() {
  const { t } = useTranslation('dashboard')
  const navigate = useNavigate()
  const { currentProject } = useProject()
  const { currentWorkspace } = useWorkspace()
  const [searchQuery, setSearchQuery] = useState('')
  // Debounce the value used for network search; the input stays bound to the
  // immediate searchQuery so typing remains responsive.
  const debouncedQuery = useDebouncedValue(searchQuery, 350)
  const [searchInMessages, setSearchInMessages] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [scope, setScope] = useState('project')

  // Only filter by project_id when scope='project' AND a project is actually
  // selected. Previously this sent the literal string "null" which the backend
  // strict-matches against {project_id: null}, hiding every chat that has a
  // real project_id. With no project active, fall through to "all" scope.
  const projectFilterParam = (scope === 'project' && currentProject?._id) || undefined

  // Page-based infinite query: every filter/scope/workspace change is part of
  // the queryKey, so React Query swaps to a fresh cache entry that starts back
  // at page 1 (BUG: filter/scope changes no longer leave a stale page hiding
  // results). "Load more" appends via fetchNextPage instead of replacing the
  // list (BUG: page N+1 used to overwrite earlier pages).
  const {
    data,
    isLoading,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['conversations-history', showArchived, scope, currentProject?._id, currentWorkspace?._id],
    queryFn: ({ pageParam }) => chatService.getConversations({
      archived: showArchived,
      page: pageParam,
      limit: 20,
      ...(projectFilterParam ? { project_id: projectFilterParam } : {}),
    }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage?.has_more ? (lastPage.page || 1) + 1 : undefined,
  })

  const { data: messageSearchData, isLoading: isSearchingMessages } = useQuery({
    queryKey: ['message-search', debouncedQuery],
    queryFn: () => chatService.searchMessages(debouncedQuery),
    enabled: searchInMessages && debouncedQuery.length >= 2,
  })

  const conversations = useMemo(
    () => (data?.pages || []).flatMap(p => p.conversations || []),
    [data]
  )
  // total reflects the full backend count, not just loaded rows.
  const total = data?.pages?.[0]?.total || 0
  const hasMore = hasNextPage

  const filteredConversations = useMemo(() => {
    if (!searchQuery || searchInMessages) return conversations
    return conversations.filter(conv =>
      conv.title?.toLowerCase().includes(searchQuery.toLowerCase())
    )
  }, [conversations, searchQuery, searchInMessages])

  const groupedMessageResults = useMemo(() => {
    if (!messageSearchData?.results) return []

    const groups = {}
    messageSearchData.results.forEach(msg => {
      const convId = msg.conversation_id
      if (!groups[convId]) {
        groups[convId] = {
          conversationId: convId,
          conversationTitle: msg.conversation_title,
          messages: []
        }
      }
      groups[convId].messages.push(msg)
    })

    return Object.values(groups)
  }, [messageSearchData])

  const highlightMatch = (text, query) => {
    if (!query || query.length < 2) return text

    const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
    return parts.map((part, i) =>
      part.toLowerCase() === query.toLowerCase()
        ? <mark key={i} className="bg-accent-muted text-foreground px-0.5 rounded">{part}</mark>
        : part
    )
  }

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter' && searchInMessages && searchQuery.length < 2) {
      toast.error(t('history.minCharsToSearch'))
    }
  }

  return (
    <PageShell width="wide">
      <PageHeader
        icon={Archive}
        title={t('history.title')}
        subtitle={t('history.totalConversations_other', { count: total })}
      />

        <div className="space-y-3">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative w-full max-w-md">
              <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-foreground-tertiary" />
              <Input
                type="text"
                placeholder={searchInMessages ? t('history.searchMessagesPlaceholder') : t('history.searchTitlesPlaceholder')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={handleSearchKeyDown}
                className="ps-9"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => setSearchInMessages(!searchInMessages)}
                variant={searchInMessages ? 'default' : 'secondary'}
                className="gap-2 whitespace-nowrap"
              >
                <FileText className="h-4 w-4" />
                {searchInMessages ? t('history.searchMessages') : t('history.searchTitles')}
              </Button>
              <Button
                onClick={() => setShowArchived(!showArchived)}
                variant={showArchived ? 'default' : 'secondary'}
                className="gap-2"
              >
                <Archive className="h-4 w-4" />
                {showArchived ? t('history.archived') : t('history.active')}
              </Button>
              <Button
                onClick={() => setScope(scope === 'project' ? 'all' : 'project')}
                variant={scope === 'project' ? 'default' : 'secondary'}
                className="gap-2 min-w-0"
                aria-pressed={scope === 'project'}
                title={scope === 'project' ? t('history.scopeFilterProjectTip') : t('history.scopeFilterAllTip')}
              >
                <span className="truncate">
                  {scope === 'project'
                    ? (currentProject?.name || t('history.unfiled'))
                    : t('history.allScopes')}
                </span>
              </Button>
            </div>
          </div>

          {searchInMessages && searchQuery && (
            <p className="text-sm text-foreground-secondary">
              {isSearchingMessages
                ? t('history.searching')
                : t('history.foundMessages', { count: messageSearchData?.total || 0, query: debouncedQuery })}
            </p>
          )}

          {/* Title search runs client-side over loaded pages only. When more
              pages exist the filter is incomplete, so label the scope honestly
              and point users at the server-side message search. */}
          {!searchInMessages && searchQuery && hasMore && (
            <p className="text-sm text-foreground-secondary">
              {t('history.searchTitlesScopeNote')}
            </p>
          )}
        </div>

        {searchInMessages && debouncedQuery.length >= 2 ? (
          isSearchingMessages ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
          ) : groupedMessageResults.length === 0 ? (
            <div className="text-center py-12">
              <Search className="h-12 w-12 text-foreground-tertiary mx-auto mb-3" />
              <h3 className="text-lg font-medium text-foreground mb-1">{t('history.noMessagesFound')}</h3>
              <p className="text-foreground-secondary">
                {t('history.noMessagesFoundDesc')}
              </p>
            </div>
          ) : (
            <div className="space-y-4 max-w-3xl">
              {groupedMessageResults.map((group) => (
                <Card key={group.conversationId} className="p-4">
                  <div
                    className="flex items-center gap-2 pb-3 border-b border-border cursor-pointer hover:text-accent transition-colors"
                    onClick={() => navigate(`/chat/${group.conversationId}`)}
                  >
                    <MessageSquare className="h-4 w-4 text-accent" />
                    <span className="font-medium text-foreground">
                      {group.conversationTitle || t('history.untitled')}
                    </span>
                    <span className="text-sm text-foreground-tertiary">
                      {t('history.matchCount_other', { count: group.messages.length })}
                    </span>
                  </div>
                  <div className="space-y-2 pt-3">
                    {group.messages.slice(0, 3).map((msg) => (
                      <MessageSearchResult
                        key={msg._id}
                        message={msg}
                        query={debouncedQuery}
                        highlightMatch={highlightMatch}
                        onClick={() => navigate(`/chat/${group.conversationId}`)}
                      />
                    ))}
                    {group.messages.length > 3 && (
                      <Button
                        variant="link"
                        onClick={() => navigate(`/chat/${group.conversationId}`)}
                        className="text-sm text-accent hover:underline p-0 h-auto"
                      >
                        {t('history.viewMoreMatches', { count: group.messages.length - 3 })}
                      </Button>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )
        ) : (
          <>
            {isLoading ? (
              <div className="space-y-3">
                {[1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} className="h-20 rounded-xl" />
                ))}
              </div>
            ) : filteredConversations.length === 0 ? (
              searchQuery ? (
                <EmptyState
                  icon={MessageSquare}
                  title={t('history.noMatchesFound')}
                  description={t('history.tryDifferentTerm')}
                />
              ) : showArchived ? (
                <EmptyState
                  icon={MessageSquare}
                  title={t('history.noConversationsFound')}
                  description={t('history.noArchivedConversations')}
                />
              ) : scope === 'project' ? (
                <EmptyState
                  icon={MessageSquare}
                  title={t('history.noConversationsFound')}
                  description={t('history.noConversationsInScope', { scope: currentProject?.name || t('history.unfiled') })}
                  primaryCta={{
                    label: t('history.switchToAllScopes'),
                    onClick: () => setScope('all'),
                  }}
                />
              ) : (
                <EmptyState
                  icon={MessageSquare}
                  icon3d="/icons/3d/chat.png"
                  title={t('historyEmptyState.title')}
                  description={t('historyEmptyState.description')}
                  primaryCta={{
                    label: t('historyEmptyState.cta'),
                    onClick: () => navigate('/chat'),
                  }}
                />
              )
            ) : (
              <StaggerContainer className="grid grid-cols-1 gap-2 lg:grid-cols-2 2xl:grid-cols-3">
                {filteredConversations.map((conv) => (
                  <StaggerItem key={conv._id} className="h-full">
                    <ConversationCard conversation={conv} onUpdate={refetch} />
                  </StaggerItem>
                ))}
              </StaggerContainer>
            )}

            {hasMore && (
              <div className="flex justify-center pt-4">
                <Button
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                  variant="secondary"
                >
                  {t('history.loadMore')}
                </Button>
              </div>
            )}
          </>
        )}
    </PageShell>
  )
}

function MessageSearchResult({ message, query, highlightMatch, onClick }) {
  const { t } = useTranslation('dashboard')

  // Snippet slicing + regex highlight only depend on the message content and
  // the (debounced) query — memoize so unrelated parent re-renders don't
  // rebuild the regex/snippet for every result row.
  const highlightedSnippet = useMemo(() => {
    const content = message.content
    const lowerContent = content.toLowerCase()
    const lowerQuery = query.toLowerCase()
    const matchIndex = lowerContent.indexOf(lowerQuery)

    let snippet
    if (matchIndex === -1) {
      snippet = content.slice(0, 200)
    } else {
      const start = Math.max(0, matchIndex - 50)
      const end = Math.min(content.length, matchIndex + query.length + 100)
      snippet = content.slice(start, end)
      if (start > 0) snippet = '...' + snippet
      if (end < content.length) snippet = snippet + '...'
    }

    return highlightMatch(snippet, query)
    // highlightMatch is a stable-logic parent fn (new identity each render);
    // its output depends only on snippet text + query, both tracked here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message.content, query])

  const roleLabel = message.role === 'user'
    ? t('history.roleUser')
    : message.role === 'assistant'
      ? t('history.roleAssistant')
      : message.role

  return (
    <div
      className="p-3 rounded-lg bg-background-tertiary hover:bg-background-elevated cursor-pointer transition-colors"
      onClick={onClick}
    >
      <div className="flex items-center gap-2 mb-1">
        {message.role === 'user' ? (
          <User className="h-3 w-3 text-foreground-tertiary" />
        ) : (
          <Bot className="h-3 w-3 text-accent" />
        )}
        <span className="text-xs text-foreground-tertiary">{roleLabel}</span>
        <span className="text-xs text-foreground-tertiary">•</span>
        <span className="text-xs text-foreground-tertiary">
          {fmtDate(new Date(message.created_at), 'MMM d, yyyy')}
        </span>
      </div>
      <p className="text-sm text-foreground-secondary line-clamp-2">
        {highlightedSnippet}
      </p>
    </div>
  )
}

const ConversationCard = memo(function ConversationCard({ conversation, onUpdate }) {
  const { t } = useTranslation('dashboard')
  const { confirm, confirmDialog } = useConfirmDelete()

  const handleDelete = async () => {
    const ok = await confirm({
      title: t('history.deleteConversation.title'),
      description: t('history.deleteConversation.message'),
      confirmLabel: t('history.deleteConversation.confirm'),
      cancelLabel: t('history.deleteConversation.cancel'),
      destructive: true,
    })
    if (!ok) return
    try {
      await chatService.deleteConversation(conversation._id)
      onUpdate()
      toast.success(t('history.conversationDeleted'))
    } catch (error) {
      toast.error(t('history.failedToDelete'))
    }
  }

  const handleArchive = async () => {
    try {
      await chatService.archiveConversation(conversation._id)
      onUpdate()
      toast.success(conversation.is_archived ? t('history.conversationUnarchived') : t('history.conversationArchived'))
    } catch (error) {
      toast.error(t('history.failedToUpdate'))
    }
  }

  return (
    <Card className="h-full p-4 hover:border-border-light transition-colors group">
      <div className="flex items-center justify-between">
        <Link
          to={`/chat/${conversation._id}`}
          className="flex items-center gap-3 flex-1 min-w-0"
        >
          <div className="h-10 w-10 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0">
            <MessageSquare className="h-5 w-5 text-accent" />
          </div>
          <div className="min-w-0">
            <p className="font-medium text-foreground truncate">
              {conversation.title || t('history.untitled')}
            </p>
            <div className="flex items-center gap-3 text-sm text-foreground-secondary">
              <span>{t('history.messages', { count: conversation.message_count || 0, display: fmtNumber(conversation.message_count || 0) })}</span>
              <span className="text-foreground-tertiary">•</span>
              <span>{t('history.tokens', { count: conversation.token_count?.total || 0, display: fmtNumber(conversation.token_count?.total || 0) })}</span>
            </div>
          </div>
        </Link>

        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1 text-sm text-foreground-tertiary">
            <Clock className="h-4 w-4" />
            {fmtDate(new Date(conversation.last_message_at || conversation.created_at), 'MMM d')}
          </div>

          {conversation.tags?.length > 0 && (
            <div className="hidden sm:flex gap-1">
              {conversation.tags.slice(0, 2).map((tag) => (
                <Badge key={tag} variant="default">
                  {tag}
                </Badge>
              ))}
            </div>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-foreground-tertiary hover:text-foreground opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem onClick={handleArchive}>
                <Archive className="h-4 w-4 me-2" />
                {conversation.is_archived ? t('history.unarchive') : t('history.archive')}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={handleDelete}
                className="text-error focus:text-error"
              >
                <Trash2 className="h-4 w-4 me-2" />
                {t('history.delete')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {confirmDialog}
    </Card>
  )
})

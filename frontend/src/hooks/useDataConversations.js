import { useCallback, useMemo, useState } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, matchPath } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { chatService } from '../services/chatService'
import { useWorkspace } from '../context/WorkspaceContext'
import useDebouncedValue from './useDebouncedValue'
import { bucketConversations } from '../components/layout/sidebar/useSidebarConversations'

const PAGE_SIZE = 20

/**
 * Data layer for the Data Analyzer page's "past analyses" rail.
 *
 * A focused sibling of useSidebarConversations: same infinite-scroll +
 * date-bucket shape, but scoped to data-kind conversations only
 * (`kind: 'data'`). The backend filters these via `GET /conversations?kind=data`
 * (a conversation created through the intent='data' flow is auto-stamped
 * `kind='data'` server-side), so this list never mixes in ordinary chats.
 *
 * Cache-key contract: `['conversations', workspaceId, projectId, search, 'data']`
 * — the `'data'` discriminator is LAST on purpose. The whole app patches the
 * `['conversations']` PREFIX (title updates, rename/pin/archive) via filter-form
 * `setQueriesData`, which matches by prefix; keeping `'data'` at the tail means
 * those patches still reach these entries without a dedicated writer, while the
 * distinct key prevents the data list and the chat sidebar from sharing a cache
 * bucket (which would cross-contaminate their differently-filtered pages).
 *
 * Return contract mirrors useSidebarConversations (kept stable for the list
 * component): { search, setSearch, pinned, groups, conversations, isLoading,
 * isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage,
 * activeConversationId, rename, togglePin, archive, remove }.
 */
export default function useDataConversations() {
  const { t } = useTranslation('layout')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const { currentWorkspace } = useWorkspace()

  const workspaceId = currentWorkspace?._id || null

  // The list mounts on the page (inside the route), but match the live pathname
  // for the active-highlight regardless — same idiom as the sidebar hook so the
  // open analysis stays highlighted across param-only navigations.
  const activeConversationId =
    matchPath('/data-analyzer/:conversationId', location.pathname)?.params?.conversationId ?? null

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 350)

  const {
    data,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    // `'data'` discriminator LAST — see the cache-key contract above. The project
    // slot is PINNED to 'personal' (not the active project): the Data Analyzer is
    // a personal tool — its stream creates every conversation in personal/NULL
    // scope (chat.py stamps kind='data' with no project_id) — so scoping the rail
    // to the active team/company project would hide all of the user's analyses
    // whenever a project is active. Always query personal scope.
    queryKey: ['conversations', workspaceId, 'unfiled', debouncedSearch, 'data'],
    queryFn: ({ pageParam }) =>
      chatService.getConversations({
        page: pageParam,
        limit: PAGE_SIZE,
        kind: 'data',
        // 'null' = personal-scope sentinel (owner-only). Matches how data
        // conversations are persisted (project_id IS NULL).
        project_id: 'null',
        workspace_id: workspaceId,
        ...(debouncedSearch ? { search: debouncedSearch } : {}),
      }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last?.has_more ? (last.page || 1) + 1 : undefined),
    enabled: !!workspaceId,
  })

  const conversations = useMemo(
    () => (data?.pages || []).flatMap((p) => p.conversations || []),
    [data],
  )

  const pinned = useMemo(() => conversations.filter((c) => c.is_pinned), [conversations])
  const groups = useMemo(
    () => bucketConversations(conversations.filter((c) => !c.is_pinned)),
    [conversations],
  )

  // Optimistic cache helpers over every scoped ['conversations', ...] entry
  // (infinite-query shape). Identical to the sidebar hook so a rename/pin/delete
  // here also reflects in the chat sidebar's cache where the row is shared.
  const patchRow = useCallback(
    (id, patch) => {
      queryClient.setQueriesData({ queryKey: ['conversations'] }, (old) => {
        if (!old?.pages) return old
        return {
          ...old,
          pages: old.pages.map((p) => ({
            ...p,
            conversations: (p.conversations || []).map((c) =>
              c._id === id ? { ...c, ...patch } : c,
            ),
          })),
        }
      })
    },
    [queryClient],
  )

  const removeRow = useCallback(
    (id) => {
      queryClient.setQueriesData({ queryKey: ['conversations'] }, (old) => {
        if (!old?.pages) return old
        return {
          ...old,
          pages: old.pages.map((p) => ({
            ...p,
            conversations: (p.conversations || []).filter((c) => c._id !== id),
          })),
        }
      })
    },
    [queryClient],
  )

  const rename = useCallback(
    async (id, title) => {
      patchRow(id, { title })
      queryClient.setQueryData(['conversation', id], (old) =>
        old ? { ...old, conversation: { ...old.conversation, title } } : old,
      )
      try {
        await chatService.updateConversation(id, { title })
        toast.success(t('conversationList.renamed'))
      } catch (err) {
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
        toast.error(t('conversationList.actionFailed'))
      }
    },
    [patchRow, queryClient, t],
  )

  const togglePin = useCallback(
    async (conv) => {
      const next = !conv.is_pinned
      patchRow(conv._id, { is_pinned: next })
      try {
        await chatService.updateConversation(conv._id, { is_pinned: next })
        toast.success(t(next ? 'conversationList.pinnedToast' : 'conversationList.unpinnedToast'))
      } catch (err) {
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
        toast.error(t('conversationList.actionFailed'))
      }
    },
    [patchRow, queryClient, t],
  )

  const archive = useCallback(
    async (conv) => {
      removeRow(conv._id)
      try {
        await chatService.archiveConversation(conv._id)
        toast.success(t('conversationList.archived'))
        if (conv._id === activeConversationId) navigate('/data-analyzer')
      } catch (err) {
        toast.error(t('conversationList.actionFailed'))
      }
    },
    [removeRow, navigate, activeConversationId, t],
  )

  const remove = useCallback(
    async (conv) => {
      removeRow(conv._id)
      try {
        await chatService.deleteConversation(conv._id)
        toast.success(t('conversationList.deleted'))
        if (conv._id === activeConversationId) navigate('/data-analyzer')
      } catch (err) {
        toast.error(t('conversationList.actionFailed'))
      }
    },
    [removeRow, navigate, activeConversationId, t],
  )

  return {
    search,
    setSearch,
    pinned,
    groups,
    conversations,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    activeConversationId,
    rename,
    togglePin,
    archive,
    remove,
  }
}

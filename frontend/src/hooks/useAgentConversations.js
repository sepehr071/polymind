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

/** Rail list for /agent — conversations with kind='agent'. */
export default function useAgentConversations() {
  const { t } = useTranslation('layout')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const { currentWorkspace } = useWorkspace()

  const workspaceId = currentWorkspace?._id || null
  const activeConversationId =
    matchPath('/agent/:conversationId', location.pathname)?.params?.conversationId ?? null

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
    queryKey: ['conversations', workspaceId, 'unfiled', debouncedSearch, 'agent'],
    queryFn: ({ pageParam }) =>
      chatService.getConversations({
        page: pageParam,
        limit: PAGE_SIZE,
        kind: 'agent',
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
      try {
        await chatService.updateConversation(id, { title })
      } catch {
        toast.error(t('common:error', { defaultValue: 'Failed' }))
        refetch()
      }
    },
    [patchRow, refetch, t],
  )

  const togglePin = useCallback(
    async (id, isPinned) => {
      patchRow(id, { is_pinned: !isPinned })
      try {
        await chatService.updateConversation(id, { is_pinned: !isPinned })
      } catch {
        refetch()
      }
    },
    [patchRow, refetch],
  )

  const remove = useCallback(
    async (id) => {
      removeRow(id)
      if (activeConversationId === id) navigate('/agent')
      try {
        await chatService.deleteConversation(id)
      } catch {
        refetch()
      }
    },
    [removeRow, activeConversationId, navigate, refetch],
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
    remove,
  }
}

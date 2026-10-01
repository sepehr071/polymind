import { useCallback, useMemo, useState } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, matchPath } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { chatService } from '../../../services/chatService'
import { useWorkspace } from '../../../context/WorkspaceContext'
import { useProject } from '../../../context/ProjectContext'
import useDebouncedValue from '../../../hooks/useDebouncedValue'
import { fmtDate } from '../../../utils/dateLocale'

const PAGE_SIZE = 20

/**
 * Surgically bump a conversation to the top of the sidebar list and patch its
 * recency fields, WITHOUT refetching any pages.
 *
 * The sidebar cache is a set of scoped `['conversations', wsId, projectId,
 * search]` useInfiniteQuery entries, each shaped `{ pages: [{ conversations:
 * [...] }], pageParams }` (repo cache contract). This walks every such entry
 * via filter-form `setQueriesData`, finds the row by id across all pages,
 * applies `patch`, and — when found in any page after the first — splices it to
 * the front of `pages[0]` so it leads the newest-first list (the only reorder
 * the buckets need; `bucketConversations` re-derives groups from
 * `last_message_at`).
 *
 * Reorder is confined to already-cached pages: a row living on page 3 moves to
 * the head of page 1, never pulling in uncached rows. If the conversation is
 * absent from a given cache entry (e.g. filtered out by an active search box),
 * that entry is left untouched here; the caller is responsible for the
 * cache-miss fallback (a scoped invalidate) so a hidden row still surfaces once
 * its filter clears.
 *
 * @returns {boolean} true if the row was found in at least one cache entry.
 */
export function touchConversationInCache(queryClient, convId, patch = {}) {
  let foundAnywhere = false
  queryClient.setQueriesData({ queryKey: ['conversations'] }, (old) => {
    if (!old?.pages) return old

    // Locate the row and its page so we can both patch and lift it to the top.
    let found = null
    for (const page of old.pages) {
      const hit = (page.conversations || []).find((c) => c._id === convId)
      if (hit) {
        found = hit
        break
      }
    }
    if (!found) return old
    foundAnywhere = true

    const patched = { ...found, ...patch }
    const pages = old.pages.map((p, pageIdx) => {
      // Strip the row from every page; re-insert it at the head of page 0.
      const without = (p.conversations || []).filter((c) => c._id !== convId)
      if (pageIdx === 0) return { ...p, conversations: [patched, ...without] }
      return { ...p, conversations: without }
    })
    return { ...old, pages }
  })
  return foundAnywhere
}

// ChatGPT-style date buckets for the non-pinned conversations.
//
// Boundaries are built from LOCAL date PARTS — never `toISOString().slice(0,10)`,
// which would UTC-shift the day for Tehran (UTC+3:30) and bleed late-evening
// chats into "yesterday" (repo-documented gotcha). `new Date(y, m, date - N)`
// normalises across month/year edges natively.
//
// Older-than-30-days rows fall into per month-year buckets whose label is
// rendered via the locale-aware `fmtDate(date, 'MMMM yyyy')` — Shamsi month +
// year under `fa`, Gregorian under `en` (the `MMMM` token yields a long month
// name in BOTH calendars; see jalaliOptionsFor in utils/dateLocale). The list
// is render-only, so the formatted label doubles as the React/group key.
const FIXED_BUCKET_KEYS = ['today', 'yesterday', 'prev7', 'prev30']

// Exported so the Data Analyzer's parallel conversation list
// (useDataConversations) reuses the exact same ChatGPT-style date bucketing +
// local-date-parts boundary logic instead of forking a drifting copy.
export function bucketConversations(list) {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfYesterday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate() - 1,
  ).getTime()
  const startOfPrev7 = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7).getTime()
  const startOfPrev30 = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 30).getTime()

  // Fixed buckets keyed for the component to map onto `t('conversationList.*')`;
  // month buckets are collected in insertion order (list is already newest-first
  // from the API) keyed by their formatted label.
  const today = []
  const yesterday = []
  const prev7 = []
  const prev30 = []
  const months = new Map() // label -> items[]

  for (const conv of list) {
    const ts = conv.last_message_at || conv.created_at
    const time = ts ? new Date(ts).getTime() : NaN
    // Missing/invalid timestamp → treat as most-recent so the row never vanishes.
    if (!Number.isFinite(time) || time >= startOfToday) {
      today.push(conv)
    } else if (time >= startOfYesterday) {
      yesterday.push(conv)
    } else if (time >= startOfPrev7) {
      prev7.push(conv)
    } else if (time >= startOfPrev30) {
      prev30.push(conv)
    } else {
      let label
      try {
        label = fmtDate(new Date(ts), 'MMMM yyyy')
      } catch {
        // Fall back to a stable year-month string if locale formatting throws.
        const d = new Date(ts)
        label = `${d.getFullYear()}-${d.getMonth() + 1}`
      }
      if (!months.has(label)) months.set(label, [])
      months.get(label).push(conv)
    }
  }

  // Ordered newest-first: fixed buckets, then month buckets in encounter order.
  const groups = []
  const fixed = { today, yesterday, prev7, prev30 }
  for (const key of FIXED_BUCKET_KEYS) {
    if (fixed[key].length > 0) groups.push({ key, label: null, items: fixed[key] })
  }
  for (const [label, items] of months) {
    groups.push({ key: label, label, items })
  }
  return groups
}

/**
 * Data layer for the ChatGPT-style sidebar conversation list.
 *
 * Owns the search box state, an infinite-scroll query over the user's
 * conversations (scoped to the active workspace/project), the derived
 * pinned cluster + ChatGPT-style date-bucketed groups, the currently-open
 * conversation id, and the optimistic rename / pin / archive / delete mutations.
 *
 * Return contract (a sibling presentational component codes against this —
 * keep it stable):
 *   {
 *     search, setSearch,
 *     pinned,                                   // unpinned-above cluster, as-is
 *     groups: [{ key, label, items }],          // newest-first date buckets;
 *                                               //   fixed buckets → key ∈
 *                                               //   today|yesterday|prev7|prev30
 *                                               //   with label=null (component
 *                                               //   maps key → t()); month
 *                                               //   buckets → key === label ===
 *                                               //   formatted "MMMM yyyy".
 *     conversations,                            // flat list (search/empty checks)
 *     isLoading, isError, refetch,
 *     hasNextPage, fetchNextPage, isFetchingNextPage,
 *     activeConversationId,
 *     rename, togglePin, archive, remove,
 *   }
 */
export default function useSidebarConversations() {
  const { t } = useTranslation('layout')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const { currentWorkspace } = useWorkspace()
  const { currentProject } = useProject()

  const workspaceId = currentWorkspace?._id || null
  const projectId = currentProject?._id || null

  // The Sidebar mounts OUTSIDE the /chat/:conversationId <Route>, so a plain
  // useParams() here is always empty. Re-match the chat path against the live
  // pathname to learn which conversation (if any) is open for active-highlight.
  const activeConversationId =
    matchPath('/chat/:conversationId', location.pathname)?.params?.conversationId ?? null

  const [search, setSearch] = useState('')
  // Debounce so typing stays responsive while the query only refires on pause.
  const debouncedSearch = useDebouncedValue(search, 350)

  // Prefix `['conversations']` is invalidated app-wide (useChatStream title
  // updates, ChatPage). Scope segments (workspace/project/search) follow so each
  // filter combo gets its own cache that restarts at page 1.
  const {
    data,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['conversations', workspaceId, projectId, debouncedSearch, 'chat'],
    queryFn: ({ pageParam }) =>
      chatService.getConversations({
        page: pageParam,
        limit: PAGE_SIZE,
        // Scope contract: active project → exact match; no active project →
        // the 'null' sentinel (personal-scope only, project_id IS NULL — what a
        // chat created right now would get). OMITTING the param would return the
        // user's chats across ALL workspaces/projects (conversations carry no
        // workspace_id server-side) — a cross-workspace leak into this sidebar.
        project_id: projectId || 'null',
        workspace_id: workspaceId,
        // Exclude Data Analyzer conversations from the chat sidebar — they live
        // on the dedicated /data-analyzer page. Backend filters on ?kind=chat.
        // The 'chat' queryKey segment keeps this cache from colliding with the
        // data-conversation list.
        kind: 'chat',
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
  // Non-pinned rows, bucketed by recency into ordered (newest-first) groups.
  // Empty buckets are dropped here so the component never renders a bare header.
  const groups = useMemo(
    () => bucketConversations(conversations.filter((c) => !c.is_pinned)),
    [conversations],
  )

  // --- optimistic cache helpers over every scoped ['conversations', ...] entry.
  // Stored shape is infinite-query ({ pages:[{conversations:[...]}], pageParams }),
  // so guard on `old.pages` and map page-by-page.
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
      // Also patch the open-chat detail cache so a rename reflects in the header
      // of the currently-open conversation without a refetch.
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
        // Leaving the archived conversation open would 404 / show a stale view.
        if (conv._id === activeConversationId) navigate('/chat')
      } catch (err) {
        toast.error(t('conversationList.actionFailed'))
      }
      // The optimistic `removeRow` is the source of truth; the row is gone from
      // every scoped cache entry already. A natural refetch on next mount
      // settles the server side — no blanket invalidate needed.
    },
    [removeRow, queryClient, navigate, activeConversationId, t],
  )

  const remove = useCallback(
    async (conv) => {
      // Confirm dialog is the UI's responsibility — this just executes.
      removeRow(conv._id)
      try {
        await chatService.deleteConversation(conv._id)
        toast.success(t('conversationList.deleted'))
        if (conv._id === activeConversationId) navigate('/chat')
      } catch (err) {
        toast.error(t('conversationList.actionFailed'))
      }
      // Optimistic `removeRow` already cleared the row everywhere; a natural
      // refetch on next mount settles the server side.
    },
    [removeRow, queryClient, navigate, activeConversationId, t],
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

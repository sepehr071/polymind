import { createContext, useContext, useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from './AuthContext'
import workspaceService from '../services/workspaceService'

const WorkspaceContext = createContext(null)

const WORKSPACES_KEY = ['workspaces']

export function WorkspaceProvider({ children }) {
  const { user, isAuthenticated } = useAuth()
  const queryClient = useQueryClient()
  const [currentWorkspace, setCurrentWorkspace] = useState(null)
  // `initialized` flips true exactly ONCE per session (OnboardingGate gates the
  // first nav on it). React Query re-settles on every background refetch, so we
  // latch a local flag rather than re-derive it each render — never thrash it
  // back to false once the first load (success OR error) has committed.
  const [initialized, setInitialized] = useState(false)
  const [switcherOpen, setSwitcherOpen] = useState(false)
  // Last active-workspace id we persisted server-side, to dedupe the
  // best-effort PUT (DLP/spend gates read users.active_workspace_id).
  const lastPersistedActiveRef = useRef(null)

  // React Query owns the workspace list. Cached + deduped + background-stale
  // served, so an authMe refetch (new `user` object every 30s) no longer
  // refires the fetch. `enabled` gates on auth so a logged-out provider is idle.
  const {
    data: rawWorkspaces,
    isLoading,
    isFetching,
    status,
    error,
    refetch,
  } = useQuery({
    queryKey: WORKSPACES_KEY,
    queryFn: workspaceService.list,
    enabled: isAuthenticated,
    staleTime: 5 * 60_000,
  })

  // Personal workspaces no longer exist; ignore any stale rows defensively.
  const workspaces = useMemo(
    () => (rawWorkspaces || []).filter((w) => w.type !== 'personal'),
    [rawWorkspaces],
  )

  // Latch `initialized` once the query has settled (success or error) OR we're
  // logged out (nothing to load). Mirrors the old finally-block semantics.
  useEffect(() => {
    if (!isAuthenticated) {
      setInitialized(true)
      return
    }
    if (status === 'success' || status === 'error') {
      setInitialized(true)
    }
  }, [isAuthenticated, status])

  // Active-workspace selection + self-heal of a stale stored id. Runs whenever
  // the list or the user's server-side active id changes. Behaviour is byte-for
  // -byte the old refresh() picker: localStorage > user.active_workspace_id >
  // first team workspace; drop a stored id that no longer resolves to a workspace.
  useEffect(() => {
    if (!isAuthenticated) {
      setCurrentWorkspace(null)
      return
    }
    // Don't pick until the list has actually loaded; otherwise the first paint
    // would null out a still-valid selection then re-pick (flicker).
    if (status !== 'success') return

    const list = workspaces
    const stored = localStorage.getItem('active_workspace_id')
    const activeId = stored || user?.active_workspace_id
    const inList = activeId ? list.find((w) => w._id === activeId) : null
    // Super-admin can sit on a company they do not belong to. That id is absent
    // from the membership list; dropping it would snap the UI back to personal.
    const adminHold = Boolean(activeId && !inList && user?.role === 'admin')
    if (stored && !list.find((w) => w._id === stored) && !adminHold) {
      try { localStorage.removeItem('active_workspace_id') } catch { /* ignore */ }
    }
    // Admin with no selection stays unselected (switcher prompts to pick).
    const found = adminHold
      ? null
      : inList || (user?.role === 'admin' ? null : list[0] || null)
    if (adminHold) {
      setCurrentWorkspace((prev) =>
        prev?._id === activeId ? prev : { _id: activeId, name: '', type: 'team' },
      )
    } else {
      setCurrentWorkspace(found)
    }
    const persistId = adminHold ? activeId : found?._id
    // Reconcile the server column so DLP + spend gates scan the company the UI
    // is actually showing. Best-effort + deduped.
    if (
      persistId &&
      persistId !== user?.active_workspace_id &&
      lastPersistedActiveRef.current !== persistId
    ) {
      lastPersistedActiveRef.current = persistId
      workspaceService.setActive(persistId).catch(() => {})
    }
  }, [isAuthenticated, status, workspaces, user?.active_workspace_id, user?.role])

  const setActiveWorkspace = useCallback((workspace) => {
    if (!workspace) return
    setCurrentWorkspace(workspace)
    localStorage.setItem('active_workspace_id', workspace._id)
    // Persist server-side so the DLP/spend gates resolve this workspace (they
    // read users.active_workspace_id). Best-effort: never block the switch on
    // the round-trip, never surface an unhandled rejection when offline.
    lastPersistedActiveRef.current = workspace._id
    workspaceService.setActive(workspace._id).catch(() => {})
  }, [])

  // Thin wrapper around refetch that preserves the legacy return contract:
  // resolves to the workspace list (AcceptInvitePage awaits it to locate the
  // freshly-accepted workspace). Logged-out: invalidate + return [].
  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      queryClient.removeQueries({ queryKey: WORKSPACES_KEY })
      return []
    }
    const { data } = await refetch()
    return data ?? []
  }, [isAuthenticated, refetch, queryClient])

  // Token + first fetch in flight → loading. Cached data present → not loading
  // (background refetch is fine). Mirrors the old `loading` semantics.
  const loading = isAuthenticated && isLoading && isFetching

  const value = useMemo(() => ({
    workspaces,
    currentWorkspace,
    setActiveWorkspace,
    refresh,
    loading,
    initialized,
    switcherOpen,
    setSwitcherOpen,
    error,
    retry: refresh,
  }), [workspaces, currentWorkspace, setActiveWorkspace, refresh, loading, initialized, switcherOpen, error])

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider')
  return ctx
}

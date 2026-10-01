import { createContext, useContext, useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useWorkspace } from './WorkspaceContext'
import projectService from '../services/projectService'

const ProjectContext = createContext(null)

const UNFILED_SENTINEL = '__unfiled__'

export function ProjectProvider({ children }) {
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null
  const [currentProject, setCurrentProject] = useState(null)
  // P1.22 — Header ScopePillBar opens the project picker from outside the
  // <ProjectSwitcher> trigger. Co-located here mirroring WorkspaceContext.
  const [switcherOpen, setSwitcherOpen] = useState(false)

  // React Query owns the per-workspace project list. Keyed on the workspace id
  // so switching companies swaps caches instead of refetching from scratch, and
  // there's no workspace→projects waterfall blocking first paint on re-visits.
  const projectsKey = useMemo(() => ['projects', workspaceId], [workspaceId])
  const {
    data: projects = [],
    isLoading,
    isFetching,
    status,
    refetch,
  } = useQuery({
    queryKey: projectsKey,
    queryFn: () => projectService.list(workspaceId),
    enabled: !!workspaceId,
    staleTime: 5 * 60_000,
  })

  // Active-project selection + self-heal. Same picker as the old refresh():
  // Unfiled sentinel > stored id > 'personal' (unarchived) > first unarchived >
  // null; drop a stored id that no longer exists in this workspace.
  useEffect(() => {
    if (!workspaceId) {
      setCurrentProject(null)
      return
    }
    if (status !== 'success') return

    const list = projects
    const key = `active_project_id::${workspaceId}`
    const stored = localStorage.getItem(key)

    // Sentinel: user explicitly chose Unfiled view.
    if (stored === UNFILED_SENTINEL) {
      setCurrentProject(null)
      return
    }

    // Drop stored project ID if it no longer exists in this workspace —
    // prevents a deleted/foreign project from sticking around as the active
    // scope after backend resets or workspace switches.
    if (stored && !list.some(p => p._id === stored)) {
      try { localStorage.removeItem(key) } catch { /* ignore */ }
    }

    const found =
      list.find(p => p._id === stored) ||
      list.find(p => p.slug === 'personal' && !p.archived) ||
      list.find(p => !p.archived) ||
      null
    setCurrentProject(found)
  }, [workspaceId, status, projects])

  // P1.21: switching workspaces should not carry over a stale Unfiled sentinel
  // from the PREVIOUS workspace. Each workspace has its own key
  // (`active_project_id::<wid>`), so the sentinel is naturally scoped, but we
  // also drop the new workspace's sentinel on switch so the user lands on a
  // real project unless they re-pick Unfiled. Without this, a user who picked
  // Unfiled in ws A and never revisits to pick a real project would keep seeing
  // the wrong scope after switching back from ws B.
  const prevWorkspaceIdRef = useRef(null)
  useEffect(() => {
    const wid = workspaceId
    if (wid && prevWorkspaceIdRef.current && wid !== prevWorkspaceIdRef.current) {
      const key = `active_project_id::${wid}`
      const stored = localStorage.getItem(key)
      if (stored === UNFILED_SENTINEL) {
        try { localStorage.removeItem(key) } catch { /* ignore */ }
      }
    }
    prevWorkspaceIdRef.current = wid
  }, [workspaceId])

  const setActiveProject = useCallback((project) => {
    setCurrentProject(project)
    if (project && workspaceId) {
      localStorage.setItem(`active_project_id::${workspaceId}`, project._id)
    }
  }, [workspaceId])

  // Special: setActiveProject(null) means "Unfiled" view. Persist as sentinel.
  const setUnfiledView = useCallback(() => {
    setCurrentProject(null)
    if (workspaceId) {
      localStorage.setItem(`active_project_id::${workspaceId}`, UNFILED_SENTINEL)
    }
  }, [workspaceId])

  // Thin wrapper around refetch; preserves the legacy return contract (resolves
  // to the project list). No active workspace → the query is disabled, so
  // there's nothing to fetch; return [].
  const refresh = useCallback(async () => {
    if (!workspaceId) return []
    const { data } = await refetch()
    return data ?? []
  }, [workspaceId, refetch])

  const loading = !!workspaceId && isLoading && isFetching

  const value = useMemo(() => ({
    projects,
    currentProject,
    setActiveProject,
    setUnfiledView,
    refresh,
    loading,
    switcherOpen,
    setSwitcherOpen,
  }), [projects, currentProject, setActiveProject, setUnfiledView, refresh, loading, switcherOpen])

  return (
    <ProjectContext.Provider value={value}>
      {children}
    </ProjectContext.Provider>
  )
}

export function useProject() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used within ProjectProvider')
  return ctx
}

/**
 * navHelpers — workspace-aware navigation utilities.
 *
 * P1.20: bare `setActiveWorkspace(w)` calls outside the WorkspaceSwitcher
 * left the URL stuck on the OLD workspace id when the caller was on a
 * wid-scoped route (`/workspaces/<wid>/...` or `/admin/companies/<wid>/...`).
 * BillingTab / OverviewPage / SettingsPage kept showing the wrong company
 * because `wid` from useParams() wasn't re-routed.
 *
 * `switchTo` mirrors the helper baked into WorkspaceSwitcher.jsx so every
 * call site (CreateWorkspacePage, OnboardingWizard, AcceptInvitePage,
 * WorkspaceInvitesPanel, etc.) gets identical behaviour: set the workspace
 * active AND re-target the current route to the new id if the URL was
 * keyed by the old one. Callers who never sit on a wid-scoped route are
 * unharmed — the pathname regex simply doesn't match and we no-op the nav.
 *
 * Usage:
 *   import { makeSwitchTo } from '@/utils/navHelpers'
 *   const switchTo = makeSwitchTo({
 *     setActiveWorkspace,
 *     currentWorkspaceId: currentWorkspace?._id,
 *     navigate,
 *     location,
 *   })
 *   switchTo(newWorkspace)
 *
 * `navigate` and `location` come from react-router-dom's `useNavigate` and
 * `useLocation`.
 */
export function makeSwitchTo({
  setActiveWorkspace,
  currentWorkspaceId,
  navigate,
  location,
}) {
  return (w) => {
    if (!w) return
    const oldId = currentWorkspaceId
    setActiveWorkspace(w)
    if (!oldId || oldId === w._id) return
    if (!navigate || !location) return

    const m = location.pathname.match(/^\/workspaces\/([^/]+)(\/.*)?$/)
    if (m && m[1] === oldId) {
      const tail = m[2] || ''
      navigate(`/workspaces/${w._id}${tail}${location.search}`, { replace: true })
      return
    }
    const m2 = location.pathname.match(/^\/admin\/companies\/([^/]+)(\/.*)?$/)
    if (m2 && m2[1] === oldId) {
      const tail = m2[2] || ''
      navigate(`/admin/companies/${w._id}${tail}${location.search}`, { replace: true })
    }
  }
}

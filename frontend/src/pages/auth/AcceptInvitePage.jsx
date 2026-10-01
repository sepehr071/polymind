import { useEffect, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import workspaceService from '../../services/workspaceService'
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { useTranslation } from 'react-i18next'
import { makeSwitchTo } from '../../utils/navHelpers'

export default function AcceptInvitePage() {
  const { token } = useParams()
  const { isAuthenticated, isLoading } = useAuth()
  const { refresh, setActiveWorkspace, currentWorkspace } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const { t } = useTranslation('auth')

  // P1.20: shared helper so wid-scoped routes re-target after switching
  // workspaces, instead of leaving stale ids in the URL.
  const switchTo = (w) =>
    makeSwitchTo({
      setActiveWorkspace,
      currentWorkspaceId: currentWorkspace?._id,
      navigate,
      location,
    })(w)
  const [status, setStatus] = useState(t('invite.joining'))
  const [errored, setErrored] = useState(false)
  // null = still joining, object = success state
  const [success, setSuccess] = useState(null)

  useEffect(() => {
    if (isLoading) return
    if (!token) {
      setStatus(t('invite.invalid_link'))
      setErrored(true)
      return
    }
    if (!isAuthenticated) {
      localStorage.setItem('pending_invite_token', token)
      navigate('/login', { state: { from: `/invite/${token}` }, replace: true })
      return
    }

    let cancelled = false
    ;(async () => {
      try {
        const { workspace_id, role } = await workspaceService.acceptInvite(token)
        if (cancelled) return
        localStorage.removeItem('pending_invite_token')
        const list = await refresh()
        const fresh = (list || []).find(w => w._id === workspace_id)
        if (fresh) switchTo(fresh)
        const workspaceName = fresh?.name || t('invite.fallback_workspace')
        // Localize the raw backend role enum (owner|editor|viewer|member);
        // fall back to the raw value if a future role has no translation yet.
        const rawRole = role || 'member'
        const localizedRole = t(`invite.roles.${rawRole}`, { defaultValue: rawRole })
        setSuccess({ workspaceName, role: localizedRole, workspace: fresh || null })
      } catch (e) {
        if (cancelled) return
        localStorage.removeItem('pending_invite_token')
        // Show a localized failure message; fall back to the raw backend string
        // only if the translation is somehow missing, never the bare server text.
        const serverError = e.response?.data?.error
        setStatus(t('invite.error_expired', { defaultValue: serverError || 'Invite invalid or expired' }))
        setErrored(true)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [isAuthenticated, isLoading, token, navigate, refresh, setActiveWorkspace, t])

  if (success) {
    const { workspaceName, role, workspace } = success

    function handleNav(path) {
      if (workspace) switchTo(workspace)
      navigate(path, { replace: true })
    }

    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-foreground p-4">
        <Card className="w-full max-w-sm text-center">
          <CardHeader>
            <CardTitle className="text-xl">{t('invite.welcome')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-foreground-secondary text-sm">
              {t('invite.joined_as', { workspace: workspaceName, role })}
            </p>
            <div className="flex flex-col gap-2">
              <Button onClick={() => handleNav('/projects')} className="w-full">
                {t('invite.browse_projects')}
              </Button>
              <Button variant="secondary" onClick={() => handleNav('/chat')} className="w-full">
                {t('invite.start_chatting')}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="w-full max-w-sm space-y-3 rounded-md border border-border bg-background-elevated p-6 text-center">
        <div
          className={`flex items-center justify-center gap-2 ${errored ? 'text-error' : 'text-foreground-secondary'}`}
          aria-live="polite"
        >
          {!errored && (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
          )}
          <p>{status}</p>
        </div>
        <button
          className="text-sm text-accent hover:underline"
          onClick={() => navigate('/dashboard')}
        >
          {t('invite.go_dashboard')}
        </button>
      </div>
    </div>
  )
}

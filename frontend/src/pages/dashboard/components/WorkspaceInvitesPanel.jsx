import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import workspaceService from '../../../services/workspaceService'
import { useWorkspace } from '../../../context/WorkspaceContext'
import { makeSwitchTo } from '../../../utils/navHelpers'

export default function WorkspaceInvitesPanel() {
  const { t } = useTranslation('dashboard')
  const [token, setToken] = useState(() => localStorage.getItem('pending_invite_token'))
  const [error, setError] = useState(null)
  const [accepting, setAccepting] = useState(false)
  const { refresh, setActiveWorkspace, currentWorkspace } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (!token) return
    let cancelled = false

    async function accept() {
      setAccepting(true)
      try {
        const { workspace_id } = await workspaceService.acceptInvite(token)
        if (cancelled) return
        localStorage.removeItem('pending_invite_token')
        const list = await refresh()
        const ws = (list || []).find(w => w._id === workspace_id)
        if (ws) {
          // P1.20: use shared helper so wid-scoped routes re-target after
          // accepting an invite, instead of leaving stale ids in the URL.
          makeSwitchTo({
            setActiveWorkspace,
            currentWorkspaceId: currentWorkspace?._id,
            navigate,
            location,
          })(ws)
        }
        setToken(null)
      } catch (e) {
        if (cancelled) return
        localStorage.removeItem('pending_invite_token')
        setError(e.response?.data?.error || t('workspace.inviteError', { error: '' }))
      } finally {
        if (!cancelled) setAccepting(false)
      }
    }

    accept()
    return () => {
      cancelled = true
    }
  }, [token, refresh, setActiveWorkspace, currentWorkspace?._id, navigate, location, t])

  if (!token && !error) return null

  return (
    <div
      className="rounded-md border border-warn/40 bg-warn/10 p-3 text-sm"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {error ? (
        <span className="text-warn">{t('workspace.inviteError', { error })}</span>
      ) : (
        <span className="text-warn">
          {accepting ? t('workspace.acceptingInvite') : t('workspace.resumingInvite')}
        </span>
      )}
    </div>
  )
}

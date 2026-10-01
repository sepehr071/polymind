import { useState } from 'react'
import { Copy, X, RotateCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import RoleBadge from './RoleBadge'
import { workspaceService } from '@/services/workspaceService'
import { fmtDistanceToNow } from '@/utils/dateLocale'

export default function PendingInvitesList({ invites, onRevoke, onResend, wid }) {
  const { t } = useTranslation('projects')
  const [resendingTokens, setResendingTokens] = useState(new Set())
  // FLIP on invite add/revoke/resend; list parent holds only invite cards.
  const [listRef] = useAutoAnimate()

  async function handleResend(token) {
    if (!wid) return
    setResendingTokens((prev) => new Set(prev).add(token))
    try {
      const result = await workspaceService.resendInvite(wid, token)
      if (result?.email_sent === false) {
        toast(t('workspaceSettings.invites.resentLink'), { duration: 5000 })
      } else {
        toast.success(t('workspaceSettings.invites.resentEmail'))
      }
      if (onResend && result?.invite) {
        onResend({ old_token: token, invite: result.invite })
      }
    } catch (err) {
      toast.error(err?.response?.data?.error || t('workspaceSettings.invites.resendFailed'))
    } finally {
      setResendingTokens((prev) => {
        const next = new Set(prev)
        next.delete(token)
        return next
      })
    }
  }

  function relativeTime(isoString) {
    if (!isoString) return ''
    const expiry = new Date(isoString)
    if (Number.isNaN(expiry.getTime())) return ''
    if (expiry.getTime() <= Date.now()) return t('workspaceSettings.invites.expired')
    // Suffix-less distance ("3 days" / "۳ روز") fed into the "expires in {{time}}"
    // template — date-fns localizes the unit + digits per the numeral preference.
    return t('workspaceSettings.invites.expiresIn', {
      time: fmtDistanceToNow(expiry),
    })
  }

  if (!invites || invites.length === 0) {
    return (
      <p className="text-sm text-foreground-tertiary py-4">{t('workspaceSettings.invites.noInvites')}</p>
    )
  }

  function copyLink(token) {
    const url = `${window.location.origin}/invite/${token}`
    navigator.clipboard.writeText(url).then(() => {
      // Clipboard write succeeded silently
    }).catch(() => {
      // Fallback: prompt user
      window.prompt(t('workspaceSettings.invites.copyLinkPrompt'), url)
    })
  }

  return (
    <div ref={listRef} className="space-y-1">
      {invites.map((invite) => (
        <div
          key={invite.token}
          className="flex items-center gap-3 py-2.5 px-3 rounded-lg bg-background-elevated border border-border"
        >
          <div className="flex-1 min-w-0">
            <span className="text-sm text-foreground truncate block">
              {invite.email}
            </span>
            <span className="text-xs text-foreground-tertiary">
              {relativeTime(invite.expires_at)}
            </span>
          </div>

          <RoleBadge role={invite.role} />

          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-foreground-secondary hover:text-foreground"
            onClick={() => copyLink(invite.token)}
            title={t('workspaceSettings.invites.copyLink')}
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>

          {wid && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-foreground-secondary hover:text-accent"
              onClick={() => handleResend(invite.token)}
              disabled={resendingTokens.has(invite.token)}
              title={t('workspaceSettings.invites.resend')}
            >
              <RotateCw className={`h-3.5 w-3.5 ${resendingTokens.has(invite.token) ? 'animate-spin' : ''}`} />
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-foreground-tertiary hover:text-error"
            onClick={() => onRevoke(invite.token)}
            title={t('workspaceSettings.invites.revoke')}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ))}
    </div>
  )
}

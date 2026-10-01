import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Link2, Users, Copy, Check, Loader2, Globe, Folder, Clock,
} from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useProject } from '@/context/ProjectContext'
import { shareService } from '@/services/shareService'

/**
 * ShareDialog — two ways to share a chat, spelled out so the difference is
 * obvious:
 *  - Teams: LIVE collaboration. Members of the selected team(s) open the chat in
 *    their team scope and read + reply (a real, ongoing access grant).
 *  - Link: a FROZEN snapshot. Any logged-in user with the link reads the chat as
 *    it was at share time; they can't reply and later messages never appear. The
 *    link dies if the chat is deleted or the link is revoked.
 *
 * Owner-only surface (rendered from ChatHeader). Team list is the owner's own
 * teams (`useProject().projects`), mirroring MoveChatToProjectModal.
 */
export default function ShareDialog({ open, onOpenChange, conversationId, onSharesChanged }) {
  const { t } = useTranslation('chat')
  const { projects } = useProject()
  const [tab, setTab] = useState('teams')
  const [copied, setCopied] = useState(false)
  const [confirmingRevoke, setConfirmingRevoke] = useState(false)
  const [busyId, setBusyId] = useState(null) // project id or 'link' while a mutation runs

  const { data: shares, refetch, isLoading } = useQuery({
    queryKey: ['conversation-shares', conversationId],
    queryFn: () => shareService.listShares(conversationId),
    enabled: open && !!conversationId,
    staleTime: 0,
  })

  const teamIds = new Set(shares?.teams || [])
  const linkToken = shares?.link?.token || null
  const shareUrl = linkToken ? `${window.location.origin}/share/${linkToken}` : null
  const myTeams = (projects || []).filter((p) => !p.archived)

  const notifyChanged = () => onSharesChanged?.()

  async function toggleTeam(pid) {
    const next = new Set(teamIds)
    if (next.has(pid)) next.delete(pid)
    else next.add(pid)
    setBusyId(pid)
    try {
      await shareService.setTeamShares(conversationId, [...next])
      await refetch()
      notifyChanged()
    } catch {
      toast.error(t('share.error'))
    } finally {
      setBusyId(null)
    }
  }

  async function generateLink() {
    setBusyId('link')
    try {
      await shareService.createLinkShare(conversationId)
      await refetch()
      notifyChanged()
    } catch {
      toast.error(t('share.error'))
    } finally {
      setBusyId(null)
    }
  }

  async function revokeLink() {
    setBusyId('link')
    try {
      await shareService.revokeLinkShare(conversationId)
      await refetch()
      notifyChanged()
      setConfirmingRevoke(false)
    } catch {
      toast.error(t('share.error'))
    } finally {
      setBusyId(null)
    }
  }

  async function copyLink() {
    if (!shareUrl) return
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error(t('window.copyFailed'))
    }
  }

  const tabBtn = (key, Icon, label) => (
    <button
      type="button"
      onClick={() => { setTab(key); setConfirmingRevoke(false) }}
      className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
        tab === key
          ? 'bg-background text-foreground shadow-sm'
          : 'text-foreground-secondary hover:text-foreground'
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  )

  // One "what this does" bullet (icon + text), optional tone.
  const fact = (Icon, text, tone) => (
    <li className="flex items-start gap-2">
      <Icon
        className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${tone === 'warn' ? 'text-warning' : 'text-foreground-tertiary'}`}
      />
      <span className={tone === 'warn' ? 'text-foreground' : 'text-foreground-secondary'}>{text}</span>
    </li>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('share.title')}</DialogTitle>
          <DialogDescription>{t('share.subtitle')}</DialogDescription>
        </DialogHeader>

        <div className="flex gap-1 rounded-lg bg-background-secondary p-1">
          {tabBtn('teams', Users, t('share.teamsTab'))}
          {tabBtn('link', Link2, t('share.linkTab'))}
        </div>

        {tab === 'teams' ? (
          <div className="space-y-3">
            {/* What this mode does — sets the mental model before the controls. */}
            <div className="flex items-start gap-2.5 rounded-lg bg-accent/5 px-3 py-2.5">
              <Users className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
              <p className="text-sm leading-relaxed text-foreground-secondary">{t('share.teamsIntro')}</p>
            </div>

            {isLoading ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-accent" />
              </div>
            ) : myTeams.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-foreground-tertiary">
                {t('share.noTeams')}
              </p>
            ) : (
              <div className="max-h-60 space-y-1 overflow-auto">
                {myTeams.map((team) => {
                  const on = teamIds.has(team._id)
                  const busy = busyId === team._id
                  return (
                    <button
                      key={team._id}
                      type="button"
                      disabled={busy}
                      onClick={() => toggleTeam(team._id)}
                      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-start transition-colors ${
                        on ? 'bg-accent/10' : 'hover:bg-background-tertiary'
                      }`}
                    >
                      <Folder
                        className="h-4 w-4 shrink-0"
                        style={team.color ? { color: team.color } : undefined}
                      />
                      <span className="min-w-0 flex-1 truncate text-sm text-foreground">{team.name}</span>
                      {busy ? (
                        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent" />
                      ) : (
                        <span
                          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                            on ? 'border-accent bg-accent text-accent-foreground' : 'border-border'
                          }`}
                        >
                          {on && <Check className="h-3 w-3" />}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            )}

            {teamIds.size > 0 && (
              <p className="flex items-center gap-1.5 border-t border-border pt-2.5 text-xs text-foreground-tertiary">
                <Check className="h-3.5 w-3.5 text-success" />
                {t('share.teamsActiveHint', { count: teamIds.size })}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-start gap-2.5 rounded-lg bg-accent/5 px-3 py-2.5">
              <Globe className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
              <p className="text-sm leading-relaxed text-foreground-secondary">{t('share.linkIntro')}</p>
            </div>

            {linkToken ? (
              <>
                <div className="flex items-center gap-2 rounded-lg border border-border bg-background-secondary px-3 py-2">
                  <Globe className="h-4 w-4 shrink-0 text-foreground-tertiary" />
                  <input
                    readOnly
                    dir="ltr"
                    value={shareUrl}
                    onFocus={(e) => e.target.select()}
                    className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none"
                  />
                  <Button size="sm" variant="ghost" onClick={copyLink} className="shrink-0 gap-1.5">
                    {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
                    {copied ? t('share.copied') : t('share.copy')}
                  </Button>
                </div>

                {/* Exactly what this link does. */}
                <ul className="space-y-1.5 text-xs">
                  {fact(Globe, t('share.linkFactAnyone'))}
                  {fact(Clock, t('share.linkFactSnapshot'))}
                  {fact(Copy, t('share.linkFactSaveCopy'))}
                </ul>

                <div className="border-t border-border pt-2.5">
                  {confirmingRevoke ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-error/5 px-3 py-2">
                      <span className="min-w-0 text-xs text-foreground">{t('share.revokeConfirmBody')}</span>
                      <div className="flex shrink-0 items-center gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setConfirmingRevoke(false)}
                          disabled={busyId === 'link'}
                        >
                          {t('share.cancel')}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={revokeLink}
                          disabled={busyId === 'link'}
                          className="text-error hover:text-error"
                        >
                          {busyId === 'link' ? <Loader2 className="h-4 w-4 animate-spin" /> : t('share.revoke')}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex justify-end">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setConfirmingRevoke(true)}
                        className="text-error hover:text-error"
                      >
                        {t('share.revokeLink')}
                      </Button>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                <ul className="space-y-1.5 px-1 text-xs">
                  {fact(Globe, t('share.linkFactAnyone'))}
                  {fact(Clock, t('share.linkFactSnapshot'))}
                  {fact(Copy, t('share.linkFactSaveCopy'))}
                </ul>
                <Button onClick={generateLink} disabled={busyId === 'link'} className="w-full gap-2">
                  {busyId === 'link' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
                  {t('share.createLink')}
                </Button>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

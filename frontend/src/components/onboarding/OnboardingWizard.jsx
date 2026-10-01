import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { workspaceService } from '@/services/workspaceService'
import { userService } from '@/services/userService'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useAuth } from '@/context/AuthContext'
import { cn } from '@/lib/utils'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import { makeSwitchTo } from '@/utils/navHelpers'

// Basic shape check — backend is authoritative, this just catches obvious typos
// (missing @, missing domain, whitespace) before we bother sending invites.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function splitEmails(raw) {
  return raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function partitionEmails(raw) {
  const valid = []
  const invalid = []
  for (const candidate of splitEmails(raw)) {
    if (EMAIL_RE.test(candidate)) valid.push(candidate)
    else invalid.push(candidate)
  }
  return { valid, invalid }
}

export default function OnboardingWizard() {
  const { t } = useTranslation(['companies', 'common', 'projects'])
  const nav = useNavigate()
  const location = useLocation()
  const { setActiveWorkspace, refresh, currentWorkspace } = useWorkspace()
  const { user, updateUser } = useAuth()

  // "Seen" is recorded the moment the wizard is first shown — the gate
  // (OnboardingGate) then never force-redirects here again, regardless of
  // whether the user finishes, skips, or just navigates away. localStorage
  // is written first as an offline fallback; the backend stamp (idempotent,
  // StrictMode-safe) is authoritative and patched into the authMe cache so
  // navigating away works without a /me round-trip.
  useEffect(() => {
    if (user?.id) {
      try { localStorage.setItem(`onboarding_complete:${user.id}`, '1') } catch { /* noop */ }
    }
    userService
      .markOnboardingSeen()
      .then(({ onboarding_seen_at }) => {
        updateUser({ settings: { ...(user?.settings || {}), onboarding_seen_at } })
      })
      .catch(() => { /* localStorage fallback already written */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [step, setStep] = useState(1)
  const [companyName, setCompanyName] = useState('')
  const [emailsRaw, setEmailsRaw] = useState('')
  const [role, setRole] = useState('editor')
  const [busy, setBusy] = useState(false)

  // Live malformed-email check so the manager can fix typos before sending.
  const invalidEmails = partitionEmails(emailsRaw).invalid

  async function handleStep1(e) {
    e.preventDefault()
    if (!companyName.trim()) return
    setStep(2)
  }

  async function handleFinish(skip = false) {
    setBusy(true)
    try {
      const ws = await workspaceService.create({ name: companyName.trim(), type: 'team' })
      const newWorkspace = ws.workspace || ws

      // P1.20: use shared switchTo helper so wid-scoped routes don't drift
      // to the old workspace id after the new company is created.
      makeSwitchTo({
        setActiveWorkspace,
        currentWorkspaceId: currentWorkspace?._id,
        navigate: nav,
        location,
      })(newWorkspace)
      await refresh()

      if (!skip) {
        const { valid, invalid } = partitionEmails(emailsRaw)
        let sentCount = 0
        let noEmailCount = 0
        // Don't drop failures on the floor — collect them so the manager
        // knows which teammates still need inviting. {email, reason}.
        const failed = [...invalid.map((email) => ({ email, reason: 'invalid' }))]

        // Fire all invites concurrently — sequential awaits made onboarding
        // crawl with a long list. allSettled keeps per-email failures isolated.
        const results = await Promise.allSettled(
          valid.map((email) => workspaceService.invite(newWorkspace._id, { email, role })),
        )
        results.forEach((outcome, i) => {
          if (outcome.status === 'fulfilled') {
            if (outcome.value?.email_sent === false) {
              noEmailCount++
            } else {
              sentCount++
            }
          } else {
            const reason =
              outcome.reason?.response?.data?.error || t('onboarding.failedReasonGeneric')
            failed.push({ email: valid[i], reason })
          }
        })

        const total = sentCount + noEmailCount
        if (total > 0) {
          toast.success(t('onboarding.toastSuccess', { count: total }))
        }
        if (noEmailCount > 0) {
          toast(t('onboarding.toastNoEmail'), { duration: 6000 })
        }
        if (failed.length > 0) {
          const list = failed.map((f) => `${f.email} (${f.reason})`).join('\n')
          toast.error(t('onboarding.toastFailed', { count: failed.length, list }), {
            duration: 9000,
          })
        }
      }

      nav('/dashboard', { replace: true })
    } catch (err) {
      toast.error(err?.response?.data?.error || t('onboarding.createFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-app-dvh items-start sm:items-center justify-center overflow-y-auto bg-bg-0 p-4 py-8">
      {/* Standalone wizard panel (own full-screen backdrop, not a Dialog).
          Inner hierarchy box stays nested-tier (no 2nd solid layer). */}
      <div
        className={cn('w-full max-w-md rounded-xl p-8')}
        style={solidPanelSx({ radius: RADII.surface })}
      >
        {/* Step indicator */}
        <div
          className="mb-6 flex items-center gap-2"
          role="progressbar"
          aria-valuenow={step}
          aria-valuemin={1}
          aria-valuemax={2}
          aria-label={t('onboarding.stepProgress', { current: step, total: 2 })}
        >
          {[1, 2].map((s) => (
            <div
              key={s}
              aria-current={s === step ? 'step' : undefined}
              className={cn(
                'h-1.5 flex-1 rounded-full transition-colors',
                s <= step ? 'bg-accent' : 'bg-bg-3',
              )}
            />
          ))}
          <span className="sr-only">
            {t('onboarding.stepProgress', { current: step, total: 2 })}
          </span>
        </div>

        <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-fg-3">
          {t('onboarding.welcomeManager')}
        </p>

        {step === 1 && (
          <form onSubmit={handleStep1} className="space-y-5">
            <h1 className="text-xl font-semibold text-fg-0">
              {t('onboarding.step1Title')}
            </h1>

            <div className="space-y-2">
              <Label htmlFor="company-name">{t('label')}</Label>
              <Input
                id="company-name"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder={t('create.namePlaceholder')}
                maxLength={100}
                required
                autoFocus
              />
            </div>

            {/* How the app is organized — Company → Team. Nested inside the
                glass wizard panel → nested tier, no 2nd glass layer. */}
            <div className="rounded-lg border border-line bg-bg-2/50 p-4">
              <p className="mb-2 text-xs font-medium text-fg-1">
                {t('onboarding.hierarchyTitle')}
              </p>
              <ol className="space-y-1.5 text-[13px] leading-relaxed text-fg-2">
                <li>
                  <span className="font-medium text-fg-1">{t('onboarding.hierarchyCompany')}</span>
                  {' — '}
                  {t('onboarding.hierarchyCompanyDesc')}
                </li>
                <li className="ps-3">
                  <span className="font-medium text-fg-1">{t('onboarding.hierarchyTeam')}</span>
                  {' — '}
                  {t('onboarding.hierarchyTeamDesc')}
                </li>
              </ol>
            </div>

            <div className="flex items-center justify-between pt-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => nav('/dashboard', { replace: true })}
              >
                {t('onboarding.skipForNow')}
              </Button>
              <Button type="submit" disabled={!companyName.trim()}>
                {t('common:actions.next')}
              </Button>
            </div>
          </form>
        )}

        {step === 2 && (
          <div className="space-y-5">
            <h1 className="text-xl font-semibold text-fg-0">
              {t('onboarding.step2Title')}
            </h1>

            <div className="space-y-2">
              <Label htmlFor="invite-emails">{t('onboarding.emailsLabel')}</Label>
              <Textarea
                id="invite-emails"
                value={emailsRaw}
                onChange={(e) => setEmailsRaw(e.target.value)}
                placeholder={t('onboarding.emailsPlaceholder')}
                rows={4}
                dir="ltr"
              />
              <p className="text-[11px] text-fg-3">
                {t('onboarding.emailsHint')}
              </p>
              {invalidEmails.length > 0 && (
                <p className="text-[11px] text-warn" dir="ltr">
                  {t('onboarding.invalidEmailsWarn', {
                    count: invalidEmails.length,
                    list: invalidEmails.join(', '),
                  })}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label>{t('onboarding.roleLabel')}</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="editor">{t('projects:roles.editor')}</SelectItem>
                  <SelectItem value="viewer">{t('projects:roles.viewer')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center justify-between pt-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => handleFinish(true)}
                disabled={busy}
              >
                {t('onboarding.skip')}
              </Button>
              <Button
                type="button"
                onClick={() => handleFinish(false)}
                disabled={busy}
              >
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin me-2" />
                    {t('onboarding.finishing')}
                  </>
                ) : (
                  t('onboarding.finish')
                )}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

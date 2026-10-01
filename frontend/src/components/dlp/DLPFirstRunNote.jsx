import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ShieldCheck, X } from 'lucide-react'
import { dlpService } from '@/services/dlpService'
import { useWorkspace } from '@/context/WorkspaceContext'

const STORAGE_KEY = 'polymind.dlp.composerNoteDismissed.v1'

function readDismissed() {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * One-time, dismissible content-safety note shown above the chat composer.
 *
 * Calibrated transparency: a single warm sentence telling people their messages
 * are checked for accidental secrets and that their text is never stored, shown
 * once per device and then dismissed for good.
 *
 * Only rendered when the active workspace actually has DLP enabled, so we never
 * claim to scan when nothing is running. The policy GET is cached long (the
 * enabled flag rarely changes) so opening chat doesn't re-hit the endpoint, and
 * any error leaves the note hidden (fail-safe: never assert scanning when unsure).
 *
 * Dismissal lives in localStorage: the /users/ai-preferences PUT whitelist has
 * no generic UI-flags bucket, and a lost flag just re-shows one sentence, so a
 * server round-trip isn't warranted (per-device cosmetic flag).
 */
export default function DLPFirstRunNote() {
  const { t } = useTranslation('chat')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null
  const [dismissed, setDismissed] = useState(readDismissed)

  // getPolicy returns { policy: {...}, rule_catalog: [...] } — the enabled flag
  // is nested under `.policy` (see DLPPolicyTab load).
  const { data: policyRes } = useQuery({
    queryKey: ['dlp-policy', workspaceId],
    queryFn: () => dlpService.getPolicy(workspaceId),
    enabled: !!workspaceId && !dismissed,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  if (dismissed || !policyRes?.policy?.enabled) return null

  const dismiss = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, '1')
    } catch {
      // ignore — still hide for this session
    }
    setDismissed(true)
    window.dispatchEvent(new CustomEvent('chat:composer-focus'))
  }

  return (
    <div className="px-3 md:px-4">
      <div className="mx-auto flex max-w-[768px] items-start gap-3 rounded-xl border border-border bg-background-secondary px-4 py-3 text-start">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <p className="min-w-0 flex-1 text-[12px] leading-relaxed text-foreground-secondary">
          {t('dlp.composerNote')}
        </p>
        <button
          type="button"
          onClick={dismiss}
          aria-label={t('dlp.composerNoteDismiss')}
          title={t('dlp.composerNoteDismiss')}
          className="shrink-0 rounded-md p-1 text-foreground-tertiary transition-colors hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

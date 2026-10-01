import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import { Dialog, DialogClose, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { SECTIONS, DEFAULT_SECTION } from '@/pages/dashboard/settings/sections/registry'
import SettingsNav from '@/components/settings/SettingsNav'

/**
 * ChatGPT-style settings modal. Wraps the SAME section components used by the
 * standalone /settings page (shared via sections/registry) so the modal and the
 * page never drift. Opened app-wide via the `open-settings` window event; the
 * /settings route + its hash deep-links remain intact.
 *
 * Layout mirrors the page: canonical UNDERLINE tab row (shared SettingsNav) over
 * a single scrollable section body — both surfaces stay in lock-step per the
 * shared-registry contract (P2-04).
 */
export default function SettingsDialog({ open, onOpenChange, initialSection }) {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  const [active, setActive] = useState(initialSection || DEFAULT_SECTION)

  // Re-sync when reopened pointed at a different section (e.g. a future
  // deep-link that opens straight onto Usage).
  useEffect(() => {
    if (open) setActive(initialSection || DEFAULT_SECTION)
  }, [open, initialSection])

  const current = SECTIONS.find((s) => s.id === active) || SECTIONS[0]
  const ActiveComponent = current.Component

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showClose={false}
        // Phones: edge-to-edge full-screen (safe-area insets keep the top nav +
        // content clear of the notch/home indicator). sm+ keeps the centered,
        // capped panel.
        className="!flex !h-[80vh] !max-h-[80vh] !flex-col !overflow-hidden max-w-3xl w-full p-0 max-sm:!h-[100dvh] max-sm:!max-h-none max-sm:w-screen max-sm:max-w-none max-sm:mx-0 max-sm:rounded-none max-sm:pt-[var(--safe-top)] max-sm:pb-[var(--safe-bottom)]"
      >
        {/* a11y label only — the visual heading lives in each section. */}
        <DialogTitle className="sr-only">{t('title')}</DialogTitle>

        {/* Tab row + close: same 40px height, inline-flex items-center. */}
        <div className="inline-flex h-14 w-full shrink-0 items-center gap-2 overflow-hidden px-4">
          <SettingsNav active={active} onSelect={setActive} className="min-w-0" />
          <DialogClose
            aria-label={tCommon('actions.close')}
            className="ms-auto inline-flex h-10 w-10 shrink-0 items-center justify-center self-center rounded-lg text-foreground-tertiary opacity-70 transition-all hover:opacity-100 hover:bg-background-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-4 w-4" />
          </DialogClose>
        </div>

        {/* Section body — the SOLE scroll container. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-24 pt-4 md:px-6">
          <ActiveComponent />
        </div>
      </DialogContent>
    </Dialog>
  )
}

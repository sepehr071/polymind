import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import { SHORTCUTS, formatShortcut } from '../../hooks/useKeyboardShortcuts'

// Compact reference of the wired keyboard shortcuts. Opened via `mod+/`
// (global, wired in MainLayout). Rows come straight from the SHORTCUTS catalog
// so the panel never advertises a binding that isn't actually live.
export default function ShortcutsHelpModal({ open, onOpenChange }) {
  const { t } = useTranslation('layout')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('shortcutsHelp.title')}</DialogTitle>
        </DialogHeader>

        <ul className="space-y-1">
          {Object.entries(SHORTCUTS).map(([id, { keys, descriptionKey }]) => (
            <li
              key={id}
              className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5"
            >
              <span className="text-sm text-foreground-secondary">
                {t(descriptionKey)}
              </span>
              {/* Key names are Latin tokens — lock LTR so '⌘ + /' never reorders
                  inside the RTL layout. */}
              <span dir="ltr" className="flex shrink-0 items-center gap-1">
                {formatShortcut(keys).split(' + ').map((token, i) => (
                  <kbd
                    key={i}
                    className="px-1 py-0.5 rounded border border-border bg-background-tertiary text-[10px] font-mono leading-none text-foreground-secondary"
                  >
                    {token}
                  </kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  )
}

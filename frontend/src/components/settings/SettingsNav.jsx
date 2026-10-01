import { useTranslation } from 'react-i18next'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/utils/cn'
import { SECTIONS } from '@/pages/dashboard/settings/sections/registry'

/**
 * SettingsNav — the single section nav shared by BOTH the standalone /settings
 * page and the ChatGPT-style settings modal (SettingsDialog), so the two
 * surfaces can never drift. Renders the canonical UNDERLINE tabs primitive
 * (ui/tabs.jsx, Consistent UI System P2-04): active = accent text + 2px accent
 * bottom-border, inactive = foreground-secondary. Pure presentational — the
 * caller owns `active` and how a section is selected (hash-route on the page,
 * local state in the modal).
 *
 * Direction-agnostic: the underline tab row is a horizontal strip that scrolls
 * on narrow viewports (logical props only).
 *
 * @param {string} active                 currently-selected section id
 * @param {(id: string) => void} onSelect select handler
 * @param {string} [className]            extra classes on the <TabsList>
 */
export default function SettingsNav({ active, onSelect, className }) {
  const { t } = useTranslation('settings')

  return (
    <Tabs value={active} onValueChange={onSelect} variant="underline" className={cn('min-w-0', className)}>
      <TabsList
        aria-label={t('title')}
        className="inline-flex h-10 w-auto items-center justify-start overflow-x-auto overflow-y-hidden [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
      >
        {SECTIONS.map(({ id, icon: Icon, tKey }) => (
          <TabsTrigger key={id} value={id} className="inline-flex h-full w-max shrink-0 items-center px-0 py-0">
            <Icon className="h-4 w-4 shrink-0" />
            <span className="leading-none">{t(tKey)}</span>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}

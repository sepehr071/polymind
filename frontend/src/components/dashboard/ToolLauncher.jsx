import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LayoutGrid } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { hasFeature } from '@/utils/featureFlags'
import { ALL_NAV_ITEMS } from '@/constants/navigation'
import { hubIconFor } from '@/constants/hubIcons'
import { cn } from '@/utils/cn'
import ToolCard from './ToolCard'

/** Home rows. Paths are real routes. Flags still hide a tile. */
const HOME_GROUPS = [
  {
    id: 'chat',
    titleKey: 'hub.groups.chat',
    hintKey: 'hub.groups.chatHint',
    paths: ['/chat', '/arena', '/debate', '/agent'],
  },
  {
    id: 'work',
    titleKey: 'hub.groups.work',
    hintKey: 'hub.groups.workHint',
    paths: [
      '/email-writer',
      '/cv-checker',
      '/research',
      '/contracts',
      '/tenders',
      '/shop',
      '/data-analyzer',
      '/presentations',
      '/payroll',
      '/meetings',
      '/workflow',
      '/automate-agent',
    ],
  },
  {
    id: 'visual',
    titleKey: 'hub.groups.visual',
    hintKey: 'hub.groups.visualHint',
    paths: ['/image-studio', '/ocr'],
  },
]

const CATS = [
  { id: 'all', labelKey: 'hub.cats.all' },
  { id: 'chat', labelKey: 'hub.groups.chat' },
  { id: 'work', labelKey: 'hub.groups.work' },
  { id: 'visual', labelKey: 'hub.groups.visual' },
]

export default function ToolLauncher() {
  const { t } = useTranslation('dashboard')
  const [cat, setCat] = useState('all')
  const { user } = useAuth()

  const groups = useMemo(() => {
    const byPath = new Map(ALL_NAV_ITEMS.map((item) => [item.to, item]))
    return HOME_GROUPS.map((group) => ({
      ...group,
      items: group.paths
        .map((path) => byPath.get(path))
        .filter((item) => item && (!item.feature || hasFeature(user, item.feature))),
    })).filter((group) => group.items.length)
  }, [user])

  if (!groups.length) return null

  const active = cat === 'all' ? null : groups.find((group) => group.id === cat)

  return (
    <div className="mt-10">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <LayoutGrid className="h-4 w-4 text-accent" />
          <h2 className="text-lg font-bold text-foreground">{t('hub.sections.tools')}</h2>
        </div>
        <div className="flex items-center gap-1 overflow-x-auto rounded-full bg-background-tertiary p-1 ring-1 ring-border">
          {CATS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setCat(tab.id)}
              className={cn(
                'inline-flex shrink-0 items-center rounded-full px-4 py-2 text-sm',
                cat === tab.id
                  ? 'bg-accent text-accent-foreground shadow-sm'
                  : 'text-foreground-secondary hover:text-foreground',
              )}
            >
              {t(tab.labelKey)}
            </button>
          ))}
        </div>
      </div>
      {cat === 'all' ? (
        <div className="space-y-8">
          {groups.map((group) => (
            <section key={group.id}>
              <div className="mb-3">
                <h3 className="text-base font-bold text-foreground">{t(group.titleKey)}</h3>
                <p className="mt-0.5 text-[11px] text-foreground-tertiary">{t(group.hintKey)}</p>
              </div>
              <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 lg:grid-cols-3 xl:grid-cols-4">
                {group.items.map((item) => (
                  <div key={item.to} className="flex w-[min(72vw,240px)] shrink-0 sm:w-auto">
                    <ToolCard
                      to={item.to}
                      icon={item.icon}
                      art={hubIconFor(item.to)}
                      labelKey={item.labelKey}
                      descKey={item.descKey}
                    />
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : active ? (
        <div className="grid grid-cols-2 items-stretch gap-3 lg:grid-cols-3 xl:grid-cols-4">
          {active.items.map((item) => (
            <ToolCard
              key={item.to}
              to={item.to}
              icon={item.icon}
              art={hubIconFor(item.to)}
              labelKey={item.labelKey}
              descKey={item.descKey}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

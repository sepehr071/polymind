import { useTranslation } from 'react-i18next'
import {
  Globe, Image as ImageIcon, FileSpreadsheet, Link2, Sparkles, ListChecks,
} from 'lucide-react'
import { IconTile } from '@/components/ui/icon-tile'
import { cn } from '@/lib/utils'

const CAP_ICONS = {
  web: Globe,
  image: ImageIcon,
  files: FileSpreadsheet,
  data: FileSpreadsheet,
  clarify: ListChecks,
}

const STARTER_ICONS = [Globe, ImageIcon, Link2, FileSpreadsheet, Sparkles, ListChecks]

/**
 * Empty agent hero — capability map + fill-not-send starters.
 */
export default function AgentEmptyState({ onPickStarter }) {
  const { t } = useTranslation('agent')

  const capsRaw = t('empty.capabilities', { returnObjects: true })
  const caps = Array.isArray(capsRaw) ? capsRaw : []

  const startersRaw = t('empty.starters', { returnObjects: true })
  const starters = (Array.isArray(startersRaw) ? startersRaw : []).slice(0, 6).map((s, i) => ({
    title: s?.title ?? '',
    prompt: s?.prompt ?? '',
    Icon: STARTER_ICONS[i] ?? Sparkles,
  }))

  return (
    <div className="relative mx-auto my-auto flex w-full max-w-[768px] flex-col gap-6 px-4 py-8">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-48"
        style={{
          background:
            'radial-gradient(60% 100% at 50% 0%, rgba(30,71,209,0.08), transparent 70%)',
        }}
      />

      <div className="flex flex-col items-center gap-3 text-center">
        <IconTile tone="sky" size="xl">
          <Sparkles className="size-5" />
        </IconTile>
        <h2 className="text-xl font-semibold tracking-tight text-foreground md:text-2xl">
          {t('empty.title')}
        </h2>
        <p className="max-w-md text-[13px] leading-relaxed text-muted-foreground">
          {t('empty.subtitle')}
        </p>
      </div>

      {caps.length > 0 && (
        <div className="flex flex-wrap justify-center gap-2">
          {caps.map((c) => {
            const key = c?.key || c?.id || c?.label
            const Icon = CAP_ICONS[c?.key] || Sparkles
            return (
              <span
                key={key}
                className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-bg-2/50 px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
              >
                <Icon className="size-3.5 text-primary" aria-hidden />
                {c?.label}
              </span>
            )
          })}
        </div>
      )}

      <div className="flex flex-wrap justify-center gap-2">
        {starters.map((s, i) => (
          <button
            key={i}
            type="button"
            onClick={() => s.prompt && onPickStarter?.(s.prompt)}
            className={cn(
              'group inline-flex items-center gap-2 rounded-full border border-border bg-accent/[0.06]',
              'ps-3 pe-4 py-2 text-[13px] font-semibold text-foreground',
              'transition-colors hover:border-accent/40 hover:bg-accent/10',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
            )}
          >
            <s.Icon className="size-4 text-accent" aria-hidden />
            <span>{s.title}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

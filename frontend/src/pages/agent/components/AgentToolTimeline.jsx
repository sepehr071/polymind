import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ChevronDown, Globe, Link2, Image as ImageIcon, Terminal,
  HelpCircle, Loader2, Check, CircleAlert, Wrench,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const TOOL_META = {
  web_search: { Icon: Globe, labelKey: 'tools.webSearch' },
  web_fetch: { Icon: Link2, labelKey: 'tools.webFetch' },
  generate_image: { Icon: ImageIcon, labelKey: 'tools.image' },
  run_python: { Icon: Terminal, labelKey: 'tools.code' },
  ask_user: { Icon: HelpCircle, labelKey: 'tools.ask' },
}

function toolMeta(name) {
  return TOOL_META[name] || { Icon: Wrench, labelKey: null }
}

/**
 * Compact agent tool activity — live chips or collapsible finished list.
 * steps: [{ step, name, status?: 'running'|'done'|'error', error?, prompt? }]
 */
export default function AgentToolTimeline({
  steps = [],
  streaming = false,
  className,
  compact = false,
}) {
  const { t } = useTranslation('agent')
  const list = Array.isArray(steps) ? steps.filter((s) => s && (s.name || s.step != null)) : []
  const [open, setOpen] = useState(false)

  if (!list.length) return null

  if (compact || streaming) {
    return (
      <div className={cn('flex flex-wrap items-center gap-1.5', className)} role="status">
        {list.map((s, i) => {
          const { Icon, labelKey } = toolMeta(s.name)
          const label = labelKey ? t(labelKey) : (s.name || t('tools.generic'))
          const running = s.status === 'running' || (streaming && i === list.length - 1 && !s.status)
          const err = s.status === 'error' || !!s.error
          return (
            <span
              key={s.step ?? i}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px]',
                err && 'border-destructive/40 text-destructive',
                running && !err && 'border-primary/40 bg-primary/10 text-primary',
                !running && !err && 'border-border text-muted-foreground',
              )}
            >
              {running && !err ? (
                <Loader2 className="size-3 animate-spin" aria-hidden />
              ) : err ? (
                <CircleAlert className="size-3" aria-hidden />
              ) : (
                <Icon className="size-3" aria-hidden />
              )}
              {label}
              {s.step != null ? ` #${s.step}` : ''}
              {running && !err ? '…' : ''}
            </span>
          )
        })}
      </div>
    )
  }

  // Settled: collapsible summary
  return (
    <div className={cn('rounded-xl border border-border/50 bg-bg-2/40', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-start text-[12px] font-medium text-muted-foreground hover:text-foreground"
      >
        <Wrench className="size-3.5 shrink-0" aria-hidden />
        <span className="flex-1">{t('tools.used', { count: list.length })}</span>
        <ChevronDown
          className={cn('size-3.5 transition-transform', open && 'rotate-180')}
          aria-hidden
        />
      </button>
      {open && (
        <ol className="space-y-1.5 border-t border-border/40 px-3 py-2">
          {list.map((s, i) => {
            const { Icon, labelKey } = toolMeta(s.name)
            const label = labelKey ? t(labelKey) : (s.name || t('tools.generic'))
            const err = s.status === 'error' || !!s.error
            return (
              <li key={s.step ?? i} className="flex items-start gap-2 text-[12px]">
                {err ? (
                  <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                ) : (
                  <Check className="mt-0.5 size-3.5 shrink-0 text-primary" />
                )}
                <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <span className={cn(err && 'text-destructive')}>
                  {label}
                  {s.prompt ? (
                    <span className="ms-1 text-muted-foreground">— {String(s.prompt).slice(0, 80)}</span>
                  ) : null}
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

export function phaseLabel(phase, t) {
  if (!phase) return null
  const map = {
    thinking: 'phase.thinking',
    finishing: 'phase.finishing',
    web_search: 'phase.searching',
    web_fetch: 'phase.fetching',
    generating_image: 'phase.generatingImage',
    extracting: 'phase.readingFile',
    asking: 'phase.asking',
    tool: 'phase.tool',
  }
  const key = map[phase]
  return key ? t(key) : null
}

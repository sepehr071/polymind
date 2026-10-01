import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { ArrowUp, Plus } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useProject } from '@/context/ProjectContext'
import { hasFeature } from '@/utils/featureFlags'
import { ALL_NAV_ITEMS } from '@/constants/navigation'
import { cn } from '@/utils/cn'
import { Button } from '@/components/ui/button'
import PillBar from '@/components/chat/PillBar'
import { configService } from '@/services/chatService'
import {
  QUICK_MODEL_IDS,
  isQuickModel,
  getModelIdFromQuick,
  findDefaultModel,
} from '@/constants/models'
import { stashDashboardChatConfig } from '@/utils/dashboardChatHandoff'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const LIBRARY = new Set(['/configs', '/knowledge'])

function labelFor(item, tLayout, tDash) {
  const slug = item.labelKey?.startsWith('sidebar.') ? item.labelKey.slice('sidebar.'.length) : null
  return slug ? tDash(`hub.toolTitle.${slug}`, { defaultValue: tLayout(item.labelKey) }) : tLayout(item.labelKey)
}

/**
 * Home composer. Chat drafts go to /chat and auto-send there.
 * Any other chip only navigates. It does not send.
 */
export default function QuickChatComposer({ className }) {
  const { t, i18n } = useTranslation('dashboard')
  const { t: tl } = useTranslation('layout')
  const { user } = useAuth()
  const { currentProject } = useProject()
  const projectId = currentProject?._id || null
  const navigate = useNavigate()
  const [message, setMessage] = useState('')
  const [target, setTarget] = useState('/chat')
  const [selectedConfigId, setSelectedConfigId] = useState(
    () => (QUICK_MODEL_IDS[0] ? `quick:${QUICK_MODEL_IDS[0]}` : null),
  )

  const { data: configsData } = useQuery({
    queryKey: ['configs', { projectId }],
    queryFn: () => configService.getConfigs(projectId ? { project_id: projectId } : undefined),
    enabled: target === '/chat',
  })
  const configs = useMemo(
    () => (configsData?.configs || []).filter((c) => c.parameters?.kind !== 'image'),
    [configsData?.configs],
  )
  const selectedConfig = useMemo(() => {
    if (!selectedConfigId) return null
    if (isQuickModel(selectedConfigId)) {
      const model = findDefaultModel(getModelIdFromQuick(selectedConfigId))
      if (model) {
        return {
          _id: selectedConfigId,
          name: model.name,
          avatar: { type: 'logo', value: model.logo },
          model_id: model.id,
          isQuickModel: true,
        }
      }
    }
    return configs.find((c) => c._id === selectedConfigId) || null
  }, [selectedConfigId, configs])

  const assistants = useMemo(
    () =>
      ALL_NAV_ITEMS.filter(
        (item) => !LIBRARY.has(item.to) && (!item.feature || hasFeature(user, item.feature)),
      ),
    [user],
  )
  const chips = assistants.slice(0, 4)
  const more = assistants.slice(4)

  useEffect(() => {
    if (assistants.some((item) => item.to === target)) return
    setTarget(assistants.find((item) => item.to === '/chat')?.to || assistants[0]?.to || '/chat')
  }, [assistants, target])

  const go = (event) => {
    event?.preventDefault()
    const text = message.trim()
    if (target === '/chat') {
      stashDashboardChatConfig(selectedConfigId)
      if (text) {
        try {
          sessionStorage.setItem('dashboard_chat_draft', text)
        } catch {
          /* private mode */
        }
      }
      navigate('/chat')
      return
    }
    navigate(target)
  }

  return (
    <div className={cn('mx-auto w-full max-w-3xl', className)}>
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
        {chips.map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.to}
              type="button"
              onClick={() => setTarget(item.to)}
              className={cn(
                'inline-flex shrink-0 items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors',
                target === item.to
                  ? 'border-accent/40 bg-accent/10 text-accent'
                  : 'border-border bg-background-secondary text-foreground-secondary hover:bg-background-tertiary hover:text-foreground',
              )}
            >
              {Icon ? <Icon className="h-4 w-4" /> : null}
              {labelFor(item, tl, t)}
            </button>
          )
        })}
        {more.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="inline-flex shrink-0 items-center gap-2 rounded-full border border-border bg-background-secondary px-3 py-1.5 text-sm text-foreground-secondary hover:bg-background-tertiary hover:text-foreground"
              >
                <Plus className="h-3.5 w-3.5" />
                {t('hub.otherAssistant')}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-h-80 w-64">
              {more.map((item) => (
                <DropdownMenuItem key={item.to} onSelect={() => setTarget(item.to)}>
                  {labelFor(item, tl, t)}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <form
        onSubmit={go}
        className="overflow-hidden rounded-2xl border border-border bg-background-secondary shadow-[0_1px_2px_rgb(17_24_39/0.04),0_8px_24px_-12px_rgb(30_71_209/0.14)] focus-within:border-accent/70 dark:shadow-none"
      >
        <textarea
          rows={2}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              go()
            }
          }}
          placeholder={t('hub.quickChat.placeholder')}
          dir={i18n.dir()}
          className="max-h-48 w-full resize-none bg-transparent px-4 pb-2 pt-4 text-[15px] text-foreground outline-none placeholder:text-foreground-tertiary"
        />
        <div className="flex items-center gap-2 px-2 pb-2">
          {target === '/chat' ? (
            <PillBar
              prominent
              selectedConfig={selectedConfig}
              configs={configs}
              selectedConfigId={selectedConfigId}
              onSelectConfig={setSelectedConfigId}
            />
          ) : (
            <span className="min-w-0 flex-1 truncate px-2 text-[11px] text-foreground-tertiary">
              {labelFor(assistants.find((item) => item.to === target) || { labelKey: 'sidebar.chat', to: '/chat' }, tl, t)}
            </span>
          )}
          {target === '/chat' && <span className="min-w-0 flex-1" />}
          <Button
            type="submit"
            size="icon"
            aria-label={t('hub.quickChat.send')}
            className="h-9 w-9 shrink-0 rounded-lg bg-accent text-accent-foreground shadow-primary-glow hover:bg-accent/90"
          >
            <ArrowUp className="h-4 w-4" />
          </Button>
        </div>
      </form>
    </div>
  )
}

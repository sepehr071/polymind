import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Bot, Plus, Check, Zap, FolderOpen, Globe, Type, Image as ImageIcon, AudioLines, Video, FileText, HardDrive, X } from 'lucide-react'
import { cn } from '../../utils/cn'
import { prettifyModelName } from '@/utils/modelName'
import { DEFAULT_MODELS } from '../../constants/models'
import { solidPanelSx, SOLID_SURFACE_CLASS } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import { useModelCatalog } from '../../hooks/useModelCatalog'
import { useCoarsePointer } from '../../hooks/useMediaQuery'
import { useProject } from '../../context/ProjectContext'
import ModelLogo from './ModelLogo'
import {
  Command,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from '@/components/ui/command'

function ItemAvatar({ children, className }) {
  return (
    <div
      className={cn(
        'h-8 w-8 rounded-lg flex items-center justify-center text-sm flex-shrink-0 bg-background-tertiary/80',
        className
      )}
    >
      {children}
    </div>
  )
}

function TierBadge({ tier, t }) {
  if (tier === 'local') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold leading-none px-1.5 py-0.5 rounded-full bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 shrink-0">
        <HardDrive className="h-2.5 w-2.5" aria-hidden="true" />
        {t('configSelector.badgeLocal')}
      </span>
    )
  }
  if (tier === 'free') {
    return (
      <span className="text-[10px] font-semibold leading-none px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 shrink-0">
        {t('configSelector.badgeFree')}
      </span>
    )
  }
  if (tier === 'expensive') {
    return (
      <span className="text-[10px] font-semibold leading-none px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400 shrink-0">
        {t('configSelector.badgePro')}
      </span>
    )
  }
  return null
}

// Compact 3-dot strength meter (Speed / Intelligence) driven by a 1–3 value.
// Undefined value renders all-muted dots.
function Meter({ label, value = 0 }) {
  return (
    <span className="inline-flex items-center gap-1" title={`${label}: ${value}/3`} aria-label={`${label} ${value} of 3`}>
      <span className="text-[10px] text-foreground-tertiary">{label}</span>
      <span className="flex items-center gap-0.5">
        {[1, 2, 3].map(i => (
          <span key={i} className={i <= value ? 'h-1.5 w-1.5 rounded-full bg-accent' : 'h-1.5 w-1.5 rounded-full bg-muted'} />
        ))}
      </span>
    </span>
  )
}

export default function ConfigSelector({ configs, selectedConfigId, onSelect, onClose }) {
  const { t } = useTranslation('chat')
  const navigate = useNavigate()
  const { isDeprecated, getById } = useModelCatalog()
  const { currentProject } = useProject()
  // Touch devices: autofocusing the search input pops the soft keyboard over
  // the list the user just opened — let them tap the field if they want it.
  const isCoarse = useCoarsePointer()

  const handleQuickSelect = (modelId) => onSelect(`quick:${modelId}`)

  // Group configs by visibility relative to the active project. A config is
  // "Project" if its project_id matches the active project. "Mine" = owned but
  // not pinned to this project (private/personal). "Public" = explicitly public.
  const { projectConfigs, myConfigs, publicConfigs } = useMemo(() => {
    const projectId = currentProject?._id || null
    const project = []
    const mine = []
    const pub = []
    for (const c of configs) {
      if (projectId && c.project_id === projectId) {
        project.push(c)
      } else if (c.visibility === 'public') {
        pub.push(c)
      } else {
        mine.push(c)
      }
    }
    return { projectConfigs: project, myConfigs: mine, publicConfigs: pub }
  }, [configs, currentProject?._id])

  // Segmented Models | Assistants tabs. Default to the tab containing the
  // current selection so the active item is visible on open.
  const [tab, setTab] = useState(() =>
    selectedConfigId?.startsWith('quick:') ? 'models' : (configs.length ? 'assistants' : 'models')
  )
  const [search, setSearch] = useState('')
  const [provider, setProvider] = useState('all')
  const [useCase, setUseCase] = useState('all')
  const [processing, setProcessing] = useState('all')

  const providers = useMemo(
    () => [...new Set(DEFAULT_MODELS.map((m) => m.logo))],
    [],
  )

  const filteredModels = useMemo(() => DEFAULT_MODELS.filter((m) => {
    if (provider !== 'all' && m.logo !== provider) return false
    if (processing === 'local' && m.tier !== 'local') return false
    if (processing === 'cloud' && m.tier === 'local') return false
    if (useCase === 'multimodal') {
      if (!(m.modalities || []).some((x) => x !== 'text')) return false
    } else if (useCase === 'reasoning') {
      if (m.intelligence !== 3) return false
    } else if (useCase === 'fast') {
      if (m.speed !== 3) return false
    } else if (useCase === 'text') {
      if (!(m.modalities || []).every((x) => x === 'text')) return false
    }
    return true
  }), [provider, processing, useCase])

  const filtersActive = provider !== 'all' || useCase !== 'all' || processing !== 'all' || !!search
  const clearFilters = () => {
    setSearch('')
    setProvider('all')
    setUseCase('all')
    setProcessing('all')
  }

  const renderConfigItem = (config) => {
    const isSelected = selectedConfigId === config._id
    const initial = config.name?.[0]?.toUpperCase() || 'A'
    return (
      <CommandItem
        key={config._id}
        value={`assistant ${config.name} ${config.model_name || ''} ${config.model_id || ''}`}
        onSelect={() => onSelect(config._id)}
        className={cn(
          'gap-3 cursor-pointer',
          isSelected && 'bg-accent/10 text-foreground'
        )}
      >
        <ItemAvatar>
          {config.avatar?.type === 'emoji' ? config.avatar.value : initial}
        </ItemAvatar>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm truncate">{config.name}</span>
            {isSelected && <Check className="h-3.5 w-3.5 text-accent flex-shrink-0" />}
          </div>
          <p className="text-xs text-foreground-tertiary truncate">
            {config.model_name || prettifyModelName(config.model_id)}
          </p>
        </div>
      </CommandItem>
    )
  }

  return (
    <div
      className={cn(
        // Solid floating menu (popover shell is transparent). Not chrome glass.
        SOLID_SURFACE_CLASS,
        'animate-fade-in',
        'w-[min(22rem,calc(100vw-1rem))] max-h-[70vh] flex flex-col overflow-hidden'
      )}
      style={solidPanelSx({ radius: RADII.surface })}
      data-testid="config-selector"
    >
      <Command className="flex-1 flex flex-col overflow-hidden bg-transparent">
        <CommandInput
          value={search}
          onValueChange={setSearch}
          placeholder={tab === 'models' ? t('configSelector.searchByName') : t('configSelector.searchPlaceholder')}
          autoFocus={!isCoarse}
        />

        {/* Segmented Models | Assistants control */}
        <div className="px-2 pb-2 pt-1 shrink-0">
          <div className="flex items-center gap-1 p-1 rounded-lg bg-background-tertiary">
            <button
              type="button"
              onClick={() => setTab('models')}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                tab === 'models'
                  ? 'bg-accent/10 text-accent'
                  : 'text-foreground-tertiary hover:text-foreground'
              )}
            >
              <Zap className="h-3.5 w-3.5" />
              {t('configSelector.tabModels')}
            </button>
            <button
              type="button"
              onClick={() => setTab('assistants')}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                tab === 'assistants'
                  ? 'bg-accent/10 text-accent'
                  : 'text-foreground-tertiary hover:text-foreground'
              )}
            >
              <Bot className="h-3.5 w-3.5" />
              {t('configSelector.tabAssistants')}
              {configs.length > 0 && (
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-background-secondary text-foreground-tertiary">
                  {configs.length}
                </span>
              )}
            </button>
          </div>
        </div>

        {tab === 'models' && (
          <div className="px-2 pb-2 shrink-0 space-y-1.5">
            <div className="grid grid-cols-3 gap-1.5">
              <FilterSelect
                ariaLabel={t('configSelector.filterProvider')}
                value={provider}
                onChange={setProvider}
                options={[
                  { value: 'all', label: t('configSelector.filterAll') },
                  ...providers.map((p) => ({ value: p, label: t(`configSelector.provider.${p}`, { defaultValue: p }) })),
                ]}
              />
              <FilterSelect
                ariaLabel={t('configSelector.filterUse')}
                value={useCase}
                onChange={setUseCase}
                options={[
                  { value: 'all', label: t('configSelector.filterAll') },
                  { value: 'multimodal', label: t('configSelector.useMultimodal') },
                  { value: 'reasoning', label: t('configSelector.useReasoning') },
                  { value: 'fast', label: t('configSelector.useFast') },
                  { value: 'text', label: t('configSelector.useText') },
                ]}
              />
              <FilterSelect
                ariaLabel={t('configSelector.filterProcessing')}
                value={processing}
                onChange={setProcessing}
                options={[
                  { value: 'all', label: t('configSelector.filterAll') },
                  { value: 'cloud', label: t('configSelector.processingCloud') },
                  { value: 'local', label: t('configSelector.processingLocal') },
                ]}
              />
            </div>
            {filtersActive && (
              <button
                type="button"
                onClick={clearFilters}
                className="inline-flex items-center gap-1 text-xs text-foreground-tertiary hover:text-foreground"
              >
                <X className="h-3 w-3" />
                {t('configSelector.clearFilters')}
              </button>
            )}
          </div>
        )}

        <CommandList className="max-h-none flex-1 overflow-y-auto">
          <CommandEmpty>{t('configSelector.noConfigs')}</CommandEmpty>

          {/* Quick Models */}
          {tab === 'models' && (
          <CommandGroup heading={
            <span className="flex items-center gap-1 text-foreground-tertiary">
              <Zap className="h-3 w-3" />
              <span>{t('configSelector.quickModels')}</span>
            </span>
          }>
            {filteredModels.map((model) => {
              const quickId = `quick:${model.id}`
              const isSelected = selectedConfigId === quickId
              return (
                <CommandItem
                  key={model.id}
                  value={`quick ${model.name} ${model.description} ${model.id}`}
                  onSelect={() => handleQuickSelect(model.id)}
                  className={cn(
                    'gap-3 cursor-pointer',
                    isSelected && 'bg-accent/10 text-foreground'
                  )}
                >
                  <ItemAvatar>
                    <ModelLogo logo={model.logo} modelId={model.id} size={20} />
                  </ItemAvatar>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-medium text-sm truncate">{model.name}</span>
                      <TierBadge tier={model.tier} t={t} />
                      {isDeprecated(model.id) && (
                        <span
                          className="h-2 w-2 rounded-full bg-warning flex-shrink-0"
                          title={t('configSelector.deprecated')}
                          aria-label={t('configSelector.deprecated')}
                        />
                      )}
                      {isSelected && <Check className="h-3.5 w-3.5 text-accent flex-shrink-0" />}
                    </div>
                    <p className="text-xs text-foreground-tertiary truncate">
                      {t(`configSelector.modelDesc.${model.descKey}`, { defaultValue: model.description })}
                    </p>
                    {(() => {
                      const live = getById(model.id)?.architecture?.input_modalities
                      const mods = (Array.isArray(live) && live.length) ? live : (model.modalities || [])
                      const ICONS = { text: Type, image: ImageIcon, audio: AudioLines, video: Video, file: FileText }
                      const order = ['text', 'image', 'audio', 'video', 'file']
                      return (
                        <div className="mt-1 flex items-center gap-2 flex-wrap">
                          <div className="flex items-center gap-1">
                            {order.filter(m => mods.includes(m)).map(m => {
                              const Ico = ICONS[m]
                              return <Ico key={m} className="h-3.5 w-3.5 text-foreground-tertiary" aria-label={t(`configSelector.modality.${m}`)} />
                            })}
                          </div>
                          <Meter label={t('configSelector.speed')} value={model.speed} />
                          <Meter label={t('configSelector.intelligence')} value={model.intelligence} />
                        </div>
                      )
                    })()}
                  </div>
                </CommandItem>
              )
            })}
          </CommandGroup>
          )}

          {tab === 'assistants' && (
          <>
          {/* Project assistants — only when a project is active and any configs match */}
          {currentProject && projectConfigs.length > 0 && (
            <CommandGroup heading={
              <span className="flex items-center gap-1 text-foreground-tertiary">
                <FolderOpen className="h-3 w-3" />
                <span>{t('configSelector.projectGroup', { name: currentProject.name })}</span>
              </span>
            }>
              {projectConfigs.map(renderConfigItem)}
            </CommandGroup>
          )}

          {/* My assistants — owned, not pinned to active project */}
          {myConfigs.length > 0 && (
            <CommandGroup heading={
              <span className="text-foreground-tertiary">{t('configSelector.myAssistants')}</span>
            }>
              {myConfigs.map(renderConfigItem)}
            </CommandGroup>
          )}

          {/* Public assistants */}
          {publicConfigs.length > 0 && (
            <CommandGroup heading={
              <span className="flex items-center gap-1 text-foreground-tertiary">
                <Globe className="h-3 w-3" />
                <span>{t('configSelector.public')}</span>
              </span>
            }>
              {publicConfigs.map(renderConfigItem)}
            </CommandGroup>
          )}

          {configs.length === 0 && (
            <div className="py-6 text-center">
              <Bot className="h-8 w-8 text-foreground-tertiary mx-auto mb-2" />
              <p className="text-sm text-foreground-secondary">{t('configSelector.noAssistantsYet')}</p>
              <p className="text-xs text-foreground-tertiary mt-1">{t('configSelector.noAssistantsCreate')}</p>
            </div>
          )}
          </>
          )}
        </CommandList>
      </Command>

      {/* Footer — assistants tab only. No public gallery route exists, so the
          old "browse gallery" link (it 404'd) stays off until that page ships. */}
      {tab === 'assistants' && (
        <div className="p-2 border-t border-border flex gap-2 shrink-0">
          <button
            onClick={() => {
              onClose?.()
              navigate('/configs')
            }}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm text-foreground-secondary hover:bg-background-tertiary hover:text-foreground transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t('configSelector.createNew')}
          </button>
        </div>
      )}
    </div>
  )
}

// Native <select> so the filter stays inside the model popover (a portaled
// Radix Select counts as "outside" and would close PillBar's Popover).
function FilterSelect({ ariaLabel, value, onChange, options }) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        'h-8 w-full min-w-0 rounded-[10px] border border-border bg-background-elevated',
        'px-1.5 text-[11px] text-foreground leading-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
      )}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  )
}

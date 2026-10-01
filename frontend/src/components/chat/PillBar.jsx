import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, AlertTriangle, Lock } from 'lucide-react'
import { cn } from '@/utils/cn'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import ConfigSelector from './ConfigSelector'
import ModelLogo from './ModelLogo'
import { useModelCatalog } from '@/hooks/useModelCatalog'

/**
 * PillBar — the chat's MODEL pill. A single chip-style dropdown that opens the
 * ConfigSelector popover. Company + Team scope now live in the global Header
 * (ScopePillBar), so this no longer carries Project/Workspace pills — it's
 * portaled into the single Header bar via ChatHeader's HeaderSlot.
 */
function ModelAvatar({ selectedConfig, size = 16 }) {
  if (!selectedConfig) {
    return (
      <span
        className="flex items-center justify-center rounded-full bg-accent/15 text-accent text-[9px] font-semibold shrink-0"
        style={{ height: size, width: size }}
      >
        AI
      </span>
    )
  }
  const logo = selectedConfig.avatar?.type === 'logo' ? selectedConfig.avatar.value : null
  if (logo || selectedConfig.model_id) {
    return (
      <span
        className="flex items-center justify-center rounded-full bg-background-tertiary/80 shrink-0"
        style={{ height: size, width: size }}
      >
        <ModelLogo logo={logo} modelId={selectedConfig.model_id} size={Math.max(12, size - 4)} />
      </span>
    )
  }
  if (selectedConfig.avatar?.type === 'emoji') {
    return (
      <span
        className="flex items-center justify-center rounded-full bg-accent/10 text-[10px] shrink-0"
        style={{ height: size, width: size }}
      >
        {selectedConfig.avatar.value}
      </span>
    )
  }
  return (
    <span
      className="flex items-center justify-center rounded-full bg-accent/15 text-accent text-[9px] font-semibold shrink-0"
      style={{ height: size, width: size }}
    >
      {(selectedConfig.name?.[0] || 'A').toUpperCase()}
    </span>
  )
}

export default function PillBar({
  // Model picker props (mirrors the ChatHeader call site)
  selectedConfig,
  configs = [],
  selectedConfigId,
  onSelectConfig,
  // `prominent` = the big/bold empty-composer variant (taller, filled bg, ring,
  // larger avatar). Default = the compact header chip.
  prominent = false,
  // `locked` renders a static, non-interactive chip (no popover) showing a
  // forced model — used by Data Analyzer mode, which pins the model server-side.
  locked = false,
  lockedLabel,
  lockedTitle,
}) {
  const { t } = useTranslation('chat')
  const { getById } = useModelCatalog()
  const [modelOpen, setModelOpen] = useState(false)

  const underlyingModelId = selectedConfigId?.startsWith('quick:')
    ? selectedConfigId.slice('quick:'.length)
    : selectedConfig?.model_id || null
  const catalogEntry = underlyingModelId ? getById(underlyingModelId) : null
  const isDeprecated = Boolean(catalogEntry?.expiration_date)

  // Data Analyzer locks the model server-side — render a static, disabled chip
  // (no popover) so the user sees the forced model and can't switch away.
  if (locked) {
    return (
      <div className="flex items-center min-w-0">
        {/* Static, quiet "locked model" chip — not a dropdown. Lock-led + the
            English model name is LTR-locked so its digits sit right under RTL. */}
        <div
          title={lockedTitle}
          aria-label={lockedTitle}
          dir="ltr"
          className={cn(
            'inline-flex items-center rounded-full cursor-default select-none',
            'bg-accent/[0.06] border border-accent/15 text-foreground-secondary',
            prominent
              ? 'gap-1.5 ps-2 pe-2.5 h-9 text-sm font-medium'
              : 'gap-1 ps-1.5 pe-2 h-7 text-xs font-medium',
          )}
        >
          <Lock size={prominent ? 13 : 11} className="text-accent shrink-0" />
          <span className={cn('truncate', prominent ? 'max-w-[180px]' : 'max-w-[130px]')}>
            {lockedLabel}
          </span>
        </div>
      </div>
    )
  }

  if (!onSelectConfig) return null

  return (
    <div className="flex items-center min-w-0">
      {/* MODEL pill */}
      <Popover open={modelOpen} onOpenChange={setModelOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={t('modelChip.selectModel')}
            className={cn(
              'inline-flex items-center rounded-full text-foreground transition-colors',
              'focus:outline-none focus:ring-2 focus:ring-accent/30',
              prominent
                ? // Empty-composer: big/bold filled chip with ring + larger avatar.
                  'gap-2 ps-2 pe-3 h-9 text-sm font-semibold bg-accent/10 hover:bg-accent/15 border border-accent/20 ring-1 ring-accent/20'
                : // Header: compact chip, bolder than before ("Both").
                  'gap-1.5 ps-1.5 pe-2.5 h-7 text-xs font-semibold bg-accent/10 hover:bg-accent/15 border border-accent/10',
            )}
          >
            <ModelAvatar selectedConfig={selectedConfig} size={prominent ? 20 : 16} />
            <span className={cn('truncate', prominent ? 'max-w-[200px]' : 'max-w-[140px]')}>
              {selectedConfig?.name || t('modelChip.selectAi')}
            </span>
            {isDeprecated && (
              <AlertTriangle
                size={12}
                className="text-warning shrink-0"
                aria-label={t('configSelector.deprecated')}
              />
            )}
            <ChevronDown size={11} className="text-foreground-tertiary shrink-0" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          side="bottom"
          align="start"
          sideOffset={8}
          className="p-0 w-auto border-0 bg-transparent shadow-none"
        >
          <ConfigSelector
            configs={configs}
            selectedConfigId={selectedConfigId}
            onSelect={(id) => {
              onSelectConfig?.(id)
              setModelOpen(false)
            }}
            onClose={() => setModelOpen(false)}
          />
        </PopoverContent>
      </Popover>
    </div>
  )
}

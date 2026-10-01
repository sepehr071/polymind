import { Loader2 } from 'lucide-react';
import { Handle, Position } from 'reactflow';
import { useTranslation } from 'react-i18next';
import { fmtDistanceToNow } from '../../utils/dateLocale';
import { cn } from '../../utils/cn';

export default function CompactNodeShell({
  selected = false,
  isRunning = false,
  hasError = false,
  errorMessage = null,
  icon: Icon,
  iconColor = 'bg-accent/10',
  iconTextColor = 'text-accent',
  title,
  statusDot = null,
  summary,
  lastRunAt = null,
  leftHandles = [],
  rightHandles = [],
  isConnectable = true,
}) {
  const { t } = useTranslation('workflow');
  const useInputRows = leftHandles.some((h) => h.label);
  const showTimestamp = !isRunning && !!lastRunAt;

  return (
    <div
      className={cn(
        'group relative w-[180px] rounded-xl border bg-background transition-shadow',
        selected ? 'border-accent shadow-glow-accent' : 'border-border shadow-sm',
        hasError && 'border-destructive/60 ring-2 ring-destructive/50',
        isRunning && 'animate-pulse',
      )}
    >
      {hasError && (
        <div
          className="absolute -top-1.5 -end-1.5 z-10 w-4 h-4 rounded-full bg-destructive flex items-center justify-center shadow-sm cursor-default"
          title={errorMessage || '!'}
        >
          <span className="text-[9px] font-bold text-white leading-none select-none">!</span>
        </div>
      )}
      <div className="flex items-center gap-2 px-2.5 py-1.5">
        {Icon && (
          <div className={cn('p-1 rounded-md flex-shrink-0', iconColor)}>
            <Icon className={cn('h-3.5 w-3.5', iconTextColor)} />
          </div>
        )}
        <span className="text-xs font-semibold truncate flex-1 text-foreground">
          {title}
        </span>
        {isRunning && (
          <Loader2 className="h-3 w-3 animate-spin text-accent flex-shrink-0" />
        )}
        {!isRunning && statusDot === 'ok' && (
          <span className="h-1.5 w-1.5 rounded-full bg-success flex-shrink-0" />
        )}
        {!isRunning && statusDot === 'error' && (
          <span className="h-1.5 w-1.5 rounded-full bg-destructive flex-shrink-0" />
        )}
      </div>

      {useInputRows && (
        <div className="border-t border-border/40 py-1">
          {leftHandles.map((h) => (
            <div
              key={h.id}
              className="relative flex items-center gap-2 px-2.5 py-1 text-[10px] font-medium text-foreground-secondary"
            >
              <Handle
                type="target"
                position={Position.Left}
                id={h.id}
                className="!w-3 !h-3 !bg-accent !border-2 !border-background"
                isConnectable={isConnectable}
                title={h.label || h.id}
              />
              <span className="truncate">{h.label || h.id}</span>
            </div>
          ))}
        </div>
      )}

      {!useInputRows && leftHandles.map((h) => (
        <Handle
          key={h.id}
          type="target"
          position={Position.Left}
          id={h.id}
          style={{ top: h.top || '50%' }}
          className="!w-3 !h-3 !bg-accent !border-2 !border-background"
          isConnectable={isConnectable}
          title={h.label || h.id}
        />
      ))}

      <div
        className={cn(
          'px-2.5 text-[11px] text-foreground-secondary leading-tight truncate',
          useInputRows
            ? 'border-t border-border/40 py-1.5'
            : showTimestamp ? 'pt-2' : 'pb-2',
        )}
      >
        {summary ?? <span className="opacity-50 italic">{t('compactNodeShell.empty')}</span>}
      </div>

      {showTimestamp && (
        <div className="px-2.5 pb-1.5 text-[9px] text-foreground-tertiary truncate">
          {t('compactNodeShell.lastRun', { time: fmtDistanceToNow(new Date(lastRunAt)) })}
        </div>
      )}

      {rightHandles.map((h) => (
        <Handle
          key={h.id}
          type="source"
          position={Position.Right}
          id={h.id}
          style={{ top: h.top || '50%' }}
          className="!w-3 !h-3 !bg-accent !border-2 !border-background"
          isConnectable={isConnectable}
          title={h.label || h.id}
        />
      ))}

      {rightHandles.filter((h) => h.label).map((h) => (
        <div
          key={`lbl-${h.id}`}
          className="absolute start-full ms-2 -translate-y-1/2 text-[10px] font-medium text-foreground bg-background border border-border/60 px-1.5 py-0.5 rounded whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none shadow-sm z-10"
          style={{ top: h.top || '50%' }}
        >
          {h.label}
        </div>
      ))}
    </div>
  );
}

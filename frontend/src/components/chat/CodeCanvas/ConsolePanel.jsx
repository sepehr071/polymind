import { memo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, Trash2, AlertCircle, Info, AlertTriangle } from 'lucide-react'

/**
 * Console output panel for displaying logs and errors from the code preview
 */
const ConsolePanel = memo(function ConsolePanel({ logs = [], errors = [], onClear }) {
  const { t } = useTranslation('chat')
  const [isExpanded, setIsExpanded] = useState(true)

  // Combine and sort logs and errors by timestamp
  const allEntries = [
    ...logs.map(log => ({ ...log, type: 'log' })),
    ...errors.map(err => ({ ...err, type: 'error', method: 'error', timestamp: Date.now() }))
  ].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))

  const getIcon = (method) => {
    switch (method) {
      case 'error':
        return <AlertCircle className="h-3.5 w-3.5 text-error flex-shrink-0" />
      case 'warn':
        return <AlertTriangle className="h-3.5 w-3.5 text-warning flex-shrink-0" />
      case 'info':
        return <Info className="h-3.5 w-3.5 text-accent flex-shrink-0" />
      default:
        return <span className="w-3.5 h-3.5 flex-shrink-0 text-foreground-secondary text-xs">›</span>
    }
  }

  const getTextColor = (method) => {
    switch (method) {
      case 'error':
        return 'text-error'
      case 'warn':
        return 'text-warning'
      case 'info':
        return 'text-accent'
      default:
        return 'text-foreground'
    }
  }

  return (
    <div className="border-t border-border bg-background-secondary">
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-background-tertiary"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-foreground-secondary" />
          ) : (
            <ChevronUp className="h-4 w-4 text-foreground-secondary" />
          )}
          <span className="text-sm font-medium text-foreground">{t('codeCanvas.console')}</span>
          {allEntries.length > 0 && (
            <span className="text-xs text-foreground-secondary bg-background-tertiary px-1.5 py-0.5 rounded">
              {allEntries.length}
            </span>
          )}
          {errors.length > 0 && (
            <span className="text-xs text-error bg-error/10 px-1.5 py-0.5 rounded">
              {errors.length > 1 ? t('codeCanvas.errorsPlural', { count: errors.length }) : t('codeCanvas.errors', { count: errors.length })}
            </span>
          )}
        </div>
        {allEntries.length > 0 && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onClear?.()
            }}
            className="p-1 hover:bg-background-tertiary rounded text-foreground-secondary hover:text-foreground"
            title={t('codeCanvas.clearConsole')}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Entries */}
      {isExpanded && (
        <div className="max-h-32 overflow-y-auto">
          {allEntries.length === 0 ? (
            <div className="px-3 py-2 text-xs text-foreground-secondary italic">
              {t('codeCanvas.noOutput')}
            </div>
          ) : (
            <div className="divide-y divide-border/50">
              {allEntries.map((entry, index) => (
                <div
                  key={index}
                  className={`px-3 py-1.5 flex items-start gap-2 text-xs font-mono ${
                    entry.method === 'error' ? 'bg-error/5' : ''
                  }`}
                >
                  {getIcon(entry.method)}
                  <div className={`flex-1 break-all ${getTextColor(entry.method)}`}>
                    {entry.type === 'error' ? (
                      <span>
                        {entry.message}
                        {entry.line > 0 && (
                          <span className="text-foreground-secondary ms-2">
                            (line {entry.line}{entry.col > 0 ? `:${entry.col}` : ''})
                          </span>
                        )}
                      </span>
                    ) : (
                      entry.args?.join(' ') || ''
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
})

export default ConsolePanel

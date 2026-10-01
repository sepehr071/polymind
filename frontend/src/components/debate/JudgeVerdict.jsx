import { memo, useMemo } from 'react'
import { Loader2, Gavel, Award } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import MarkdownRenderer from '../chat/MarkdownRenderer'
import { getTextDirection } from '../../utils/rtl'
import { prettifyModelName } from '@/utils/modelName'
import { Card } from '../ui/card'
import { IconTile } from '../ui/icon-tile'
import ModelLogo from '../chat/ModelLogo'

function JudgeVerdict({ config, content, isStreaming, isLoading, isComplete }) {
  const { t } = useTranslation('debate')
  const dir = useMemo(() => getTextDirection(content), [content])
  const logoKey = config?.avatar?.type === 'logo' ? config.avatar.value : null
  const useLogo = Boolean(logoKey || config?.model_id)
  const name = config?.name || 'Judge'

  if (!content && !isLoading && !isComplete) {
    return null
  }

  return (
    <Card className="overflow-hidden">
      {/* Header — subtle accent-soft strip (not a full gradient panel). */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-accent/5">
        <IconTile icon={Gavel} tone="sky" size="lg" />
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
            {t('judge.verdict')}
            {isComplete && <Award className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />}
          </h3>
          <div className="flex items-center gap-2 text-sm text-foreground-secondary">
            {useLogo ? (
              <ModelLogo logo={logoKey} modelId={config?.model_id} size={14} />
            ) : (
              <span>{config?.avatar?.value || '⚖️'}</span>
            )}
            <span>{name}</span>
            {(config?.model_name || config?.model_id) && (
              <span className="text-foreground-tertiary">
                ({config.model_name || prettifyModelName(config.model_id)})
              </span>
            )}
          </div>
        </div>
        {isLoading && (
          <Loader2 className="h-5 w-5 animate-spin text-accent" />
        )}
      </div>

      {/* Content */}
      <div className="p-6">
        {content ? (
          <div
            className="markdown-content"
            dir={dir}
          >
            <MarkdownRenderer content={content} />
            {isStreaming && (
              <span className="inline-block w-2 h-4 bg-accent animate-pulse ms-1" />
            )}
          </div>
        ) : isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <Loader2 className="h-8 w-8 animate-spin text-accent mx-auto mb-3" />
              <p className="text-foreground-secondary">
                {t('judge.reviewing')}
              </p>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  )
}

// Judge props are unchanged while debaters stream, so let the verdict card bail
// out of the per-token DebateArena re-renders. `config` is a stable ref.
function arePropsEqual(prev, next) {
  return (
    prev.config === next.config &&
    prev.content === next.content &&
    prev.isStreaming === next.isStreaming &&
    prev.isLoading === next.isLoading &&
    prev.isComplete === next.isComplete
  )
}

export default memo(JudgeVerdict, arePropsEqual)

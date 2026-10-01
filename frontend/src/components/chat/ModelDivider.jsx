import { memo } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Thin "Now talking to {model}" divider shown when the assistant model
 * changes between two consecutive messages in the conversation.
 */
const ModelDivider = memo(function ModelDivider({ modelName }) {
  const { t } = useTranslation('chat')
  const label = t('markdown.nowTalkingTo', { model: modelName })
  return (
    <div
      className="flex items-center gap-3 text-xs font-semibold tracking-wide text-foreground-tertiary uppercase my-1"
      aria-label={label}
    >
      <div className="flex-1 h-px bg-border" />
      <span>{label}</span>
      <div className="flex-1 h-px bg-border" />
    </div>
  )
})

export default ModelDivider

import { memo, useMemo, useRef, useEffect, useState } from 'react'
import { Loader2, CheckCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getTextDirection } from '../../utils/rtl'
import { prettifyModelName } from '@/utils/modelName'
import MarkdownRenderer from '../chat/MarkdownRenderer'
import { Card } from '../ui/card'
import { Avatar, AvatarFallback } from '../ui/avatar'
import ModelLogo from '../chat/ModelLogo'

function DebaterResponse({ config, content, isStreaming, isLoading, concluded = false }) {
  const { t } = useTranslation('debate')
  const contentRef = useRef(null)
  const endRef = useRef(null)
  // Autoscroll only while pinned to the bottom (mirrors EventStream), so a user
  // reading an earlier round isn't yanked down by every other debater's tokens.
  const [pinned, setPinned] = useState(true)

  useEffect(() => {
    const sentinel = endRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      ([entry]) => setPinned(entry.isIntersecting),
      { root: contentRef.current, rootMargin: '0px 0px -40px 0px', threshold: 0 }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [content])

  useEffect(() => {
    if (pinned && contentRef.current && (isStreaming || content)) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [content, isStreaming, pinned])

  // Direction detection is O(n) over the streaming string — compute once per
  // content change rather than inline on every render.
  const dir = useMemo(() => getTextDirection(content), [content])

  const name = config?.name || 'Debater'
  const logoKey = config?.avatar?.type === 'logo' ? config.avatar.value : null
  const useLogo = Boolean(logoKey || config?.model_id)

  return (
    <Card className="flex flex-col h-full overflow-hidden">
      {/* Header — plain row on the card surface (no tertiary band) */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-border relative">
        <div className="flex items-center gap-2">
          <Avatar size="sm" shape="square">
            <AvatarFallback className="text-base">
              {useLogo ? (
                <ModelLogo logo={logoKey} modelId={config?.model_id} size={16} />
              ) : (
                config?.avatar?.value || '🤖'
              )}
            </AvatarFallback>
          </Avatar>
          <span className="font-medium text-foreground truncate">{name}</span>
          {isLoading && (
            <Loader2 className="h-4 w-4 animate-spin text-accent ms-auto" />
          )}
          {concluded && !isLoading && (
            <div className="ms-auto flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300 text-xs font-medium">
              <CheckCircle className="h-3 w-3" />
              {t('debater.concluded')}
            </div>
          )}
        </div>
        <p className="text-xs text-foreground-tertiary truncate mt-1">
          {config?.model_name || prettifyModelName(config?.model_id)}
        </p>
      </div>

      {/* Content */}
      <div
        ref={contentRef}
        className="flex-1 overflow-y-auto p-4"
      >
        {content ? (
          <div
            className="markdown-content"
            dir={dir}
          >
            <MarkdownRenderer content={content} />
            {isStreaming && (
              <span className="inline-block w-2 h-4 bg-accent animate-pulse ms-1" />
            )}
            <div ref={endRef} />
          </div>
        ) : isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Loader2 className="h-8 w-8 animate-spin text-accent mx-auto mb-2" />
              <p className="text-sm text-foreground-secondary">{t('debater.thinking')}</p>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-foreground-tertiary">{t('debater.waitingForTurn')}</p>
          </div>
        )}
      </div>
    </Card>
  )
}

// DebateArena re-renders the whole rounds grid on every token (the parent's
// per-debater setState mints a fresh `debaterResponses` object). Each
// DebaterResponse receives a stable per-slice `content` string and a stable
// `config` ref, so this comparator lets the other debaters' cards bail while
// one streams.
function arePropsEqual(prev, next) {
  const prevId = prev.config?._id ?? prev.config?.id
  const nextId = next.config?._id ?? next.config?.id
  return (
    prevId === nextId &&
    prev.content === next.content &&
    prev.isStreaming === next.isStreaming &&
    prev.isLoading === next.isLoading &&
    prev.concluded === next.concluded
  )
}

export default memo(DebaterResponse, arePropsEqual)

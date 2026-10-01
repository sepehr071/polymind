import { memo, useRef, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { getTextDirection, containsRTL } from '../../utils/rtl'
import { prettifyModelName } from '@/utils/modelName'
import SaveToKnowledgeButton from '../knowledge/SaveToKnowledgeButton'
import MarkdownRenderer from '../chat/MarkdownRenderer'
import { Card } from '../ui/card'
import { Avatar, AvatarFallback } from '../ui/avatar'
import ModelLogo from '../chat/ModelLogo'

function ArenaPanel({ config, messages, streaming, isLoading, sessionId }) {
  const scrollRef = useRef(null)
  const messagesEndRef = useRef(null)
  // Autoscroll only while the user is pinned to the bottom. An
  // IntersectionObserver on the bottom sentinel tracks "pinned" state, mirroring
  // pages/automate-agent/components/EventStream.jsx so 2-4 panels don't each
  // fire a smooth-scroll animation per token.
  const [pinned, setPinned] = useState(true)

  useEffect(() => {
    const sentinel = messagesEndRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      ([entry]) => setPinned(entry.isIntersecting),
      { root: scrollRef.current, rootMargin: '0px 0px -40px 0px', threshold: 0 }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (pinned) {
      messagesEndRef.current?.scrollIntoView({ block: 'end' })
    }
  }, [messages, streaming, pinned])

  const avatar = config?.avatar?.value || '🤖'
  const name = config?.name || 'AI Assistant'

  return (
    <Card className="flex flex-col h-full overflow-hidden">
      {/* Header — plain row on the card surface (no tertiary band) */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Avatar size="sm" shape="square">
            <AvatarFallback className="text-base">
              {config?.avatar?.type === 'logo' ? (
                <ModelLogo logo={config.avatar.value} modelId={config.model_id} size={16} />
              ) : (
                avatar
              )}
            </AvatarFallback>
          </Avatar>
          <span className="font-medium text-foreground truncate">{name}</span>
        </div>
        <p className="text-xs text-foreground-tertiary truncate mt-1">
          {config?.model_name || prettifyModelName(config?.model_id)}
        </p>
      </div>

      {/* Messages — chat spec: user = accent bubble row-reverse; assistant = flush prose */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg, idx) => (
          msg.role === 'user' ? (
            <div
              key={`${msg.role}-${idx}-${msg.content.slice(0, 16)}`}
              className="flex w-full flex-col items-end rtl:items-start"
            >
              <div className="max-w-[80%] rounded-[16px] rounded-ee-[4px] bg-accent px-4 py-2 text-accent-foreground">
                <p
                  className={`whitespace-pre-wrap ${containsRTL(msg.content) ? 'font-persian' : ''}`}
                  dir={getTextDirection(msg.content)}
                >
                  {msg.content}
                </p>
              </div>
            </div>
          ) : (
            <div
              key={`${msg.role}-${idx}-${msg.content.slice(0, 16)}`}
              className="group"
            >
              <div className="markdown-content">
                <MarkdownRenderer content={msg.content} />
              </div>
              <div className="mt-1 flex items-center gap-1 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
                <SaveToKnowledgeButton
                  message={msg}
                  conversationId={sessionId || null}
                  sourceType="arena"
                />
              </div>
            </div>
          )
        ))}

        {/* Streaming content — assistant flush prose */}
        {streaming != null && streaming !== undefined && (
          <div className="markdown-content">
            <MarkdownRenderer content={streaming} streaming />
            <span className="inline-block w-2 h-4 bg-accent animate-pulse ms-1 align-middle" />
          </div>
        )}

        {/* Loading indicator — only before the first start frame ('' is streaming). */}
        {isLoading && streaming == null && (
          <div className="flex">
            <Loader2 className="h-5 w-5 animate-spin text-accent" />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </Card>
  )
}

// A single model's token updates only ITS streaming slice in ArenaPage state.
// Without memo, the parent's per-token setState re-renders every panel; this
// comparator lets untouched panels bail. `messages` is a stable ref while a
// panel streams (it only changes on complete) so a ref check is sufficient,
// but guard the `|| []` empty-array churn from the parent by treating two empty
// lists as equal.
function arePropsEqual(prev, next) {
  const prevId = prev.config?._id ?? prev.config?.id
  const nextId = next.config?._id ?? next.config?.id
  if (prevId !== nextId) return false
  if (prev.streaming !== next.streaming) return false
  if (prev.isLoading !== next.isLoading) return false
  if (prev.sessionId !== next.sessionId) return false
  if (prev.messages !== next.messages) {
    // Parent does `messages[id] || []`, minting a fresh [] for untouched empty
    // panels every render. Avoid a re-render when both are empty.
    if ((prev.messages?.length || 0) !== (next.messages?.length || 0)) return false
    if ((prev.messages?.length || 0) !== 0) return false
  }
  return true
}

export default memo(ArenaPanel, arePropsEqual)

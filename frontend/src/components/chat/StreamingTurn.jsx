import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import MarkdownRenderer from './MarkdownRenderer'

/**
 * Streaming assistant turn — plain text, ChatGPT-style. No avatar, role row,
 * caption, container, or Stop button: just the streamed markdown body followed
 * by a blinking block caret, or a 3-dot pulse before the first token arrives.
 */
const StreamingTurn = memo(function StreamingTurn({ content, onRunCode }) {
  const { t } = useTranslation('chat')

  return (
    <div>
      {content ? (
        <div className="text-[15px] leading-[1.65] text-foreground">
          <div className="markdown-content">
            <MarkdownRenderer content={content} onRunCode={onRunCode} streaming />
          </div>
          {/* Blinking block cursor */}
          <span
            className="inline-block w-[7px] h-[14px] bg-accent align-text-bottom ms-0.5"
            style={{ animation: 'chat-blink 1s step-end infinite' }}
            aria-hidden="true"
          />
        </div>
      ) : (
        /* 3-dot thinking indicator — pure CSS (.animate-pulse-dot in
           index.css), NOT framer. A framer motion.span here rendered
           permanently static (document.getAnimations() was empty while the
           dots showed), so the loader never moved. CSS keyframes run
           independently of React/framer and are the codebase's established
           thinking-dot pattern. Staggered animation-delay → wave. */
        <div
          className="flex gap-1.5 py-1"
          aria-live="polite"
          aria-label={t('window.aiThinking')}
        >
          {[0, 0.2, 0.4].map((delay, i) => (
            <span
              key={i}
              className="w-2 h-2 bg-accent/60 rounded-full animate-pulse-dot"
              style={{ animationDelay: `${delay}s` }}
            />
          ))}
        </div>
      )}
    </div>
  )
})

export default StreamingTurn

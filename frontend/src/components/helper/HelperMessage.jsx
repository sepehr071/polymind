import { memo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { RotateCcw, AlertTriangle } from 'lucide-react'
import { cn } from '../../utils/cn'
import { Button } from '../ui/button'
import MarkdownRenderer from '../chat/MarkdownRenderer'

/**
 * Single helper message renderer.
 *
 * - `role: 'user'` → right-aligned bubble (`ms-auto` flips correctly in RTL).
 * - `role: 'assistant'` → left-aligned, transparent background.
 * - `isError` → assistant bubble styled as an error affordance with an
 *   optional Retry button (wired via `onRetry`).
 *
 * Assistant content renders through the shared chat `MarkdownRenderer` so code
 * fences get prism syntax highlighting, GFM tables/lists, math and RTL parity —
 * identical to the chat surface. Internal markdown links (`href` starts with
 * `/`) are intercepted at the wrapper and routed via React Router (preserving
 * the SPA), while external links keep `MarkdownRenderer`'s `target="_blank"`
 * `rel="noopener noreferrer"` behavior.
 *
 * Memoized: a streamed chunk only mutates the LAST message object, so every
 * other (referentially stable) row bails out of re-render via shallow prop
 * compare — the whole list no longer re-renders per chunk.
 */
function HelperMessage({ role, content, isError, onRetry }) {
  const { t } = useTranslation('helper')
  const navigate = useNavigate()
  const isUser = role === 'user'

  // Intercept clicks on internal (`/...`) anchors emitted by the assistant so
  // deep links navigate via React Router instead of a full-page load. External
  // links (`http`, `mailto`, …) fall through to MarkdownRenderer's default
  // `target="_blank"` anchor untouched.
  const handleContentClick = useCallback(
    (e) => {
      const anchor = e.target.closest?.('a[href]')
      if (!anchor) return
      const href = anchor.getAttribute('href') || ''
      if (href.startsWith('/') && !href.startsWith('//')) {
        e.preventDefault()
        navigate(href)
      }
    },
    [navigate],
  )

  if (isUser) {
    return (
      <div className="ms-auto max-w-[80%] rounded-2xl rounded-ee-md bg-accent px-4 py-2.5 text-[15px] leading-7 text-accent-foreground shadow-sm">
        <div className="whitespace-pre-wrap break-words">{content}</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="me-auto max-w-full">
        <div className="flex items-start gap-2 rounded-2xl border border-error/30 bg-error/10 px-3 py-2 text-sm text-error">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
          <div className="flex-1 whitespace-pre-wrap break-words leading-relaxed">
            {content}
          </div>
        </div>
        {onRetry && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onRetry}
            className="mt-1.5 h-7 gap-1.5 text-xs text-foreground-tertiary hover:text-foreground"
            animated={false}
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            {t('retry')}
          </Button>
        )}
      </div>
    )
  }

  return (
    <div className="me-auto max-w-full text-[15px] leading-[1.65] text-foreground">
      {/* Avatar-less assistant row (ChatGPT-parity canon): prose flush
          full-width, no leading icon tile — matches the chat surface. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div
        onClick={handleContentClick}
        className={cn(
          'prose prose-sm dark:prose-invert max-w-none',
          // Tighten default markdown spacing for the rail's narrow column
          '[&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-0.5',
          '[&_pre]:my-2',
        )}
      >
        <MarkdownRenderer content={content || ''} />
      </div>
    </div>
  )
}

export default memo(HelperMessage)

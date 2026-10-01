import { useTranslation } from 'react-i18next'
import Icon3D from '@/components/ui/icon-3d'
import TemplateGallery from './TemplateGallery'
import { cn } from '../../utils/cn'

/* ═══════════════════════════════════════════════════════════════════════
   ImageStudioEmptyState — the teaching screen for a fresh Generate tab.

   Shown by ImageThread when the active thread has no turns yet. A centered
   column (768px lane, matching the composer below) walks the user from a
   plain prompt → a suggestion chip → a professional template, top to bottom:
   a 3D picture glyph, a one-line teaching line, a row of fill-not-send
   suggestion chips, then the hero TemplateGallery (featured pro tier + a
   compact browse grid, which owns its own variable-fill dialog).

   Both the chips and the gallery are fill-not-send: the page seeds the
   composer (onPickPrompt / onPickTemplate) and the user sends manually.
   ═══════════════════════════════════════════════════════════════════════ */
export default function ImageStudioEmptyState({ onPickPrompt, onPickTemplate, disabled = false }) {
  const { t } = useTranslation('dashboard')

  const suggestionsRaw = t('imageStudio.emptyState.suggestions', { returnObjects: true })
  const suggestions = (Array.isArray(suggestionsRaw) ? suggestionsRaw : [])
    .slice(0, 4)
    .map((s) => ({ title: s?.title ?? '', prompt: s?.prompt ?? '' }))

  return (
    <div className="w-full max-w-[768px] mx-auto px-4 py-10 flex flex-col items-center gap-7">
      {/* Teaching header — 3D glyph, title, one line. */}
      <div className="flex flex-col items-center gap-3 text-center">
        <Icon3D src="/icons/3d/picture.png" size={72} />
        <h2 className="text-xl font-semibold text-foreground">
          {t('imageStudio.emptyState.title')}
        </h2>
        <p className="max-w-md text-sm text-foreground-secondary">
          {t('imageStudio.emptyState.description')}
        </p>
      </div>

      {/* Suggestion chips — fill-not-send, FLAT pills (radius99, 1px line,
          accent-soft hover). No glass on content chips. */}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap justify-center gap-2">
          {suggestions.map((s, i) => (
            <button
              key={i}
              type="button"
              disabled={disabled}
              onClick={() => s.prompt && onPickPrompt?.(s.prompt)}
              className={cn(
                'inline-flex items-center rounded-full border border-border bg-background px-4 py-2 text-sm',
                'transition-colors duration-200 hover:border-accent/40 hover:bg-accent/5 focus:outline-none',
                'focus-visible:ring-2 focus-visible:ring-accent/40',
                'disabled:opacity-50 disabled:pointer-events-none',
              )}
            >
              <span className="font-medium text-foreground">{s.title}</span>
            </button>
          ))}
        </div>
      )}

      {/* Professional template tier — its own heading + fill dialog live inside. */}
      <div className="w-full">
        <TemplateGallery variant="hero" onSelect={onPickTemplate} disabled={disabled} />
      </div>
    </div>
  )
}

import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import FileDownloadCard from '@/components/ui/FileDownloadCard'
import Reveal from 'reveal.js'
import 'reveal.js/reveal.css'
import 'reveal.js/theme/white.css'

/**
 * DeckPreview — stage 3 (READY). Structural reveal.js RTL preview + .pptx download.
 * Approximate layout-aware preview; themed .pptx is source of truth.
 */
export default function DeckPreview({ outline, file, onReset }) {
  const { t } = useTranslation('presentations')
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    let mounted = true
    const deck = new Reveal(el, {
      embedded: true,
      rtl: true,
      hash: false,
      controls: true,
      progress: true,
      slideNumber: true,
      keyboardCondition: 'focused',
    })
    deck.initialize().then(() => {
      if (!mounted) {
        try {
          deck.destroy()
        } catch {
          /* ignore */
        }
      }
    })
    return () => {
      mounted = false
      try {
        deck.destroy()
      } catch {
        /* ignore */
      }
    }
  }, [outline])

  const slides = Array.isArray(outline?.slides) ? outline.slides : []

  return (
    <div className="space-y-4" dir="rtl">
      {file && (
        <FileDownloadCard artifact={file} downloadLabel={t('preview.download')} tone="sky" />
      )}

      {outline?.title && (
        <h2 className="text-base font-semibold text-foreground" dir="auto">
          {outline.title}
        </h2>
      )}

      <p className="text-xs text-foreground-tertiary">{t('preview.approxNote')}</p>

      <div
        className="reveal overflow-hidden rounded-xl border border-border"
        ref={ref}
        style={{ height: 480 }}
      >
        <div className="slides">
          {slides.map((s, i) => (
            <section key={i} data-background-color="#ffffff">
              <SlideBody slide={s} t={t} />
            </section>
          ))}
        </div>
      </div>

      <Button variant="ghost" onClick={onReset}>
        <RotateCcw className="me-2 h-4 w-4" aria-hidden="true" />
        {t('preview.newDeck')}
      </Button>
    </div>
  )
}

function SlideBody({ slide, t }) {
  const layout = slide?.layout || 'content'
  const title = slide?.title || ''
  const bullets = Array.isArray(slide?.bullets) ? slide.bullets : []

  if (layout === 'quote') {
    return (
      <>
        <blockquote style={{ direction: 'rtl', fontSize: '1.4em' }}>
          {slide.quote || title}
        </blockquote>
        {slide.attribution && (
          <p style={{ direction: 'rtl', opacity: 0.7 }}>— {slide.attribution}</p>
        )}
      </>
    )
  }

  if (layout === 'metrics' && Array.isArray(slide.metrics) && slide.metrics.length) {
    return (
      <>
        <h3 style={{ direction: 'rtl' }}>{title}</h3>
        <div style={{ display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap' }}>
          {slide.metrics.slice(0, 4).map((m, j) => (
            <div key={j} style={{ minWidth: 120, textAlign: 'center' }}>
              <div style={{ fontSize: '1.6em', fontWeight: 700 }} dir="ltr">
                {m.value}
              </div>
              <div style={{ fontSize: '0.85em', direction: 'rtl' }}>{m.label}</div>
              {m.delta && (
                <div style={{ fontSize: '0.75em', opacity: 0.7 }} dir="ltr">
                  {m.delta}
                </div>
              )}
            </div>
          ))}
        </div>
      </>
    )
  }

  if ((layout === 'two_column' || layout === 'comparison') && slide.columns) {
    const L = slide.columns.left || {}
    const R = slide.columns.right || {}
    return (
      <>
        <h3 style={{ direction: 'rtl' }}>{title}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, direction: 'rtl' }}>
          <Col side={L} />
          <Col side={R} />
        </div>
      </>
    )
  }

  if (layout === 'process' && Array.isArray(slide.steps) && slide.steps.length) {
    return (
      <>
        <h3 style={{ direction: 'rtl' }}>{title}</h3>
        <ol style={{ direction: 'rtl', textAlign: 'right' }}>
          {slide.steps.map((st, j) => (
            <li key={j}>
              <strong>{st.title}</strong>
              {st.body ? ` — ${st.body}` : ''}
            </li>
          ))}
        </ol>
      </>
    )
  }

  if (layout === 'feature_grid' && Array.isArray(slide.features) && slide.features.length) {
    return (
      <>
        <h3 style={{ direction: 'rtl' }}>{title}</h3>
        <ul style={{ direction: 'rtl', textAlign: 'right' }}>
          {slide.features.map((f, j) => (
            <li key={j}>
              <strong>{f.title}</strong>
              {f.body ? ` — ${f.body}` : ''}
            </li>
          ))}
        </ul>
      </>
    )
  }

  if (layout === 'timeline' && Array.isArray(slide.events) && slide.events.length) {
    return (
      <>
        <h3 style={{ direction: 'rtl' }}>{title}</h3>
        <ul style={{ direction: 'rtl', textAlign: 'right' }}>
          {slide.events.map((ev, j) => (
            <li key={j}>
              {ev.when ? <span dir="ltr">{ev.when} — </span> : null}
              <strong>{ev.label}</strong>
              {ev.detail ? ` ${ev.detail}` : ''}
            </li>
          ))}
        </ul>
      </>
    )
  }

  if (layout === 'chart' && slide.chart) {
    return (
      <>
        <h3 style={{ direction: 'rtl' }}>{title}</h3>
        <p style={{ direction: 'rtl', opacity: 0.75 }}>
          {t('preview.chartNote', {
            type: slide.chart.type || 'bar',
            n: (slide.chart.categories || []).length,
          })}
        </p>
      </>
    )
  }

  if (layout === 'agenda') {
    const items = slide.items || bullets
    return (
      <>
        <h3 style={{ direction: 'rtl' }}>{title}</h3>
        <ol style={{ direction: 'rtl', textAlign: 'right' }}>
          {items.map((b, j) => (
            <li key={j}>{b}</li>
          ))}
        </ol>
      </>
    )
  }

  return (
    <>
      <h3 style={{ direction: 'rtl' }}>{title}</h3>
      {layout !== 'title' && layout !== 'section' && layout !== 'closing' && bullets.length > 0 && (
        <ul style={{ direction: 'rtl', textAlign: 'right' }}>
          {bullets.map((b, j) => (
            <li key={j}>{b}</li>
          ))}
        </ul>
      )}
      {(layout === 'title' || layout === 'section' || layout === 'closing') && slide.subtitle && (
        <p style={{ direction: 'rtl', opacity: 0.75 }}>{slide.subtitle}</p>
      )}
    </>
  )
}

function Col({ side }) {
  return (
    <div>
      {side.title && <h4 style={{ direction: 'rtl' }}>{side.title}</h4>}
      {Array.isArray(side.bullets) && side.bullets.length > 0 && (
        <ul style={{ direction: 'rtl', textAlign: 'right', fontSize: '0.85em' }}>
          {side.bullets.map((b, j) => (
            <li key={j}>{b}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

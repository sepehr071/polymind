import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2, ArrowUp, ArrowDown, Plus, ArrowRight, Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Card } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export const LAYOUT_IDS = [
  'title',
  'section',
  'agenda',
  'content',
  'content_image',
  'two_column',
  'comparison',
  'metrics',
  'process',
  'timeline',
  'quote',
  'feature_grid',
  'image_hero',
  'chart',
  'closing',
]

/**
 * OutlineEditor — stage 2. Edit the generated deck before rendering.
 * AI picks layout; user can override via Select. Structured fields from the
 * model are preserved on patch (spread); bullets remain the universal text editor.
 */
export default function OutlineEditor({ outline, onChange, onRender, onBack }) {
  const { t } = useTranslation('presentations')
  const [local, setLocal] = useState(() => normalize(outline))

  const commit = useCallback(
    (next) => {
      setLocal(next)
      onChange?.(next)
    },
    [onChange],
  )

  const setTitle = useCallback(
    (title) => commit({ ...local, title }),
    [commit, local],
  )

  const updateSlide = useCallback(
    (index, patch) => {
      const slides = local.slides.map((s, i) => (i === index ? { ...s, ...patch } : s))
      commit({ ...local, slides })
    },
    [commit, local],
  )

  const moveSlide = useCallback(
    (index, dir) => {
      const target = index + dir
      if (target < 0 || target >= local.slides.length) return
      const slides = [...local.slides]
      ;[slides[index], slides[target]] = [slides[target], slides[index]]
      commit({ ...local, slides })
    },
    [commit, local],
  )

  const deleteSlide = useCallback(
    (index) => {
      const slides = local.slides.filter((_, i) => i !== index)
      commit({ ...local, slides })
    },
    [commit, local],
  )

  const addSlide = useCallback(() => {
    const slides = [
      ...local.slides,
      { layout: 'content', title: '', bullets: [], image_prompt: null },
    ]
    commit({ ...local, slides })
  }, [commit, local])

  const canRender = useMemo(
    () => local.slides.length > 0 && local.slides.some((s) => (s.title || s.quote || '').trim()),
    [local.slides],
  )

  return (
    <div className="space-y-5" dir="rtl">
      <section className="space-y-1.5">
        <Label htmlFor="deck-title" className="text-foreground-secondary">
          {t('editor.deckTitle')}
        </Label>
        <Input
          id="deck-title"
          value={local.title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('editor.deckTitle')}
          dir="auto"
        />
      </section>

      <ol className="space-y-4">
        {local.slides.map((slide, index) => (
          <li key={index}>
            <Card className="space-y-3 p-4">
              <div className="flex items-start gap-3">
                <span
                  className="mt-2 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent"
                  dir="ltr"
                  aria-hidden="true"
                >
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
                    <div className="space-y-1.5">
                      <Label
                        htmlFor={`slide-title-${index}`}
                        className="text-xs text-foreground-tertiary"
                      >
                        {t('editor.slideTitle')}
                      </Label>
                      <Input
                        id={`slide-title-${index}`}
                        value={slide.title}
                        onChange={(e) => updateSlide(index, { title: e.target.value })}
                        placeholder={t('editor.slideTitle')}
                        dir="auto"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-foreground-tertiary">
                        {t('editor.layout')}
                      </Label>
                      <Select
                        value={slide.layout || 'content'}
                        onValueChange={(layout) => updateSlide(index, { layout })}
                      >
                        <SelectTrigger className="w-full" dir="auto">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="z-[1400]">
                          {LAYOUT_IDS.map((id) => (
                            <SelectItem key={id} value={id}>
                              {t(`layout.${id}`, { defaultValue: id })}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label
                      htmlFor={`slide-bullets-${index}`}
                      className="text-xs text-foreground-tertiary"
                    >
                      {t('editor.bullets')}
                    </Label>
                    <Textarea
                      id={`slide-bullets-${index}`}
                      value={(slide.bullets || []).join('\n')}
                      onChange={(e) =>
                        updateSlide(index, { bullets: splitBullets(e.target.value) })
                      }
                      placeholder={t('editor.bulletsPlaceholder')}
                      rows={4}
                      dir="auto"
                    />
                    {slideHint(slide, t)}
                  </div>
                </div>

                <div className="flex shrink-0 flex-col gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => moveSlide(index, -1)}
                    disabled={index === 0}
                    aria-label={t('editor.moveUp')}
                    title={t('editor.moveUp')}
                  >
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => moveSlide(index, 1)}
                    disabled={index === local.slides.length - 1}
                    aria-label={t('editor.moveDown')}
                    title={t('editor.moveDown')}
                  >
                    <ArrowDown className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteSlide(index)}
                    aria-label={t('editor.deleteSlide')}
                    title={t('editor.deleteSlide')}
                    className="text-error hover:text-error"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </Card>
          </li>
        ))}
      </ol>

      <Button variant="outline" onClick={addSlide} className="w-full" animated={false}>
        <Plus className="me-2 h-4 w-4" aria-hidden="true" />
        {t('editor.addSlide')}
      </Button>

      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
        <Button variant="ghost" onClick={onBack}>
          <ArrowRight className="me-2 h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          {t('editor.back')}
        </Button>
        <Button onClick={() => onRender(local)} disabled={!canRender} animated>
          <Wand2 className="me-2 h-4 w-4" aria-hidden="true" />
          {t('editor.render')}
        </Button>
      </div>
    </div>
  )
}

function slideHint(slide, t) {
  const layout = slide?.layout || 'content'
  const bits = []
  if (layout === 'metrics' && slide.metrics?.length) {
    bits.push(t('editor.hintMetrics', { count: slide.metrics.length }))
  }
  if ((layout === 'process' || layout === 'feature_grid') && (slide.steps?.length || slide.features?.length)) {
    bits.push(t('editor.hintStructured'))
  }
  if (layout === 'chart' && slide.chart) {
    bits.push(t('editor.hintChart'))
  }
  if (layout === 'quote' && slide.quote) {
    bits.push(slide.quote.slice(0, 80))
  }
  if (!bits.length) return null
  return (
    <p className="text-xs text-foreground-tertiary" dir="auto">
      {bits.join(' · ')}
    </p>
  )
}

function splitBullets(text) {
  return String(text)
    .split('\n')
    .map((line) => line.replace(/\s+$/, ''))
    .filter((line) => line.trim().length > 0)
}

function normalize(outline) {
  const slides = Array.isArray(outline?.slides) ? outline.slides : []
  return {
    ...outline,
    title: outline?.title || '',
    slides: slides.map((s) => ({
      ...s,
      layout: s?.layout || 'content',
      title: s?.title || '',
      bullets: Array.isArray(s?.bullets) ? s.bullets : [],
    })),
  }
}

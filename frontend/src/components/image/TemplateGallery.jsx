import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Wand2 } from 'lucide-react'
import { cn } from '../../utils/cn'
import { promptTemplateService } from '../../services/promptTemplateService'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import TemplateFillDialog from './TemplateFillDialog'

// How many template cards show before the "More" expansion (compact variant).
const COMPACT_COUNT = 6

// Featured pool for the hero variant — professional categories in priority
// order; cards are then sorted by usage_count desc within that pool.
const FEATURED_CATEGORIES = ['infographic', 'software_promo', 'corporate', 'presentation']
const FEATURED_COUNT = 8

// Stable i18n slug from a template name; MUST match the keys in common.json's
// image.templates.* exactly.
const slugify = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')

// Nested tile surface (re-skin): these dense template cards are a GRID of tiles
// living inside an already-glass surface (the composer [+] popover / the hero
// empty-state panel) — glassing each tile would stack a 2nd glass layer + read as
// a card-wall of glass. So they drop to the nested tier: semi-transparent surf,
// 1px line, no heavy shadow (the accent hover border still pops).
const CARD_CLASS = 'border-line bg-bg-2/50'

function TemplateFilterEmpty({ filtered }) {
  const { t } = useTranslation('common')
  if (!filtered) {
    return (
      <p className="py-4 text-center text-sm text-foreground-tertiary">
        {t('image.no_templates')}
      </p>
    )
  }
  return (
    <div className="py-4 text-center">
      <p className="text-sm font-medium text-foreground">{t('image.no_templates_filter_title')}</p>
      <p className="mt-1 text-xs leading-5 text-foreground-secondary">{t('image.no_templates_filter_body')}</p>
    </div>
  )
}

/**
 * Template gallery: category chips + template cards. The single source of
 * template browsing UX (the composer [+] popover and the empty state both
 * mount this). Owns its own TemplateFillDialog for variabled templates.
 *
 * Props:
 *   onSelect   (text: string, template) => void — fired with the resolved body.
 *              No-variable templates fire immediately; variabled ones open the
 *              internal fill dialog first, then fire with the filled text.
 *   disabled   boolean — dim + block interaction.
 *   variant    'compact' | 'hero' (default 'compact')
 *              compact = chip row + 2-col card grid (composer popover).
 *              hero    = featured horizontal-scroll row over the chip row + a
 *                        denser grid (empty state). Distinct tiers, no card wall.
 */
export default function TemplateGallery({ onSelect, disabled = false, variant = 'compact' }) {
  const { t } = useTranslation(['common', 'dashboard'])
  const [selectedCategory, setSelectedCategory] = useState('all')
  const [expanded, setExpanded] = useState(false)
  const [fillTemplate, setFillTemplate] = useState(null)
  const [showFillDialog, setShowFillDialog] = useState(false)

  const isHero = variant === 'hero'

  const { data: categoriesData } = useQuery({
    queryKey: ['promptTemplateCategories'],
    queryFn: () => promptTemplateService.getCategories(),
  })

  // Grid/chip-driven list (compact: filtered; hero: respects the chip selection
  // too, defaulting to all).
  const { data: templatesData, isLoading } = useQuery({
    queryKey: ['promptTemplates', selectedCategory],
    queryFn: () => promptTemplateService.getTemplates(
      selectedCategory === 'all' ? null : selectedCategory
    ),
  })

  // Hero needs the full catalog to compute the featured row independent of the
  // active chip filter.
  const { data: allTemplatesData } = useQuery({
    queryKey: ['promptTemplates', 'all'],
    queryFn: () => promptTemplateService.getTemplates(null),
    enabled: isHero,
  })

  const categories = categoriesData?.categories || []
  const templates = templatesData?.templates || []

  // Featured = professional categories, priority-ordered then usage_count desc.
  const featured = useMemo(() => {
    if (!isHero) return []
    const all = allTemplatesData?.templates || []
    return all
      .filter((tpl) => FEATURED_CATEGORIES.includes(tpl.category))
      .sort((a, b) => {
        const pa = FEATURED_CATEGORIES.indexOf(a.category)
        const pb = FEATURED_CATEGORIES.indexOf(b.category)
        if (pa !== pb) return pa - pb
        return (b.usage_count || 0) - (a.usage_count || 0)
      })
      .slice(0, FEATURED_COUNT)
  }, [isHero, allTemplatesData])

  // Both variants cap the grid behind a More/Less toggle — the hero empty state
  // showing all ~47 templates at once made the page a long scroll.
  const visibleTemplates = expanded ? templates : templates.slice(0, COMPACT_COUNT)

  const handleTemplateClick = (template) => {
    if (disabled) return

    if (template.variables && template.variables.length > 0) {
      setFillTemplate(template)
      setShowFillDialog(true)
      return
    }
    // No variables → use the localized body (falls back to raw English).
    const body = t('image.templates.' + slugify(template.name) + '.body', { defaultValue: template.template_text })
    onSelect(body, template)
  }

  // ── Card renderers ─────────────────────────────────────────────────────────

  const renderGridCard = (template) => {
    const slug = slugify(template.name)
    const title = t('image.templates.' + slug + '.title', { defaultValue: template.name })
    const desc = t('image.templates.' + slug + '.description', { defaultValue: '' })
    return (
      <button
        key={template._id}
        type="button"
        disabled={disabled}
        onClick={() => handleTemplateClick(template)}
        className={cn(
          CARD_CLASS,
          'group flex flex-col gap-1 rounded-2xl border px-3.5 py-2.5 text-start',
          'transition-colors duration-200 hover:border-accent/40 focus:outline-none',
          'focus-visible:ring-2 focus-visible:ring-accent/40',
          'disabled:opacity-50 disabled:pointer-events-none',
        )}
      >
        <span className="flex items-center gap-2 text-sm font-medium text-foreground group-hover:text-accent transition-colors">
          <Wand2 className="h-3.5 w-3.5 shrink-0 text-foreground-tertiary group-hover:text-accent transition-colors" />
          <span className="line-clamp-1">{title}</span>
        </span>
        {desc && (
          <span className="text-xs text-foreground-tertiary line-clamp-2">{desc}</span>
        )}
        {template.variables && template.variables.length > 0 && (
          <span className="mt-0.5 flex flex-wrap gap-1">
            {template.variables.map((v) => (
              <Badge key={v} variant="secondary" className="text-[10px] px-1.5 py-0">
                {t('image.variables.' + v, { defaultValue: v.replace(/_/g, ' ') })}
              </Badge>
            ))}
          </span>
        )}
      </button>
    )
  }

  // Featured cards are wider, always show a description line, and snap-scroll.
  const renderFeaturedCard = (template) => {
    const slug = slugify(template.name)
    const title = t('image.templates.' + slug + '.title', { defaultValue: template.name })
    const desc = t('image.templates.' + slug + '.description', { defaultValue: '' })
    return (
      <button
        key={template._id}
        type="button"
        disabled={disabled}
        onClick={() => handleTemplateClick(template)}
        className={cn(
          CARD_CLASS,
          'group flex w-60 shrink-0 snap-start flex-col gap-1.5 rounded-2xl border px-4 py-3.5 text-start',
          'transition-colors duration-200 hover:border-accent/40 focus:outline-none',
          'focus-visible:ring-2 focus-visible:ring-accent/40',
          'disabled:opacity-50 disabled:pointer-events-none',
        )}
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-foreground group-hover:text-accent transition-colors">
          <Wand2 className="h-4 w-4 shrink-0 text-foreground-tertiary group-hover:text-accent transition-colors" />
          <span className="line-clamp-1">{title}</span>
        </span>
        <span className="min-h-[2.5rem] text-xs text-foreground-tertiary line-clamp-2">
          {desc || t(`image.categories.${template.category}`, { defaultValue: template.category })}
        </span>
        {template.variables && template.variables.length > 0 && (
          <span className="mt-auto flex flex-wrap gap-1 pt-0.5">
            {template.variables.slice(0, 3).map((v) => (
              <Badge key={v} variant="secondary" className="text-[10px] px-1.5 py-0">
                {t('image.variables.' + v, { defaultValue: v.replace(/_/g, ' ') })}
              </Badge>
            ))}
          </span>
        )}
      </button>
    )
  }

  const chipRow = (
    <div className="flex items-center gap-1.5 flex-wrap">
      <Button
        variant={selectedCategory === 'all' ? 'default' : 'outline'}
        size="sm"
        className="h-7 px-2.5 text-xs"
        disabled={disabled}
        onClick={() => { setSelectedCategory('all'); setExpanded(false) }}
      >
        {t('image.all_categories')}
      </Button>
      {categories.map((cat) => (
        <Button
          key={cat.category}
          variant={selectedCategory === cat.category ? 'default' : 'outline'}
          size="sm"
          className="h-7 px-2.5 text-xs"
          disabled={disabled}
          onClick={() => { setSelectedCategory(cat.category); setExpanded(false) }}
        >
          {t(`image.categories.${cat.category}`, { defaultValue: cat.category })}
        </Button>
      ))}
    </div>
  )

  const fillDialog = (
    <TemplateFillDialog
      template={fillTemplate}
      open={showFillDialog}
      onOpenChange={setShowFillDialog}
      onApply={(filledText, template) => onSelect(filledText, template)}
    />
  )

  // ── Hero variant ───────────────────────────────────────────────────────────
  if (isHero) {
    return (
      <div className="space-y-5">
        {/* Featured tier */}
        {featured.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-medium text-foreground-secondary">
              <Wand2 className="h-4 w-4" />
              {t('dashboard:imageStudio.featuredTemplates')}
            </div>
            <div className="-mx-1 flex snap-x snap-mandatory gap-2.5 overflow-x-auto px-1 pb-1">
              {featured.map(renderFeaturedCard)}
            </div>
          </div>
        )}

        {/* Browse tier: chips + denser grid */}
        <div className="space-y-3">
          {chipRow}
          {isLoading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5" aria-busy="true">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-16 rounded-xl" />
              ))}
            </div>
          ) : templates.length === 0 ? (
            <TemplateFilterEmpty filtered={selectedCategory !== 'all'} />
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                {visibleTemplates.map(renderGridCard)}
              </div>
              {templates.length > COMPACT_COUNT && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs text-foreground-secondary"
                  onClick={() => setExpanded((e) => !e)}
                >
                  {expanded
                    ? t('actions.less')
                    : `${t('actions.more')} (${templates.length - COMPACT_COUNT})`}
                </Button>
              )}
            </>
          )}
        </div>

        {fillDialog}
      </div>
    )
  }

  // ── Compact variant ────────────────────────────────────────────────────────
  return (
    <div className="space-y-3">
      {chipRow}

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-xl" />
          ))}
        </div>
      ) : templates.length === 0 ? (
        <TemplateFilterEmpty filtered={selectedCategory !== 'all'} />
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {visibleTemplates.map(renderGridCard)}
          </div>

          {templates.length > COMPACT_COUNT && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-foreground-secondary"
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded
                ? t('actions.less')
                : `${t('actions.more')} (${templates.length - COMPACT_COUNT})`}
            </Button>
          )}
        </>
      )}

      {fillDialog}
    </div>
  )
}

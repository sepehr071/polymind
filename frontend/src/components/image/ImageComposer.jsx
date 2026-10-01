import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Plus, ArrowUp, Loader2, Pencil, X, Paperclip, Ban, Wand2,
  Palette, Ratio, ChevronDown, Cpu, Check, Undo2, Link2Off,
  Maximize2, FileImage, Images, Dices, Hash,
} from 'lucide-react'
import { cn } from '../../utils/cn'
import { prettifyModelName, friendlyModelLabel } from '@/utils/modelName'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/tooltip'
import {
  Popover, PopoverTrigger, PopoverContent,
} from '@/components/ui/popover'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import ResponsivePicker from './ResponsivePicker'
import ImageUploadPreview, { ingestImageFiles, isImageFile, filesFromClipboard } from '../common/ImageUploadPreview'
import TemplateSelector from './TemplateSelector'

// Style preset keys + aspect-ratio set are owned by the page (folded into the
// prompt BEFORE the DLP scan / sent as a real body param) and passed in so this
// component stays purely presentational. Keep these lists mirrored with the
// page's STYLE_SUFFIXES / ASPECT_RATIOS.
//
// ASPECT_GLYPH gives each ratio a tiny preview box (CSS `aspect-ratio`); the set
// is driven by the model's reported capabilities, so cover every ratio the
// backend can emit (1:1·16:9·9:16·4:3·3:4·2:1·1:2·4:5·5:4·3:2·2:3·21:9). A ratio
// missing from this map still renders as a plain text chip (no glyph) — fail-soft.
const ASPECT_GLYPH = {
  '1:1': '1/1', '16:9': '16/9', '9:16': '9/16', '4:3': '4/3', '3:4': '3/4',
  '2:1': '2/1', '1:2': '1/2', '4:5': '4/5', '5:4': '5/4', '3:2': '3/2',
  '2:3': '2/3', '21:9': '21/9', '9:21': '9/21', '3:1': '3/1', '1:3': '1/3',
}

// Empty-capability sentinel: a model object with no `capabilities` (old backend)
// reads every cap as unsupported, so the new controls hide and the composer
// falls back to its legacy aspect-only behaviour.
const NO_CAPS = {}
// MUI IconButton ignores Tailwind h/w/radius (emotion wins). Pin one size so
// +, sparkle, and send share the prompt-row baseline.
const ICON_BTN_SX = { width: 32, height: 32, borderRadius: 999 }
const cap = (caps, key) => (caps || NO_CAPS)[key] || { supported: false }
// Transparency only makes sense for formats with an alpha channel.
const ALPHA_FORMATS = new Set(['png', 'webp'])

/**
 * The Image Studio composer — a solid card (mirrors
 * components/chat/ChatInput.jsx). Purely presentational + controlled: every
 * piece of state lives in the page; the composer renders it and reports edits.
 *
 * Mental model surfaced here: when a base image exists (one is focused in the
 * canvas) every prompt EDITS it — a persistent "Editing v{n}" chip shows the
 * base and the send button is a pencil ("Apply edit"). With no base (fresh
 * session / New image) the send button is ArrowUp ("Generate"). The base is
 * changed by selecting a filmstrip version or New image, NOT a per-turn toggle.
 *
 * Aspect + Style are persistent chip-rail triggers (each a ResponsivePicker —
 * Popover on >=md, bottom Sheet on phones); an active non-default value fills
 * the chip in accent with an inline X to clear it. The model picker is a quiet
 * inline Select on >=md, and on phones collapses to a non-removable rail chip
 * that opens the same model list in a Sheet (so the pill row never squeezes the
 * textarea to vertical text on narrow screens). Reference images + negative
 * prompt + template stay behind the single [+] Popover (one panel, stacked
 * sections — submenus don't work for hosting a textarea / uploader). Negative
 * + refs still surface as removable active-pick chips on the rail.
 *
 * @param {object} props
 * @param {string} props.prompt
 * @param {(v:string)=>void} props.onPromptChange
 * @param {string|null} props.stylePreset                Active style key (or null).
 * @param {(v:string|null)=>void} props.onStyleChange
 * @param {string[]} props.styleKeys                     The 8 preset keys.
 * @param {string|null} props.aspectRatio                Active ratio (or null = Auto).
 * @param {(v:string|null)=>void} props.onAspectChange
 * @param {string[]} props.aspectRatios                  Allowed ratios (backend whitelist).
 * @param {object} [props.caps]                          Selected model capabilities (see GET /image-gen/models). Absent → all new controls hide (fail-open to legacy aspect-only behaviour).
 * @param {string|null} [props.resolution]               Active resolution token (caps.resolution.values) or null = Auto.
 * @param {(v:string|null)=>void} [props.onResolutionChange]
 * @param {number} [props.count]                         Number of images to generate (n). Clamped to caps.n.max.
 * @param {(v:number)=>void} [props.onCountChange]
 * @param {string|null} [props.seed]                     Seed value (string for the controlled input) or null = random.
 * @param {(v:string|null)=>void} [props.onSeedChange]
 * @param {string|null} [props.outputFormat]             Output format (caps.output_format.values) or null = model default.
 * @param {(v:string|null)=>void} [props.onOutputFormatChange]
 * @param {string|null} [props.background]               Background mode ('transparent' | 'opaque' | 'auto') or null = default.
 * @param {(v:string|null)=>void} [props.onBackgroundChange]
 * @param {string} props.negativePrompt
 * @param {(v:string)=>void} props.onNegativeChange
 * @param {Array} props.inputImages                      Reference images (ImageUploadPreview shape).
 * @param {(imgs:Array)=>void} props.onInputImagesChange
 * @param {number} props.maxRefs
 * @param {number} [props.refStartIndex]                 Slots consumed before the first user ref (focused edit-base + assistant bases). User uploads number from refStartIndex+1.
 * @param {boolean} [props.parentSlotActive]             The focused edit-base occupies slot 1 this turn (referenceBase on).
 * @param {number} [props.assistantBaseCount]            Assistant base images occupying leading slots.
 * @param {Array<{n:number,kind:string,preview?:string}>} [props.refSlots]   Numbered reference slots for the @-mention picker (wire order, capped).
 * @param {string} props.model                           Selected model id ('' = none).
 * @param {(id:string)=>void} props.onModelChange
 * @param {Array<{id,name}>} props.models
 * @param {boolean} props.modelsLoading
 * @param {boolean} props.assistantBound                 Hide/lock the model chip when an assistant drives.
 * @param {number|null} props.baseVersion                1-based version of the focused base (null = fresh generate).
 * @param {boolean} [props.referenceBase]                When a base exists, whether this turn EDITS it (true) or ignores it for a fresh take (false).
 * @param {()=>void} [props.onToggleReferenceBase]       Flip referenceBase.
 * @param {boolean} props.isGenerating
 * @param {()=>void} props.onSubmit                       Fires runGenerate in the page.
 * @param {()=>void} [props.onEnhance]                    ✨ Enhance the prompt in place (image-tuned).
 * @param {boolean} [props.isEnhancing]                   Enhance request in flight.
 * @param {boolean} [props.canRevert]                     A pre-enhance prompt is stashed → show Undo.
 * @param {()=>void} [props.onRevert]                     Restore the pre-enhance prompt.
 */
export default function ImageComposer({
  prompt,
  onPromptChange,
  stylePreset,
  onStyleChange,
  styleKeys,
  aspectRatio,
  onAspectChange,
  aspectRatios,
  caps,
  resolution = null,
  onResolutionChange,
  count = 1,
  onCountChange,
  seed = null,
  onSeedChange,
  outputFormat = null,
  onOutputFormatChange,
  background = null,
  onBackgroundChange,
  negativePrompt,
  onNegativeChange,
  inputImages,
  onInputImagesChange,
  maxRefs = 3,
  refStartIndex = 0,
  parentSlotActive = false,
  assistantBaseCount = 0,
  refSlots = [],
  model,
  onModelChange,
  models = [],
  modelsLoading = false,
  assistantBound = false,
  baseVersion = null,
  referenceBase = true,
  onToggleReferenceBase,
  isGenerating = false,
  onSubmit,
  onEnhance,
  isEnhancing = false,
  canRevert = false,
  onRevert,
}) {
  const { t, i18n } = useTranslation('dashboard')
  const { t: tLayout } = useTranslation('layout')
  const textareaRef = useRef(null)
  // Backdrop mirror for the @-mention highlight overlay (scroll-synced to the textarea).
  const backdropRef = useRef(null)
  // Model rail-picker (phones) is controlled so a row tap selects AND closes.
  const [modelPickerOpen, setModelPickerOpen] = useState(false)

  // @-mention picker for reference images. Detect an "@…" token at the caret →
  // dropdown of the numbered reference slots; selecting inserts "@imageN". On
  // send the page rewrites "@imageN" → "Image N" (what the model maps to the Nth
  // reference by order). `mention` = { query, start, end } position in the text.
  const [mention, setMention] = useState(null)
  const [mentionIndex, setMentionIndex] = useState(0)
  const [sel, setSel] = useState({ start: 0, end: 0 })
  const pendingCaretRef = useRef(null)
  const mentionOpen = mention != null
  const mentionMatches = mention
    ? refSlots.filter((s) => {
        const q = mention.query.toLowerCase()
        return !q || `image${s.n}`.startsWith(q) || String(s.n).startsWith(q)
      })
    : []

  // Find an "@word" token immediately before the caret (must start a token, so
  // emails like a@b don't trigger). Returns the token bounds + query, or null.
  const detectMention = (el) => {
    const pos = el?.selectionStart
    if (pos == null) return null
    const m = el.value.slice(0, pos).match(/(?:^|\s)@([a-zA-Z0-9]*)$/)
    if (!m) return null
    const query = m[1]
    return { query, start: pos - query.length - 1, end: pos }
  }

  const syncMention = (el) => {
    setMention(detectMention(el))
    setMentionIndex(0)
  }

  const insertMention = (slot) => {
    if (!mention) return
    const token = `@image${slot.n} `
    const next = prompt.slice(0, mention.start) + token + prompt.slice(mention.end)
    pendingCaretRef.current = mention.start + token.length
    setMention(null)
    onPromptChange(next)
  }

  // Capability gates — each control renders ONLY when the selected model
  // supports it (fail-open: an old backend with no `capabilities` hides all the
  // new controls and falls back to the legacy aspect list passed via props).
  const resCap = cap(caps, 'resolution')
  const aspectCap = cap(caps, 'aspect_ratio')
  const nCap = cap(caps, 'n')
  const seedCap = cap(caps, 'seed')
  const fmtCap = cap(caps, 'output_format')
  const bgCap = cap(caps, 'background')
  // Aspect chips: drive from caps when present, else the legacy prop whitelist.
  const aspectOptions = (caps && aspectCap.supported && aspectCap.values?.length)
    ? aspectCap.values
    : aspectRatios
  const showAspect = caps ? aspectCap.supported : true
  // Count: clamp the rendered max to 10 regardless of an over-generous backend.
  const nMax = Math.min(nCap.max || 1, 10)
  // Transparency toggle is meaningful only with an alpha-capable format chosen.
  const alphaFmt = !outputFormat || ALPHA_FORMATS.has(outputFormat)
  const isTransparent = background === 'transparent'

  const promptPlaceholder = t('imageStudio.promptPlaceholder')

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }, [prompt])

  // After an @-mention insert, restore the caret past the inserted token. Also
  // close a stale mention when the prompt changed from OUTSIDE the textarea
  // (template insert, reset-on-send, enhance) so the dropdown doesn't linger.
  useEffect(() => {
    if (pendingCaretRef.current != null && textareaRef.current) {
      const p = pendingCaretRef.current
      pendingCaretRef.current = null
      textareaRef.current.focus()
      try { textareaRef.current.setSelectionRange(p, p) } catch { /* noop */ }
    } else if (mention && textareaRef.current && !detectMention(textareaRef.current)) {
      setMention(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt])

  // A base image exists AND the user keeps the reference on → this prompt edits
  // it (pencil send). Toggling the reference off (or no base) = fresh generate.
  const editing = baseVersion != null && referenceBase
  const canSend = !!prompt.trim() && !isGenerating && (assistantBound || !!model)

  // Native textarea ::selection paints full-width line boxes over the transparent
  // overlay (covers empty padding). Hide it and draw a glyph-tight highlight on
  // the backdrop instead (`box-decoration-break: clone`).
  const syncSel = (el) => {
    if (!el) return
    const start = el.selectionStart ?? 0
    const end = el.selectionEnd ?? 0
    setSel((prev) => (prev.start === start && prev.end === end ? prev : { start, end }))
  }

  const handleKeyDown = (e) => {
    // @-mention menu owns arrows / enter / tab / escape while open.
    if (mentionOpen && mentionMatches.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setMentionIndex((i) => (i + 1) % mentionMatches.length); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setMentionIndex((i) => (i - 1 + mentionMatches.length) % mentionMatches.length); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insertMention(mentionMatches[mentionIndex] || mentionMatches[0]); return }
      if (e.key === 'Escape') { e.preventDefault(); setMention(null); return }
    }
    if (e.nativeEvent.isComposing || e.keyCode === 229) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (canSend) onSubmit?.()
    }
  }

  const handlePaste = async (e) => {
    if (isGenerating) return
    const pasted = filesFromClipboard(e.clipboardData).filter(isImageFile)
    if (!pasted.length) return
    e.preventDefault()
    const result = await ingestImageFiles(pasted, {
      images: inputImages,
      maxImages: maxRefs,
      t: tLayout,
    })
    if (result.ok) onInputImagesChange(result.images)
  }

  // Negative + refs surface as small removable chips on the rail. Style + aspect
  // are now persistent rail triggers (see RailPicker below), not active chips.
  const chips = [
    negativePrompt.trim() && {
      key: 'negative',
      icon: Ban,
      label: t('imageStudio.negativeShort'),
      onRemove: () => onNegativeChange(''),
      removeLabel: t('imageStudio.removePick', { name: t('imageStudio.negativeShort') }),
    },
    inputImages.length > 0 && {
      key: 'refs',
      icon: Paperclip,
      label: t('imageStudio.refsShort', { count: inputImages.length }),
      onRemove: () => onInputImagesChange([]),
      removeLabel: t('imageStudio.removePick', { name: t('imageStudio.refsShort', { count: inputImages.length }) }),
    },
  ].filter(Boolean)

  return (
    <div className="px-4 md:px-6 pb-4 bg-transparent">
      {/* Relative column wrapper — anchors the @-mention dropdown ABOVE the card
          without being clipped by the form's overflow-hidden (needed for the
          rounded clip). The form fills this wrapper. */}
      <div className="relative mx-auto max-w-[768px]">
        {/* @-mention picker — reference images, addressable as "@imageN". Sits
            above the card (bottom-full) so the rounded clip never crops it. Rows
            use onMouseDown+preventDefault so the textarea keeps focus (no blur
            before the pick registers). */}
        {mentionOpen && (
          <div
            className="absolute bottom-full start-0 z-[1400] mb-2 w-72 max-w-full overflow-hidden rounded-xl border border-border bg-background-elevated shadow-lg"
            role="listbox"
          >
            <div className="border-b border-border px-3 py-1.5 text-[11px] font-medium text-foreground-tertiary">
              {t('imageStudio.mentionHeading')}
            </div>
            {mentionMatches.length === 0 ? (
              <div className="px-3 py-2 text-xs text-foreground-tertiary">
                {refSlots.length === 0 ? t('imageStudio.mentionNoRefs') : t('imageStudio.mentionNoMatch')}
              </div>
            ) : (
              <ul className="max-h-56 overflow-y-auto py-1">
                {mentionMatches.map((s, idx) => (
                  <li key={s.n}>
                    <button
                      type="button"
                      onMouseDown={(e) => { e.preventDefault(); insertMention(s) }}
                      onMouseEnter={() => setMentionIndex(idx)}
                      className={cn(
                        'flex w-full items-center gap-2 px-3 py-1.5 text-start transition-colors',
                        idx === mentionIndex ? 'bg-accent/10' : 'hover:bg-background-tertiary',
                      )}
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-background-tertiary">
                        {s.preview ? (
                          <img src={s.preview} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <FileImage className="h-4 w-4 text-foreground-tertiary" />
                        )}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-xs font-medium text-foreground" dir="ltr">Image {s.n}</span>
                        <span className="block truncate text-[11px] text-foreground-tertiary">
                          {t(`imageStudio.mention_${s.kind}`)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

      {/* Solid composer card. Popovers/pickers (the [+] panel, model
          Select, rail pickers) portal to body — keep overflow-hidden so
          the radius clips. */}
      <form
        onSubmit={(e) => { e.preventDefault(); if (canSend) onSubmit?.() }}
        onPaste={handlePaste}
        className="relative w-full overflow-hidden rounded-2xl border border-border bg-background-secondary shadow-[0_1px_2px_rgb(17_24_39/0.04),0_8px_24px_-12px_rgb(30_71_209/0.14)] transition-colors focus-within:border-accent/70 dark:shadow-none"
      >
        {/* Chip rail — ONE row: the editing-base indicator, the persistent
            Aspect/Style triggers (+ a Model trigger on phones), then removable
            active-pick chips (negative / refs). Wraps only when genuinely out
            of width — separate rows stacked the composer too tall. */}
        <div className="flex flex-wrap items-center gap-1.5 px-3 pt-2.5">
          {/* Base reference toggle — when an image is focused the next prompt
              EDITS it by default (accent "Editing v{n}" chip, pencil send).
              Tapping the chip drops the reference for THIS turn → a fresh
              generate from the prompt alone (muted "Ignoring v{n}", arrow send).
              Re-selecting a version / New image re-arms it (page resets). */}
          {baseVersion != null && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={onToggleReferenceBase}
                  disabled={isGenerating}
                  aria-pressed={referenceBase}
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 h-8 rounded-full text-xs font-medium border transition-colors',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                    referenceBase
                      ? 'bg-accent/15 border-accent/30 text-accent'
                      : 'border-border text-foreground-secondary hover:bg-background-tertiary hover:text-foreground',
                  )}
                >
                  {referenceBase ? <Pencil className="h-3 w-3" /> : <Link2Off className="h-3 w-3" />}
                  <span>
                    {referenceBase
                      ? t('imageStudio.editingVersion', { n: baseVersion })
                      : t('imageStudio.ignoringVersion', { n: baseVersion })}
                  </span>
                </button>
              </TooltipTrigger>
              <TooltipContent>
                {referenceBase
                  ? t('imageStudio.referenceBaseHintOn')
                  : t('imageStudio.referenceBaseHintOff')}
              </TooltipContent>
            </Tooltip>
          )}
          {/* Model trigger — phones only (the inline Select stays on >=md). When
              an assistant drives the thread the model resolves from config_id,
              so this is hidden exactly like the inline Select. */}
          {!assistantBound && (
            <div className="md:hidden">
              <ResponsivePicker
                align="start"
                title={t('imageStudio.modelTrigger')}
                contentClassName="md:w-72"
                open={modelPickerOpen}
                onOpenChange={setModelPickerOpen}
                trigger={
                  <button
                    type="button"
                    disabled={modelsLoading || isGenerating}
                    aria-label={t('imageStudio.model')}
                    className={cn(
                      'flex items-center gap-1 px-2.5 h-8 rounded-full text-xs font-medium transition-colors',
                      'border border-border text-foreground-secondary',
                      'hover:bg-background-tertiary hover:text-foreground',
                      'disabled:opacity-50 disabled:cursor-not-allowed',
                    )}
                  >
                    <Cpu className="h-3 w-3 shrink-0" />
                    <span className="max-w-[10rem] truncate">
                      {t('imageStudio.modelTrigger')}: <span dir="ltr">{model ? (friendlyModelLabel(models.find((m) => m.id === model)?.name) || prettifyModelName(model)) : t('imageStudio.selectModel')}</span>
                    </span>
                    <ChevronDown className="h-3 w-3 shrink-0 opacity-70" />
                  </button>
                }
              >
                <PickerList>
                  {models.map((m) => {
                    const selected = m.id === model
                    return (
                      <PickerRow
                        key={m.id}
                        selected={selected}
                        onClick={() => { onModelChange(m.id); setModelPickerOpen(false) }}
                      >
                        <span className="flex-1 truncate text-start" dir="ltr">{friendlyModelLabel(m.name)}</span>
                        {selected && <Check className="h-4 w-4 shrink-0 text-accent" />}
                      </PickerRow>
                    )
                  })}
                </PickerList>
              </ResponsivePicker>
            </div>
          )}

          {/* Aspect trigger — non-default value fills the chip with an inline X.
              Hidden entirely when the model can't take an aspect ratio (e.g.
              flux / gpt-image, which key off resolution instead). */}
          {showAspect && (
            <RailPicker
              icon={Ratio}
              title={t('imageStudio.aspectTrigger')}
              label={t('imageStudio.aspectTrigger')}
              active={aspectRatio !== null}
              valueLabel={aspectRatio}
              valueLtr
              disabled={isGenerating}
              onClear={() => onAspectChange(null)}
              clearLabel={t('imageStudio.removePick', { name: aspectRatio || '' })}
            >
              <div className="flex flex-wrap gap-1.5">
                <ChipToggle
                  active={aspectRatio === null}
                  onClick={() => onAspectChange(null)}
                >
                  {t('imageStudio.aspectAuto')}
                </ChipToggle>
                {aspectOptions.map((ratio) => (
                  <ChipToggle
                    key={ratio}
                    active={aspectRatio === ratio}
                    onClick={() => onAspectChange(aspectRatio === ratio ? null : ratio)}
                  >
                    {ASPECT_GLYPH[ratio] && (
                      <span
                        aria-hidden="true"
                        className="me-1 inline-block h-3 rounded-[2px] border border-current opacity-70"
                        style={{ aspectRatio: ASPECT_GLYPH[ratio] }}
                      />
                    )}
                    <span dir="ltr">{ratio}</span>
                  </ChipToggle>
                ))}
              </div>
              {/* When a base exists, Auto means "match the base image". */}
              {editing && aspectRatio === null && (
                <p className="mt-2 text-[11px] text-foreground-tertiary">
                  {t('imageStudio.aspectInheritedHint')}
                </p>
              )}
            </RailPicker>
          )}

          {/* Resolution trigger — only models with a resolution capability (e.g.
              gpt-image, flux). Values are model-reported tokens ("512","1K","2K",
              "4K"); Auto = model default. */}
          {resCap.supported && resCap.values?.length > 0 && (
            <RailPicker
              icon={Maximize2}
              title={t('imageStudio.resolutionTrigger')}
              label={t('imageStudio.resolutionTrigger')}
              active={resolution !== null}
              valueLabel={resolution}
              valueLtr
              disabled={isGenerating}
              onClear={() => onResolutionChange?.(null)}
              clearLabel={t('imageStudio.removePick', { name: resolution || '' })}
            >
              <div className="flex flex-wrap gap-1.5">
                <ChipToggle
                  active={resolution === null}
                  onClick={() => onResolutionChange?.(null)}
                >
                  {t('imageStudio.resolutionAuto')}
                </ChipToggle>
                {resCap.values.map((value) => (
                  <ChipToggle
                    key={value}
                    active={resolution === value}
                    onClick={() => onResolutionChange?.(resolution === value ? null : value)}
                  >
                    <span dir="ltr">{value}</span>
                  </ChipToggle>
                ))}
              </div>
            </RailPicker>
          )}

          {/* Format trigger — output format chips + a transparent-background
              toggle. Each row hides when its own capability is unsupported, so
              the picker can carry format alone, transparency alone, or both. */}
          {(fmtCap.supported || bgCap.supported) && (
            <RailPicker
              icon={FileImage}
              title={t('imageStudio.formatTrigger')}
              label={t('imageStudio.formatTrigger')}
              active={outputFormat !== null || isTransparent}
              valueLabel={outputFormat ? outputFormat.toUpperCase() : (isTransparent ? t('imageStudio.transparentBg') : null)}
              valueLtr={!!outputFormat}
              disabled={isGenerating}
              onClear={() => { onOutputFormatChange?.(null); onBackgroundChange?.(null) }}
              clearLabel={t('imageStudio.removePick', { name: t('imageStudio.formatTrigger') })}
            >
              {fmtCap.supported && fmtCap.values?.length > 0 && (
                <>
                  <div className="mb-1.5 text-[11px] font-medium text-foreground-secondary">
                    {t('imageStudio.formatLabel')}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {fmtCap.values.map((value) => (
                      <ChipToggle
                        key={value}
                        active={outputFormat === value}
                        onClick={() => {
                          const next = outputFormat === value ? null : value
                          onOutputFormatChange?.(next)
                          // Dropping to a non-alpha format invalidates transparency.
                          if (next && !ALPHA_FORMATS.has(next) && isTransparent) onBackgroundChange?.(null)
                        }}
                      >
                        <span dir="ltr">{value.toUpperCase()}</span>
                      </ChipToggle>
                    ))}
                  </div>
                </>
              )}
              {bgCap.supported && (bgCap.values?.includes('transparent') ?? true) && (
                <div className={cn(fmtCap.supported && 'mt-3 border-t border-border pt-3')}>
                  <label
                    className={cn(
                      'flex items-center gap-2 text-xs',
                      alphaFmt ? 'text-foreground cursor-pointer' : 'text-foreground-tertiary cursor-not-allowed',
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={isTransparent}
                      disabled={!alphaFmt || isGenerating}
                      onChange={(e) => onBackgroundChange?.(e.target.checked ? 'transparent' : null)}
                      className="h-4 w-4 rounded border-border accent-accent"
                    />
                    {t('imageStudio.transparentBg')}
                  </label>
                  {!alphaFmt && (
                    <p className="mt-1 text-[11px] text-foreground-tertiary">
                      {t('imageStudio.transparentBgHint')}
                    </p>
                  )}
                </div>
              )}
            </RailPicker>
          )}

          {/* Count trigger — 1..nMax stepper for multiple variants per turn. */}
          {nCap.supported && nMax > 1 && (
            <RailPicker
              icon={Images}
              title={t('imageStudio.countTrigger')}
              label={t('imageStudio.countTrigger')}
              active={count > 1}
              valueLabel={count > 1 ? t('imageStudio.countN', { n: count }) : null}
              valueLtr
              disabled={isGenerating}
              onClear={() => onCountChange?.(1)}
              clearLabel={t('imageStudio.removePick', { name: t('imageStudio.countTrigger') })}
            >
              <div className="mb-1.5 text-[11px] font-medium text-foreground-secondary">
                {t('imageStudio.countLabel')}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {Array.from({ length: nMax }, (_, i) => i + 1).map((value) => (
                  <ChipToggle
                    key={value}
                    active={count === value}
                    onClick={() => onCountChange?.(value)}
                  >
                    <span dir="ltr">{t('imageStudio.countN', { n: value })}</span>
                  </ChipToggle>
                ))}
              </div>
            </RailPicker>
          )}

          {/* Style trigger — non-default value fills the chip with an inline X. */}
          <RailPicker
            icon={Palette}
            title={t('imageStudio.styleTrigger')}
            label={t('imageStudio.styleTrigger')}
            active={!!stylePreset}
            valueLabel={stylePreset ? t(`imageStudio.styles.${stylePreset}`) : null}
            disabled={isGenerating}
            onClear={() => onStyleChange(null)}
            clearLabel={t('imageStudio.removePick', {
              name: stylePreset ? t(`imageStudio.styles.${stylePreset}`) : '',
            })}
          >
            <div className="flex flex-wrap gap-1.5">
              <ChipToggle
                active={!stylePreset}
                onClick={() => onStyleChange(null)}
              >
                {t('imageStudio.styleNone')}
              </ChipToggle>
              {styleKeys.map((key) => (
                <ChipToggle
                  key={key}
                  active={stylePreset === key}
                  onClick={() => onStyleChange(stylePreset === key ? null : key)}
                >
                  {t(`imageStudio.styles.${key}`)}
                </ChipToggle>
              ))}
            </div>
          </RailPicker>

          {/* Removable active-pick chips (negative / refs). */}
          {chips.map((chip) => {
            const Icon = chip.icon
            return (
              <span
                key={chip.key}
                className="flex items-center gap-1 px-2.5 h-8 rounded-full bg-accent/10 border border-accent/20 text-accent text-xs font-medium"
              >
                {Icon && <Icon className="h-3 w-3" />}
                <span dir={chip.ltr ? 'ltr' : undefined}>{chip.label}</span>
                <button
                  type="button"
                  onClick={chip.onRemove}
                  aria-label={chip.removeLabel}
                  disabled={isGenerating}
                  className="ms-0.5 h-3.5 w-3.5 rounded-full flex items-center justify-center hover:bg-accent/20 transition-colors disabled:opacity-50"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            )
          })}
        </div>

        {/* Pill row — [+] popover · quiet model chip · textarea · circular send.
            `items-end` pins the round controls to the bottom while the textarea
            grows up. */}
        <div className="flex items-center gap-1.5 px-3 pb-2.5 pt-1.5">
          {/* [+] options — ONE Popover panel (no submenus). Portals to body so
              the pill's paint-containment doesn't clip it. */}
          {/* Single asChild wrap only. Nesting TooltipTrigger asChild AROUND
              PopoverTrigger asChild double-clones the button and clobbers its
              className → it collapsed to a bare 20px icon. aria-label + title
              give the hint without the extra wrapper. */}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                disabled={isGenerating}
                aria-label={t('imageStudio.addOptions')}
                title={t('imageStudio.addOptions')}
                sx={ICON_BTN_SX}
                className="shrink-0"
              >
                <Plus className="h-5 w-5" />
              </Button>
            </PopoverTrigger>

            <PopoverContent
              side="top"
              align="start"
              sideOffset={8}
              className="z-[1400] w-[26rem] max-w-[calc(100vw-1.5rem)] max-h-[70vh] overflow-y-auto p-0"
              /* Dense settings panel over the busy canvas: override the popover's
                 default WEAK glass bg with the STRONG opacity so it reads as
                 opaque (props.sx merges last in ui/popover.jsx). */
              sx={{ backgroundColor: 'rgb(var(--glass-bg) / var(--glass-bg-strong-opacity))' }}
            >
              <div className="divide-y divide-border">
                {/* Reference images */}
                <section className="p-3">
                  <div className="mb-2 flex items-center gap-2 text-xs font-medium text-foreground-secondary">
                    <Paperclip className="h-4 w-4" />
                    {t('imageStudio.referenceImages')}
                  </div>
                  <p className="mb-2 text-[11px] text-foreground-tertiary">
                    {t('imageStudio.referenceImagesDesc', { count: maxRefs })}
                  </p>

                  {/* Slot legend — mirrors the exact order images reach the
                      model (focused edit-base → assistant bases → your uploads)
                      so each can be addressed as "Image N" in the prompt. */}
                  {refStartIndex > 0 && (
                    <ul className="mb-2 space-y-0.5 text-[11px] text-foreground-tertiary">
                      {parentSlotActive && (
                        <li dir={i18n.dir()}>{t('imageStudio.refSlotCurrent', { n: 1 })}</li>
                      )}
                      {Array.from({ length: assistantBaseCount }, (_, k) => {
                        const n = (parentSlotActive ? 1 : 0) + k + 1
                        return <li key={n} dir={i18n.dir()}>{t('imageStudio.refSlotAssistantBase', { n })}</li>
                      })}
                      <li dir={i18n.dir()}>{t('imageStudio.refSlotsYourUploads', { from: refStartIndex + 1 })}</li>
                    </ul>
                  )}

                  {(refStartIndex > 0 || inputImages.length > 1) && (
                    <p className="mb-2 text-[11px] text-foreground-tertiary">
                      {t('imageStudio.refByNumberHint')}
                    </p>
                  )}

                  <ImageUploadPreview
                    images={inputImages}
                    maxImages={maxRefs}
                    startIndex={refStartIndex}
                    cap={maxRefs}
                    onChange={onInputImagesChange}
                    disabled={isGenerating}
                  />

                  {inputImages.length + refStartIndex > maxRefs && (
                    <p className="mt-2 text-[11px] text-error">
                      {t('imageStudio.refOverCapWarning', { count: inputImages.length + refStartIndex - maxRefs })}
                    </p>
                  )}
                </section>

                {/* Negative prompt — canonical field pattern: 13/600 label +
                    a Textarea styled to the Input tokens (radius10, 1px line,
                    2px accent border + 3px accent-soft ring on focus). */}
                <section className="p-3">
                  <label className="mb-1.5 flex items-center gap-2 text-[13px] font-semibold text-foreground-secondary">
                    <Ban className="h-4 w-4" />
                    {t('imageStudio.negativePrompt')}
                  </label>
                  <textarea
                    value={negativePrompt}
                    onChange={(e) => onNegativeChange(e.target.value)}
                    placeholder={t('imageStudio.negativePromptPlaceholder')}
                    rows={3}
                    dir={negativePrompt ? 'auto' : i18n.dir()}
                    className={cn(
                      'w-full resize-none rounded-[10px] border border-border bg-background',
                      'px-3 py-2 text-sm text-foreground placeholder:text-foreground-tertiary placeholder:opacity-60',
                      'transition-[border-color,box-shadow] outline-none',
                      'focus:border-accent focus:shadow-[0_0_0_3px_hsl(var(--accent)/0.18)]',
                    )}
                  />
                </section>

                {/* Seed — power-user reproducibility control. Numeric, LTR
                    (digits are technical tokens). Randomize fills a fresh seed;
                    the inline X clears back to a random seed each run. Hidden
                    when the model can't take a seed. */}
                {seedCap.supported && (
                  <section className="p-3">
                    <label className="mb-1.5 flex items-center gap-2 text-[13px] font-semibold text-foreground-secondary">
                      <Hash className="h-4 w-4" />
                      {t('imageStudio.seedLabel')}
                    </label>
                    <div className="flex items-center gap-1.5">
                      <input
                        type="number"
                        inputMode="numeric"
                        dir="ltr"
                        value={seed ?? ''}
                        onChange={(e) => onSeedChange?.(e.target.value === '' ? null : e.target.value)}
                        placeholder={t('imageStudio.seedPlaceholder')}
                        disabled={isGenerating}
                        className={cn(
                          'flex-1 rounded-[10px] border border-border bg-background',
                          'px-3 py-2 text-sm text-foreground placeholder:text-foreground-tertiary placeholder:opacity-60',
                          'transition-[border-color,box-shadow] outline-none tabular-nums',
                          'focus:border-accent focus:shadow-[0_0_0_3px_hsl(var(--accent)/0.18)]',
                          'disabled:opacity-50 disabled:cursor-not-allowed',
                        )}
                      />
                      <Button
                        type="button"
                        variant="secondary"
                        size="icon"
                        onClick={() => onSeedChange?.(String(Math.floor(Math.random() * 2_147_483_647)))}
                        disabled={isGenerating}
                        aria-label={t('imageStudio.seedRandomize')}
                        title={t('imageStudio.seedRandomize')}
                        className="shrink-0 h-9 w-9 rounded-[10px]"
                      >
                        <Dices className="h-4 w-4" />
                      </Button>
                      {seed != null && seed !== '' && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => onSeedChange?.(null)}
                          disabled={isGenerating}
                          aria-label={t('imageStudio.seedClear')}
                          title={t('imageStudio.seedClear')}
                          className="shrink-0 h-9 w-9 rounded-[10px]"
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                    <p className="mt-1.5 text-[11px] text-foreground-tertiary">
                      {t('imageStudio.seedHint')}
                    </p>
                  </section>
                )}

                {/* Templates */}
                <section className="p-3">
                  <div className="mb-2 flex items-center gap-2 text-xs font-medium text-foreground-secondary">
                    <Wand2 className="h-4 w-4" />
                    {t('imageStudio.quickStartTemplate')}
                  </div>
                  <TemplateSelector
                    onSelect={(templateText) => onPromptChange(templateText)}
                    disabled={isGenerating}
                  />
                </section>
              </div>
            </PopoverContent>
          </Popover>

          {/* Quiet model chip — a compact Select, not a labeled field. Hidden +
              locked when an assistant drives the thread (model resolves from
              config_id). LTR-locked: model ids are technical tokens. Phones use
              the rail-chip Model trigger instead (this would squeeze the
              textarea to vertical text at 390px), so this is >=md only. */}
          {!assistantBound && (
            <div className="hidden md:block w-max max-w-[11rem] shrink-0 self-end">
              <Select value={model} onValueChange={onModelChange} disabled={modelsLoading || isGenerating}>
                <SelectTrigger
                  dir="ltr"
                  className={cn(
                    'h-8 w-auto max-w-[11rem] rounded-full border border-border bg-background',
                    'px-3 text-xs text-foreground-secondary',
                    'hover:bg-background-tertiary hover:text-foreground',
                    'data-[placeholder]:text-foreground-tertiary',
                  )}
                  aria-label={t('imageStudio.model')}
                >
                  <SelectValue placeholder={t('imageStudio.selectModel')} />
                </SelectTrigger>
                <SelectContent>
                  {models.map((m) => (
                    <SelectItem key={m.id} value={m.id} dir="ltr">{friendlyModelLabel(m.name)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Prompt input with an @-mention highlight overlay. A mirror BACKDROP
              div renders the text with @imageN as accent chips; the textarea on
              top has transparent text + a visible caret. Both share identical box
              metrics / dir / wrapping (and scroll in lock-step) so each chip sits
              exactly under its typed token. A textarea can't style substrings —
              this is the standard highlight-within-textarea pattern.
              Content-driven dir="auto" (English→LTR, Persian→RTL); empty → UI dir
              so the placeholder stays aligned. */}
          <div className="relative min-h-8 min-w-0 flex-1 self-center">
            <div
              ref={backdropRef}
              aria-hidden="true"
              dir={prompt ? 'auto' : i18n.dir()}
              className={cn(
                'pointer-events-none absolute inset-0 overflow-hidden text-start',
                'px-1 py-1.5 text-base leading-5 whitespace-pre-wrap break-words text-foreground',
              )}
            >
              {highlightMentions(prompt, sel.start, sel.end)}
            </div>
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(e) => { onPromptChange(e.target.value); syncMention(e.target); syncSel(e.target) }}
              onClick={(e) => { syncMention(e.target); syncSel(e.target) }}
              onSelect={(e) => syncSel(e.target)}
              onKeyUp={(e) => syncSel(e.target)}
              onKeyDown={handleKeyDown}
              onBlur={() => setMention(null)}
              onScroll={(e) => {
                if (backdropRef.current) {
                  backdropRef.current.scrollTop = e.target.scrollTop
                  backdropRef.current.scrollLeft = e.target.scrollLeft
                }
              }}
              placeholder={promptPlaceholder}
              disabled={isGenerating}
              rows={1}
              dir={prompt ? 'auto' : i18n.dir()}
              className={cn(
                'relative block w-full px-1 py-1.5 text-start placeholder:text-start',
                'border-none focus:outline-none resize-none',
                'bg-transparent text-transparent placeholder:text-foreground-tertiary',
                'overflow-y-auto',
                '[scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                'text-base leading-5 whitespace-pre-wrap break-words',
                '[&::selection]:bg-transparent [&::selection]:text-transparent',
                '[&::-moz-selection]:bg-transparent [&::-moz-selection]:text-transparent',
              )}
              style={{ minHeight: '32px', maxHeight: '200px', caretColor: 'hsl(var(--foreground))' }}
            />
          </div>

          {/* ✨ Enhance — rewrite the prompt in place (image-tuned). Quiet accent
              icon button; spins while enhancing. Undo appears once a pre-enhance
              prompt is stashed. Kept LEFT of send so the send glyph stays last. */}
          {onEnhance && (
            <div className="flex h-8 shrink-0 items-center">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={onEnhance}
                    disabled={!prompt.trim() || isGenerating || isEnhancing}
                    aria-label={t('imageStudio.enhance')}
                    sx={ICON_BTN_SX}
                    className="text-accent hover:bg-accent/10"
                  >
                    {isEnhancing ? (
                      <Loader2 className="h-5 w-5 animate-spin" />
                    ) : (
                      <Wand2 className="h-5 w-5" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('imageStudio.enhance')}</TooltipContent>
              </Tooltip>
            </div>
          )}

          {canRevert && (
            <div className="flex h-8 shrink-0 items-center">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={onRevert}
                    disabled={isGenerating || isEnhancing}
                    aria-label={t('imageStudio.revert')}
                    sx={ICON_BTN_SX}
                  >
                    <Undo2 className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('imageStudio.revert')}</TooltipContent>
              </Tooltip>
            </div>
          )}

          {/* Circular send — ArrowUp (Generate) / Pencil (Apply edit). NO
              rtl:-scale-x-100: the glyph must stay upright in RTL. Primary fill
              + the canonical primary glow (no hand-rolled shadow-accent/25). */}
          <div className="flex h-8 shrink-0 items-center">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="submit"
                  variant="default"
                  size="icon"
                  disabled={!canSend}
                  aria-label={editing ? t('imageStudio.applyEdit') : t('imageStudio.generateImage')}
                  sx={ICON_BTN_SX}
                  className={cn(
                    canSend
                      ? 'bg-primary text-primary-foreground shadow-primary-glow hover:bg-primary-dark'
                      : 'bg-background-tertiary text-foreground-tertiary',
                  )}
                >
                  {isGenerating ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : editing ? (
                    <Pencil className="h-5 w-5" />
                  ) : (
                    <ArrowUp className="h-5 w-5" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {editing ? t('imageStudio.applyEdit') : t('imageStudio.generateImage')}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </form>
      </div>
    </div>
  )
}

// Render prompt text with @imageN mentions as inline accent chips for the
// composer's highlight overlay. ONLY color/background/radius — never padding,
// border, margin, or font-weight — so the backdrop's text metrics stay
// byte-identical to the textarea underneath (chips align under the caret).
function highlightMentions(text, selStart = 0, selEnd = 0) {
  if (!text) return null
  const hasSel = selEnd > selStart
  const tokens = []
  const re = /(@image\s*\d+)/gi
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) tokens.push({ start: last, end: m.index, mention: false })
    tokens.push({ start: m.index, end: m.index + m[0].length, mention: true })
    last = m.index + m[0].length
  }
  if (last < text.length) tokens.push({ start: last, end: text.length, mention: false })

  const out = []
  let key = 0
  const emit = (start, end, mention, selected) => {
    if (start >= end) return
    const slice = text.slice(start, end)
    if (mention) {
      out.push(
        <mark
          key={key++}
          className={cn(
            'rounded-[3px] bg-accent/25 text-accent [box-decoration-break:clone] [-webkit-box-decoration-break:clone]',
            selected && 'bg-accent/40',
          )}
        >
          {slice}
        </mark>,
      )
    } else if (selected) {
      out.push(
        <span
          key={key++}
          className="rounded-[2px] bg-accent-muted [box-decoration-break:clone] [-webkit-box-decoration-break:clone]"
        >
          {slice}
        </span>,
      )
    } else {
      out.push(<span key={key++}>{slice}</span>)
    }
  }

  for (const tok of tokens) {
    if (!hasSel || tok.end <= selStart || tok.start >= selEnd) {
      emit(tok.start, tok.end, tok.mention, false)
      continue
    }
    emit(tok.start, Math.max(tok.start, selStart), tok.mention, false)
    emit(Math.max(tok.start, selStart), Math.min(tok.end, selEnd), tok.mention, true)
    emit(Math.min(tok.end, selEnd), tok.end, tok.mention, false)
  }
  return out
}

// A small pill toggle used inside the rail pickers (style / aspect picks).
// Active = filled accent; idle = quiet bordered chip.
function ChipToggle({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1 px-2.5 h-8 rounded-full text-xs font-medium transition-colors',
        active
          ? 'bg-accent text-accent-foreground'
          : 'border border-border text-foreground-secondary hover:bg-background-tertiary hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

/**
 * A persistent chip-rail trigger backed by a ResponsivePicker (Popover on >=md,
 * bottom Sheet on phones). The chip itself is ALWAYS visible: idle it shows the
 * section label with a chevron; with a non-default value active it fills accent,
 * shows the value, and grows an inline X that clears via `onClear` WITHOUT
 * opening the picker.
 */
function RailPicker({
  icon: Icon,
  title,
  label,
  active,
  valueLabel,
  valueLtr = false,
  disabled,
  onClear,
  clearLabel,
  children,
}) {
  return (
    <ResponsivePicker
      align="start"
      title={title}
      contentClassName="md:w-72"
      trigger={
        <button
          type="button"
          disabled={disabled}
          aria-label={title}
          className={cn(
            'flex h-8 items-center gap-1 rounded-full px-2.5 text-xs font-medium transition-colors',
            active
              ? 'bg-accent/10 border border-accent/20 text-accent'
              : 'border border-border text-foreground-secondary hover:bg-background-tertiary hover:text-foreground',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          {Icon && <Icon className="h-3 w-3 shrink-0" />}
          <span className="max-w-[9rem] truncate" dir={active && valueLtr ? 'ltr' : undefined}>
            {active && valueLabel ? valueLabel : label}
          </span>
          {active ? (
            <span
              role="button"
              tabIndex={0}
              aria-label={clearLabel}
              onClick={(e) => { e.stopPropagation(); if (!disabled) onClear() }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  e.stopPropagation()
                  if (!disabled) onClear()
                }
              }}
              className="ms-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full hover:bg-accent/20"
            >
              <X className="h-3 w-3" />
            </span>
          ) : (
            <span className="ms-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center">
              <ChevronDown className="h-3 w-3 opacity-70" />
            </span>
          )}
        </button>
      }
    >
      {children}
    </ResponsivePicker>
  )
}

// A scrollable list wrapper for select-style pickers (model). Caps height so a
// long roster scrolls inside the popover / sheet rather than overflowing it.
function PickerList({ children }) {
  return <div className="flex flex-col gap-0.5 max-h-[50vh] overflow-y-auto">{children}</div>
}

// A single tap-to-select row inside a PickerList — selecting closes the surface
// (ResponsivePicker is uncontrolled here, so the Radix/Sheet trigger's
// outside-interaction close fires after the click handler).
function PickerRow({ selected, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 w-full px-3 h-9 rounded-lg text-sm transition-colors',
        selected
          ? 'bg-accent/10 text-accent font-medium'
          : 'text-foreground hover:bg-background-tertiary',
      )}
    >
      {children}
    </button>
  )
}

import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { imageService } from '../../services/imageService'
import { configService } from '../../services/chatService'
import ImageThread, { useImageThread } from '../../components/image/ImageThread'
import ImageComposer from '../../components/image/ImageComposer'
import SessionSwitcher from '../../components/image/SessionSwitcher'
import ImageDetailModal from '../../components/image/ImageDetailModal'
import PageHeader from '../../components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { useDlpConfirm } from '../../hooks/useDlpConfirm'
import { useBudgetBlock } from '../../hooks/useBudgetBlock'
import { useImageDownload } from '../../hooks/useImageDownload'
import toast from 'react-hot-toast'
import { Image as ImageIcon, Images } from 'lucide-react'

// Style preset chips — each maps to an ENGLISH prompt suffix (image models
// follow English style text best). The suffix folds into the prompt BEFORE the
// DLP scan so scanned text == submitted prompt (confirm_token sha must match).
const STYLE_SUFFIXES = {
  photorealistic: 'photorealistic, sharp focus, natural lighting',
  cinematic: 'cinematic lighting, dramatic composition, film still',
  illustration: 'stylized illustration, clean line work',
  anime: 'anime style, cel shading, vibrant colors',
  '3d-render': '3D render, physically based shading, soft global illumination',
  watercolor: 'watercolor painting, soft washes, textured paper',
  minimalist: 'minimalist composition, lots of negative space',
  isometric: 'isometric view, clean geometric forms',
}
const STYLE_KEYS = Object.keys(STYLE_SUFFIXES)

// Legacy aspect-ratio fallback — used only when the selected model object has no
// `capabilities` (old backend). When caps ARE present the aspect set is driven
// from currentModel.capabilities.aspect_ratio.values. null = model default.
const FALLBACK_ASPECT_RATIOS = ['1:1', '16:9', '9:16', '4:5', '3:2']

const CONTENT_ERROR_RE = /content[_\s-]?policy|safety system|responsible ai|image_safety|prohibited_content|moderation|nsfw|filtered out|unsafe content|policy violation/i
const QUOTA_ERROR_RE = /insufficient[_\s-]?credits|budget_exceeded|credit balance|out of credits|quota|payment required/i

function classifyImageGenError(body, status) {
  const code = body?.code
  if (code === 'content_policy') return 'content'
  if (code === 'budget_exceeded' || code === 'insufficient_credits' || status === 402) return 'quota'
  const text = typeof body?.error === 'string' ? body.error : ''
  if (CONTENT_ERROR_RE.test(text)) return 'content'
  if (QUOTA_ERROR_RE.test(text)) return 'quota'
  return null
}

export default function ImageStudioPage() {
  const { t } = useTranslation('dashboard')
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const assistantId = searchParams.get('assistant') || null

  // DLP pre-flight + violation modal (workspace Content Safety policy).
  const { scan: dlpScan, dlpModal } = useDlpConfirm({ source: 'image_prompt' })
  // Budget/credit 402 catcher (hard block — no "send anyway").
  const { handleBudgetError, budgetModal } = useBudgetBlock()
  // Shared download helper (resolves full base64 by id, then anchor-downloads).
  const { download: downloadImage, isDownloading } = useImageDownload()

  // Composer form state (owned here; ImageThread is presentational + plumbing).
  const [prompt, setPrompt] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [stylePreset, setStylePreset] = useState(null)
  const [aspectRatio, setAspectRatio] = useState(null)
  // OpenRouter Image API capability controls — each is a REAL body param sent
  // only when the selected model supports it (the model-change effect below
  // clamps/clears stale values). resolution/count/format/background are sticky
  // across turns; seed is only sticky once the user sets it.
  const [resolution, setResolution] = useState(null)
  const [count, setCount] = useState(1)
  const [seed, setSeed] = useState(null)
  const [outputFormat, setOutputFormat] = useState(null)
  const [background, setBackground] = useState(null)
  const [inputImages, setInputImages] = useState([])
  const [zoomedImage, setZoomedImage] = useState(null)
  const openedEdit = useRef(false)
  // When a base image is focused, whether the next prompt EDITS it (true) or
  // ignores it for a fresh take (false). Re-armed whenever the focused base
  // changes (selecting a version / a new generated turn) — see effect below.
  const [referenceBase, setReferenceBase] = useState(true)
  // ✨ Enhance: in-flight flag + the pre-enhance prompt stashed for one-click Undo.
  const [isEnhancing, setIsEnhancing] = useState(false)
  const [revertPrompt, setRevertPrompt] = useState(null)
  // Synchronous single-flight lock. isGenerating flips on the next render, so a
  // second click in the same frame would otherwise start another generate.
  const inflightRef = useRef(false)

  // Image assistant bound to NEW threads (?assistant=<configId>). When present,
  // the model picker is locked and config_id rides every generate.
  const { data: assistant } = useQuery({
    queryKey: ['imageAssistant', assistantId],
    queryFn: () => configService.getConfig(assistantId),
    enabled: !!assistantId,
  })
  // getConfig returns { config: {...} } — the assistant is nested.
  const assistantName = assistant?.config?.name || null

  // Image-kind assistants the user can bind to a thread (mirrors ConfigsPage:
  // fetch all configs, filter client-side on parameters.kind === 'image').
  const { data: configsData, isLoading: assistantsLoading } = useQuery({
    queryKey: ['imageAssistants'],
    queryFn: () => configService.getConfigs(),
  })
  const imageAssistants = (configsData?.configs || []).filter(
    (c) => c.parameters?.kind === 'image',
  )

  // Bind / unbind via the ?assistant= query param (replace — no history spam).
  // Unbind sends an empty param set; the bind effect below only fires on a
  // truthy id, so unbinding does NOT start a fresh thread.
  const onBindAssistant = (id) => {
    setSearchParams(id ? { assistant: id } : {}, { replace: true })
  }

  // Conversational thread state machine.
  const thread = useImageThread({ configId: assistantId })

  // When an assistant is present, ensure a fresh thread is in play so config_id
  // binds. Run once per assistant id.
  useEffect(() => {
    if (assistantId) thread.startNewThread()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistantId])

  const { data: modelsData, isLoading: isLoadingModels } = useQuery({
    queryKey: ['imageModels'],
    queryFn: () => imageService.getImageModels(),
  })
  const models = modelsData?.models || []
  const currentModel = models.find((m) => m.id === selectedModel)
  const caps = currentModel?.capabilities
  // max_input_images is the alias of capabilities.input_references.max.
  const maxRefs = currentModel?.max_input_images ?? 3
  // Derive the rendered aspect set from caps (fail-open to the legacy list).
  const aspectOptions = (caps?.aspect_ratio?.supported && caps.aspect_ratio.values?.length)
    ? caps.aspect_ratio.values
    : FALLBACK_ASPECT_RATIOS

  // Auto-select a sensible default once models load (skip while assistant-locked).
  useEffect(() => {
    if (!assistantId && !selectedModel && models.length > 0) {
      const fallback = models.find((m) => m.is_default) || models[0]
      if (fallback?.id) setSelectedModel(fallback.id)
    }
  }, [models, selectedModel, assistantId])

  // On model change, CLAMP/CLEAR any value the new model can't take so a stale
  // unsupported param never ships (which would 400). Keyed on selectedModel (the
  // caps come from the just-loaded model object). No-op until models load.
  useEffect(() => {
    if (!currentModel) return
    const c = currentModel.capabilities
    // No caps at all (old backend) → clear every new control; legacy behaviour.
    if (!c) {
      setResolution(null); setCount(1); setSeed(null)
      setOutputFormat(null); setBackground(null)
      return
    }
    if (!c.n?.supported) setCount(1)
    else setCount((v) => Math.min(Math.max(v, 1), Math.min(c.n.max || 1, 10)))
    if (!c.seed?.supported) setSeed(null)
    if (!c.resolution?.supported) setResolution(null)
    else setResolution((v) => (v && !c.resolution.values?.includes(v) ? null : v))
    if (!c.aspect_ratio?.supported) setAspectRatio(null)
    else setAspectRatio((v) => (v && !c.aspect_ratio.values?.includes(v) ? null : v))
    if (!c.output_format?.supported) setOutputFormat(null)
    else setOutputFormat((v) => (v && !c.output_format.values?.includes(v) ? null : v))
    if (!c.background?.supported) setBackground(null)
    else setBackground((v) => (v && !c.background.values?.includes(v) ? null : v))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedModel])

  const favoriteMutation = useMutation({
    mutationFn: imageService.toggleFavorite,
    onMutate: async (id) => {
      const fromTurn = thread.turns.find((tr) => tr.image?._id === id)?.image?.is_favorite
      const current = thread.focused?._id === id
        ? !!thread.focused.is_favorite
        : zoomedImage?._id === id
          ? !!zoomedImage.is_favorite
          : !!fromTurn
      const next = !current
      thread.patchFavorite(id, next)
      if (zoomedImage?._id === id) {
        setZoomedImage((z) => (z ? { ...z, is_favorite: next } : z))
      }
      await queryClient.cancelQueries({ queryKey: ['imageHistory'] })
      const previousHistory = queryClient.getQueriesData({ queryKey: ['imageHistory'] })
      queryClient.setQueriesData({ queryKey: ['imageHistory'] }, (old) => {
        if (!old?.images) return old
        return {
          ...old,
          images: old.images.map((img) => (
            img._id === id ? { ...img, is_favorite: next } : img
          )),
        }
      })
      return { id, prev: current, previousHistory }
    },
    onError: (_err, id, ctx) => {
      if (!ctx) return
      thread.patchFavorite(id, ctx.prev)
      if (zoomedImage?._id === id) {
        setZoomedImage((z) => (z ? { ...z, is_favorite: ctx.prev } : z))
      }
      ctx.previousHistory?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data)
      })
    },
    onSuccess: (data, id) => {
      if (typeof data?.is_favorite === 'boolean') {
        thread.patchFavorite(id, data.is_favorite)
        if (zoomedImage?._id === id) {
          setZoomedImage((z) => (z ? { ...z, is_favorite: data.is_favorite } : z))
        }
      }
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
    },
  })

  // Compose the final prompt + DLP-scan + budget gate, shared by Generate and
  // the right-pane "Variation" action. Conversation by default: the thread hook
  // sends the FOCUSED image as parent_image_id unless `noParent` (fresh take).
  const runGenerate = async ({ overridePrompt, noParent } = {}) => {
    // @-mention sugar: the composer inserts "@imageN" tokens; rewrite them to
    // "Image N" — the phrasing the model maps to the Nth reference by order.
    // Done BEFORE the scan so scanned text == submitted prompt (token sha match).
    const rawPrompt = (overridePrompt ?? prompt).trim().replace(/@image\s*(\d+)/gi, 'Image $1')
    if (!rawPrompt) {
      toast.error(t('imageStudio.enterPrompt'))
      return
    }
    if (!assistantId && !selectedModel) {
      toast.error(t('imageStudio.selectModelError'))
      return
    }
    if (inflightRef.current) return

    // Style suffix folds into the prompt BEFORE the scan (byte-identical to the
    // submitted prompt). Aspect ratio is a real body param, NOT prompt text.
    const basePrompt = stylePreset
      ? `${rawPrompt}, ${STYLE_SUFFIXES[stylePreset]}`
      : rawPrompt

    const np = negativePrompt.trim()

    // Aspect inheritance before the optimistic tile so the canvas frame matches
    // the result. Editing keeps the base image's aspect unless the user picked one.
    const base = !noParent ? thread.focused : null
    const inheritedAspect = base
      ? (base.aspect_ratio || base.settings?.aspect_ratio || base.metadata?.aspect_ratio)
      : undefined
    const effectiveAspect = base
      ? (aspectRatio || inheritedAspect)
      : aspectRatio

    inflightRef.current = true
    try {
      // Optimistic-first (mirror chat's useChatStream): insert the pending tile +
      // flip isGenerating NOW — before the DLP pre-flight await — so the click has
      // instant feedback (button spinner, canvas frame) instead of a dead
      // window followed by a jarring full-screen swap. Roll back if DLP blocks.
      const tempId = thread.prepareTurn({
        prompt: basePrompt,
        negative_prompt: np,
        aspectRatio: effectiveAspect || '1:1',
      })

      const scanText = np ? `${basePrompt}\n\n[negative]\n${np}` : basePrompt
      const decision = await dlpScan(scanText)
      if (decision === null) {
        thread.discardTurn(tempId) // blocked / cancelled — keep the composer intact
        return
      }

      const imageBase64Array = inputImages.map((img) => img.base64)

      // Capability params — omit when null/unsupported so an unsupported value
      // never reaches a model that would 400 on it (the model-change effect keeps
      // these clamped to the live caps). Seed is sent as an integer when set.
      const seedNum = seed != null && seed !== '' ? Number(seed) : null

      const result = await thread.generate({
        prompt: basePrompt,
        // When an assistant drives the thread the backend resolves the model from
        // config_id; otherwise send the picker selection.
        ...(assistantId ? {} : { model: selectedModel }),
        negative_prompt: np,
        aspect_ratio: effectiveAspect || undefined,
        input_images: imageBase64Array.length > 0 ? imageBase64Array : undefined,
        // New OpenRouter Image API params (capability-gated; omitted when null).
        resolution: caps?.resolution?.supported && resolution ? resolution : undefined,
        n: caps?.n?.supported && count > 1 ? count : undefined,
        seed: caps?.seed?.supported && Number.isFinite(seedNum) ? seedNum : undefined,
        output_format: caps?.output_format?.supported && outputFormat ? outputFormat : undefined,
        background: caps?.background?.supported && background ? background : undefined,
        dlp_confirmed: decision.confirmed || undefined,
        dlp_confirm_token: decision.confirm_token || undefined,
      }, { noParent, tempId, count: caps?.n?.supported ? count : 1 })

      if (result?.ok) {
        // Reset per-turn inputs — the next turn starts clean (aspect auto-inherits
        // from the new base image; style is not auto-reapplied).
        setPrompt('')
        setInputImages([])
        setStylePreset(null)
        setNegativePrompt('')
        setAspectRatio(null)
        thread.setBanner(null)
      } else if (result?.error) {
        const body = result.error.response?.data
        const kind = classifyImageGenError(body, result.error.response?.status)
        if (kind === 'content' || kind === 'quota') {
          thread.setBanner({
            title: t(kind === 'content' ? 'imageStudio.contentBlockedTitle' : 'imageStudio.quotaTitle'),
            description: t(kind === 'content' ? 'imageStudio.contentBlockedBody' : 'imageStudio.quotaBody'),
          })
          return
        }
        if (handleBudgetError(body)) return
        const raw = typeof body?.error === 'string' ? body.error : ''
        thread.setBanner(raw || t('imageStudio.generationFailed'))
      }
    } finally {
      inflightRef.current = false
    }
  }

  // Re-arm base-referencing whenever the focused image changes (a new generated
  // turn, selecting a filmstrip version, switching threads). An explicit
  // "ignore" choice only lasts for the turn the user made it on.
  useEffect(() => {
    setReferenceBase(true)
  }, [thread.focused?._id])

  // Generate from the composer — edits the focused base by default (the hook
  // sends it as parent_image_id); fresh when nothing is focused OR the user
  // toggled the base reference off for this turn.
  const handleGenerate = () => runGenerate({ noParent: !referenceBase })

  // Maps a useDlpConfirm `scan` result into the request-body dlp_* fields.
  const dlpFields = (d) => ({
    dlp_confirmed: d.confirmed,
    ...(d.confirm_token ? { dlp_confirm_token: d.confirm_token } : {}),
    ...(d.redact ? { dlp_redact: true } : {}),
  })

  // Prompt edits clear a stashed Undo (the pre-enhance text is no longer the
  // immediate predecessor once the user types / picks a template).
  const handlePromptChange = (v) => {
    setPrompt(v)
    if (revertPrompt !== null) setRevertPrompt(null)
  }

  // ✨ Enhance the raw prompt in place (image-tuned), DLP-scanned with the same
  // text we send so the confirm-token sha matches. Replace + stash for Undo.
  const handleEnhance = async () => {
    const original = prompt.trim()
    if (!original) {
      toast.error(t('imageStudio.enhanceEmpty'))
      return
    }
    const decision = await dlpScan(original)
    if (decision === null) return // blocked / cancelled
    setIsEnhancing(true)
    try {
      const { enhanced_prompt } = await configService.enhancePrompt(original, dlpFields(decision), 'image')
      setPrompt(enhanced_prompt) // direct set — keeps the stash below intact
      setRevertPrompt(original)
      toast.success(t('imageStudio.enhanced'))
    } catch (error) {
      toast.error(error.response?.data?.error || t('imageStudio.enhanceFailed'))
    } finally {
      setIsEnhancing(false)
    }
  }

  const handleRevert = () => {
    if (revertPrompt === null) return
    setPrompt(revertPrompt)
    setRevertPrompt(null)
    toast.success(t('imageStudio.reverted'))
  }

  // "Variation": re-run the SAME prompt with NO parent (a fresh re-roll).
  const handleVariation = (image) => {
    runGenerate({ overridePrompt: image?.prompt, noParent: true })
  }

  // Continue editing from the gallery lightbox lands here with location state.
  useEffect(() => {
    const editImage = location.state?.editImage
    if (!editImage || openedEdit.current) return
    openedEdit.current = true
    thread.openImageThread(editImage)
  }, [location.state, thread])

  const handleContinueEditing = (image) => {
    thread.openImageThread(image)
    setZoomedImage(null)
  }

  // Detail-modal favorite/delete reuse the grid's own cache flow via invalidate.
  const handleModalFavorite = () => {
    if (zoomedImage) favoriteMutation.mutate(zoomedImage._id)
  }
  const handleModalDelete = async () => {
    if (!zoomedImage) return
    try {
      await imageService.deleteImage(zoomedImage._id)
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
      toast.success(t('imageStudio.imageDeleted'))
    } catch {
      toast.error(t('imageStudio.failedToDelete'))
    }
    setZoomedImage(null)
  }

  // 1-based version of the focused image = the edit base (for the composer's
  // "Editing v{n}" chip). null = fresh generate (nothing focused). Prefer the
  // hook's `versionOf` when present (another agent is adding it); otherwise fall
  // back to the local turn-index computation so ordering doesn't matter.
  const baseVersion = thread.focused
    ? (thread.versionOf?.(thread.focused._id) ?? (() => {
        const i = thread.turns.findIndex((tr) => tr.image && tr.image._id === thread.focused._id)
        return i >= 0 ? i + 1 : null
      })())
    : null

  // Mirror the backend combined_images order (misc_a.py generate_image): the
  // focused edit-base (when referenceBase is on) takes slot 1, then assistant
  // base images, then the user's uploads. The composer numbers reference slots
  // from refStartIndex+1 so the user can address each as "Image N" in the prompt.
  const parentSlotActive = baseVersion != null && referenceBase
  const assistantBaseCount = assistantId
    ? (assistant?.config?.parameters?.base_images?.length ?? 0)
    : 0
  const refStartIndex = (parentSlotActive ? 1 : 0) + assistantBaseCount

  // Reference slots for the composer's @-mention picker — same order/numbering
  // as the legend (focused edit-base → assistant bases → uploads), capped to the
  // model limit. Thumbnails where we have them (focused thumb, upload previews).
  const refSlots = []
  if (parentSlotActive) {
    refSlots.push({ n: 1, kind: 'current', preview: thread.focused?.thumb || null })
  }
  for (let k = 0; k < assistantBaseCount; k++) {
    refSlots.push({ n: (parentSlotActive ? 1 : 0) + k + 1, kind: 'assistant', preview: null })
  }
  inputImages.forEach((img, i) => {
    // base64 (not the blob `preview`) — the popover's unmount revokes blob URLs.
    refSlots.push({ n: refStartIndex + i + 1, kind: 'upload', preview: img.base64 || img.preview })
  })
  const refSlotsCapped = refSlots.filter((s) => s.n <= maxRefs)

  return (
    <div className="h-full flex flex-col">
      <div className="flex-shrink-0 space-y-3 px-4 pt-4 md:px-6 md:pt-6">
        <PageHeader
          icon={ImageIcon}
          title={t('imageStudio.title')}
          subtitle={t('imageStudio.subtitle')}
          actions={<PrivacyBadge mode="cloud" />}
        />
        <Link
          to="/gallery"
          className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-background-tertiary px-3 py-2 text-[12px] leading-5 text-foreground-secondary"
        >
          <Images className="h-4 w-4 shrink-0 text-accent" />
          <span className="min-w-0 flex-1">{t('imageStudio.galleryHint')}</span>
          <span className="inline-flex shrink-0 items-center rounded-lg border border-border bg-background-secondary px-3 py-1.5 text-[11px] font-medium text-foreground">
            {t('imageStudio.openGallery')}
          </span>
        </Link>
        <PrivacyBanner mode="cloud" />
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
            {/* SESSION header — current session title + switcher + assistant badge. */}
            <div className="flex-shrink-0 px-4 md:px-6 pt-4">
              <SessionSwitcher
                threads={thread.threads}
                threadsLoading={thread.threadsLoading}
                activeId={thread.activeId}
                activeThread={thread.activeThread}
                onSelect={thread.selectThread}
                onNew={thread.startNewThread}
                assistantName={assistantName}
                imageAssistants={imageAssistants}
                assistantsLoading={assistantsLoading}
                assistantId={assistantId}
                onBindAssistant={onBindAssistant}
              />
            </div>

            {/* CANVAS + FILMSTRIP — the image-first body (no studio sidebar). */}
            <div className="flex-1 min-h-0 overflow-hidden px-4 md:px-6 pt-4">
              <ImageThread
                thread={thread}
                onDownload={(image) => downloadImage(image)}
                isDownloading={isDownloading}
                onFavorite={(image) => favoriteMutation.mutate(image._id)}
                onVariation={handleVariation}
                onPickPrompt={(text) => handlePromptChange(text)}
                onPickTemplate={(text) => handlePromptChange(text)}
              />
            </div>

            {/* COMPOSER — the chat-style pill (model chip + [+] menu + send). */}
            <div className="flex-shrink-0">
              <ImageComposer
                prompt={prompt}
                onPromptChange={handlePromptChange}
                stylePreset={stylePreset}
                onStyleChange={setStylePreset}
                styleKeys={STYLE_KEYS}
                aspectRatio={aspectRatio}
                onAspectChange={setAspectRatio}
                aspectRatios={aspectOptions}
                caps={caps}
                resolution={resolution}
                onResolutionChange={setResolution}
                count={count}
                onCountChange={setCount}
                seed={seed}
                onSeedChange={setSeed}
                outputFormat={outputFormat}
                onOutputFormatChange={setOutputFormat}
                background={background}
                onBackgroundChange={setBackground}
                negativePrompt={negativePrompt}
                onNegativeChange={setNegativePrompt}
                inputImages={inputImages}
                onInputImagesChange={setInputImages}
                maxRefs={maxRefs}
                refStartIndex={refStartIndex}
                parentSlotActive={parentSlotActive}
                assistantBaseCount={assistantBaseCount}
                refSlots={refSlotsCapped}
                model={selectedModel}
                onModelChange={setSelectedModel}
                models={models}
                modelsLoading={isLoadingModels}
                assistantBound={!!assistantId}
                baseVersion={baseVersion}
                referenceBase={referenceBase}
                onToggleReferenceBase={() => setReferenceBase((v) => !v)}
                isGenerating={thread.isGenerating}
                onSubmit={handleGenerate}
                onEnhance={handleEnhance}
                isEnhancing={isEnhancing}
                canRevert={revertPrompt !== null}
                onRevert={handleRevert}
              />
            </div>
      </div>

      <ImageDetailModal
        open={zoomedImage !== null}
        image={zoomedImage}
        onClose={() => setZoomedImage(null)}
        onDownload={(loadedData) => zoomedImage && downloadImage(zoomedImage, loadedData)}
        isDownloading={isDownloading}
        onToggleFavorite={handleModalFavorite}
        onDelete={handleModalDelete}
        onContinueEditing={handleContinueEditing}
      />

      {dlpModal}
      {budgetModal}
    </div>
  )
}

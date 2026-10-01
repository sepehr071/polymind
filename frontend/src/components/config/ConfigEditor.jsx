import { useState, useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Wand2, Loader2, Undo2, FolderOpen, Lock, Globe, MessageSquare, ImageIcon, Plus, X } from 'lucide-react'
import { configService } from '../../services/chatService'
import { imageService } from '../../services/imageService'
import api from '../../services/api'
import { QUICK_MODELS } from '@/constants/models'
import { useDlpConfirm } from '../../hooks/useDlpConfirm'
import { useProject } from '../../context/ProjectContext'
import { cn } from '../../utils/cn'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Segmented } from '@/components/ui/segmented'

// User-facing creativity levels mapped to underlying temperature values.
// Backend / OpenRouter still receive a numeric temperature; the UI never
// exposes the raw 0..2 scale.
const CREATIVITY_LEVELS = [
  { id: 'low', temperature: 0.2 },
  { id: 'balanced', temperature: 0.5 },
  { id: 'high', temperature: 1.0 },
]

// Soft cap surfaced in the UI. Backend hard-caps at 16; we keep the picker
// tidy at 6 (note in the hint).
const MAX_BASE_IMAGES = 6

function temperatureToCreativity(temp) {
  if (typeof temp !== 'number') return 'balanced'
  if (temp < 0.35) return 'low'
  if (temp > 0.75) return 'high'
  return 'balanced'
}

function SectionHeader({ children }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground-tertiary">
      {children}
    </h3>
  )
}

export default function ConfigEditor({ config, onClose, onSave }) {
  const { t } = useTranslation('common')
  const isEditing = !!config
  const { currentProject } = useProject()
  const projectId = currentProject?._id || null
  const { scan, dlpModal } = useDlpConfirm({ source: 'assistant' })

  const initialVisibility = config?.visibility || (projectId ? 'project' : 'private')

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    model_id: QUICK_MODELS[0]?.id || '',
    model_name: QUICK_MODELS[0]?.name || '',
    system_prompt: '',
    kind: 'text',
    parameters: {
      temperature: 0.5,
    },
    // Base images for image-kind assistants: [{ upload_id, url, thumb_url, name }]
    base_images: [],
    visibility: initialVisibility,
  })

  const [isEnhancing, setIsEnhancing] = useState(false)
  // Original prompt captured before an enhance, so the user can Revert.
  const [revertPrompt, setRevertPrompt] = useState(null)
  const [modelError, setModelError] = useState(false)
  const [isUploadingImages, setIsUploadingImages] = useState(false)
  const fileInputRef = useRef(null)

  const isImage = formData.kind === 'image'

  useEffect(() => {
    if (config) {
      const kind = config.parameters?.kind === 'image' ? 'image' : 'text'
      setFormData({
        name: config.name || '',
        description: config.description || '',
        model_id: config.model_id || '',
        model_name: config.model_name || '',
        system_prompt: config.system_prompt || '',
        kind,
        parameters: {
          temperature: config.parameters?.temperature ?? 0.5,
        },
        base_images: Array.isArray(config.parameters?.base_images)
          ? config.parameters.base_images
          : [],
        visibility: config.visibility || (projectId ? 'project' : 'private'),
      })
    }
  }, [config, projectId])

  // Image models come from the live OpenRouter catalog (image-capable subset),
  // not the curated QUICK_MODELS chat set. Only fetched while the editor is on
  // image kind.
  const { data: imageModelsData, isLoading: imageModelsLoading } = useQuery({
    queryKey: ['image-models'],
    queryFn: imageService.getImageModels,
    enabled: isImage,
    staleTime: 5 * 60 * 1000,
  })

  // Restrict the picker to the curated quick models (the same set the chat
  // composer shows) instead of the full ~300-model OpenRouter catalog. When
  // editing an assistant saved on a non-quick model, keep that model visible so
  // it isn't silently dropped on save. For image kind, the source is the
  // image-model catalog instead.
  const modelOptions = useMemo(() => {
    const base = isImage
      ? (imageModelsData?.models || []).map((m) => ({ id: m.id, name: m.name || m.id }))
      : QUICK_MODELS.map((m) => ({ id: m.id, name: m.name }))
    if (formData.model_id && !base.some((m) => m.id === formData.model_id)) {
      return [{ id: formData.model_id, name: formData.model_name || formData.model_id }, ...base]
    }
    return base
  }, [isImage, imageModelsData, formData.model_id, formData.model_name])

  const saveMutation = useMutation({
    mutationFn: isEditing
      ? (data) => configService.updateConfig(config._id, data)
      : configService.createConfig,
    onSuccess: () => {
      toast.success(isEditing ? t('config.toast_updated') : t('config.toast_created'))
      onSave()
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('config.toast_fail'))
    },
  })

  // Maps a useDlpConfirm `scan` result into the request-body fields the backend
  // dlp_gate expects. Returns null spread (empty object) when there's nothing to add.
  const dlpFields = (r) => ({
    dlp_confirmed: r.confirmed,
    ...(r.confirm_token ? { dlp_confirm_token: r.confirm_token } : {}),
    ...(r.redact ? { dlp_redact: true } : {}),
  })

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!formData.name.trim()) {
      toast.error(t('config.toast_name_required'))
      return
    }

    if (!formData.model_id) {
      setModelError(true)
      toast.error(t('config.toast_model_required'))
      return
    }
    setModelError(false)

    // DLP pre-flight on the system prompt / instructions. `null` = user
    // dismissed / blocked.
    const r = await scan(formData.system_prompt)
    if (r === null) return

    // Persist kind + (image) base_images or (text) temperature under
    // `parameters`, per the backend contract.
    const parameters = isImage
      ? { kind: 'image', base_images: formData.base_images }
      : { kind: 'text', temperature: formData.parameters.temperature }

    const payload = {
      name: formData.name,
      description: formData.description,
      model_id: formData.model_id,
      model_name: formData.model_name,
      system_prompt: formData.system_prompt,
      visibility: formData.visibility,
      parameters,
      ...dlpFields(r),
    }
    if (!isEditing && payload.visibility === 'project' && projectId) {
      payload.project_id = projectId
    }

    saveMutation.mutate(payload)
  }

  const handleChange = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  // Switching kind resets the model to a sensible default for the new kind so
  // an image model never lingers on a text assistant (or vice-versa).
  const handleKindChange = (nextKind) => {
    if (nextKind === formData.kind) return
    setModelError(false)
    setFormData((prev) => ({
      ...prev,
      kind: nextKind,
      model_id: nextKind === 'text' ? (QUICK_MODELS[0]?.id || '') : '',
      model_name: nextKind === 'text' ? (QUICK_MODELS[0]?.name || '') : '',
    }))
  }

  const handleModelChange = (modelId) => {
    const model = modelOptions.find((m) => m.id === modelId)
    setModelError(false)
    setFormData((prev) => ({
      ...prev,
      model_id: modelId,
      model_name: model?.name || modelId,
    }))
  }

  const handleCreativityChange = (levelId) => {
    const level = CREATIVITY_LEVELS.find((l) => l.id === levelId)
    if (!level) return
    setFormData((prev) => ({
      ...prev,
      parameters: { ...prev.parameters, temperature: level.temperature },
    }))
  }

  // Upload each picked file to disk-backed storage and store stable refs
  // (upload_id + urls + name) the backend re-validates on save.
  const handleBaseImageFiles = async (fileList) => {
    const files = Array.from(fileList || []).filter((f) => f.type.startsWith('image/'))
    if (files.length === 0) return

    const remaining = MAX_BASE_IMAGES - formData.base_images.length
    if (remaining <= 0) {
      toast.error(t('config.base_images_max', { max: MAX_BASE_IMAGES }))
      return
    }
    const toUpload = files.slice(0, remaining)

    setIsUploadingImages(true)
    try {
      const uploaded = await Promise.all(
        toUpload.map(async (file) => {
          const fd = new FormData()
          fd.append('file', file)
          const res = await api.post('/uploads/image', fd, {
            headers: { 'Content-Type': 'multipart/form-data' },
          })
          const up = res.data?.upload
          if (!up?.id) throw new Error('upload failed')
          return {
            upload_id: up.id,
            url: up.url,
            thumb_url: up.thumbnail_url || up.url,
            name: up.original_name || file.name,
          }
        })
      )
      setFormData((prev) => ({ ...prev, base_images: [...prev.base_images, ...uploaded] }))
    } catch (error) {
      toast.error(error.response?.data?.error || t('config.base_images_upload_fail'))
    } finally {
      setIsUploadingImages(false)
    }
  }

  const handleRemoveBaseImage = (uploadId) => {
    setFormData((prev) => ({
      ...prev,
      base_images: prev.base_images.filter((img) => img.upload_id !== uploadId),
    }))
  }

  const handleEnhancePrompt = async () => {
    if (!formData.system_prompt.trim()) {
      toast.error(t('config.enhance_empty'))
      return
    }

    const original = formData.system_prompt

    // DLP pre-flight on the prompt we're about to send to the enhancer.
    const r = await scan(original)
    if (r === null) return

    setIsEnhancing(true)
    try {
      // Image assistants' instructions are a style preamble prepended to every
      // image prompt → enhance them with the image-tuned template, not persona.
      const { enhanced_prompt } = await configService.enhancePrompt(
        original, dlpFields(r), isImage ? 'image' : 'assistant',
      )
      handleChange('system_prompt', enhanced_prompt)
      setRevertPrompt(original) // enable one-click Revert to the pre-enhance text
      toast.success(t('config.enhanced'))
    } catch (error) {
      toast.error(error.response?.data?.error || t('config.enhance_fail'))
    } finally {
      setIsEnhancing(false)
    }
  }

  const handleRevertPrompt = () => {
    if (revertPrompt === null) return
    setFormData((prev) => ({ ...prev, system_prompt: revertPrompt }))
    setRevertPrompt(null)
    toast.success(t('config.reverted'))
  }

  const creativity = temperatureToCreativity(formData.parameters.temperature)

  const KIND_OPTIONS = [
    { id: 'text', label: t('config.kind_text'), Icon: MessageSquare },
    { id: 'image', label: t('config.kind_image'), Icon: ImageIcon },
  ]

  const VISIBILITY_OPTIONS = [
    ...(projectId
      ? [{
          id: 'project',
          Icon: FolderOpen,
          title: t('config.visibility_project'),
          hint: currentProject?.name,
        }]
      : []),
    {
      id: 'private',
      Icon: Lock,
      title: t('config.visibility_private'),
      hint: t('config.visibility_private_hint'),
    },
    {
      id: 'public',
      Icon: Globe,
      title: t('config.visibility_public'),
      hint: t('config.visibility_public_hint'),
    },
  ]

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? t('config.edit_title') : t('config.create_title')}
          </DialogTitle>
        </DialogHeader>

        <form id="config-editor-form" onSubmit={handleSubmit} className="overflow-y-auto max-h-[calc(90vh-140px)] px-1">
          <div className="space-y-8">
            {/* ─── Type ─── */}
            <section className="space-y-2">
              <Label>{t('config.kind_label')}</Label>
              <Segmented
                ariaLabel={t('config.kind_label')}
                size="md"
                value={formData.kind}
                onChange={handleKindChange}
                className="flex w-full [&>button]:flex-1"
                items={KIND_OPTIONS.map(({ id, label, Icon }) => ({
                  value: id,
                  label,
                  icon: <Icon className="h-4 w-4" />,
                }))}
              />
              <p className="text-xs text-foreground-tertiary">{t('config.kind_hint')}</p>
            </section>

            {/* ─── Identity ─── */}
            <section className="space-y-4">
              <SectionHeader>{t('config.section_identity')}</SectionHeader>

              <div className="space-y-2">
                <Label htmlFor="name">
                  {t('config.name_label')}
                  <span className="text-error" aria-hidden="true"> *</span>
                </Label>
                <Input
                  id="name"
                  type="text"
                  value={formData.name}
                  onChange={(e) => handleChange('name', e.target.value)}
                  placeholder={t('config.name_placeholder')}
                  required
                />
                <p className="text-xs text-foreground-tertiary">{t('config.name_hint')}</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">{t('config.description_label')}</Label>
                <Input
                  id="description"
                  type="text"
                  value={formData.description}
                  onChange={(e) => handleChange('description', e.target.value)}
                  placeholder={t('config.description_placeholder')}
                />
                <p className="text-xs text-foreground-tertiary">{t('config.description_hint')}</p>
              </div>
            </section>

            {/* ─── Behavior ─── */}
            <section className="space-y-4">
              <SectionHeader>{t('config.section_behavior')}</SectionHeader>

              <div className="space-y-2">
                <Label htmlFor="model">
                  {isImage ? t('config.image_model_label') : t('config.model_label')}
                  <span className="text-error" aria-hidden="true"> *</span>
                </Label>
                <Select value={formData.model_id} onValueChange={handleModelChange}>
                  <SelectTrigger
                    id="model"
                    dir="ltr"
                    aria-invalid={modelError}
                    aria-describedby={modelError ? 'model-error' : undefined}
                    className={cn('text-start', modelError && 'border-error focus-visible:ring-error')}
                  >
                    <SelectValue
                      placeholder={
                        isImage && imageModelsLoading
                          ? t('config.loading_models')
                          : t('config.model_placeholder')
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {modelOptions.map((model) => (
                      <SelectItem key={model.id} value={model.id} dir="ltr">
                        {model.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {modelError ? (
                  <p id="model-error" role="alert" className="text-xs text-error">
                    {t('config.toast_model_required')}
                  </p>
                ) : (
                  <p className="text-xs text-foreground-tertiary">
                    {isImage ? t('config.image_model_hint') : t('config.model_hint')}
                  </p>
                )}
              </div>

              {/* Base images — image kind only */}
              {isImage && (
                <div className="space-y-2">
                  <Label>{t('config.base_images_label')}</Label>
                  <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                    {formData.base_images.map((img) => (
                      <div
                        key={img.upload_id}
                        className="relative group aspect-square overflow-hidden rounded-[10px] border border-border bg-background-secondary"
                      >
                        <img
                          src={img.thumb_url || img.url}
                          alt={img.name || ''}
                          className="h-full w-full object-cover"
                        />
                        <Button
                          type="button"
                          variant="destructive"
                          size="icon"
                          onClick={() => handleRemoveBaseImage(img.upload_id)}
                          aria-label={t('config.base_images_remove')}
                          className="absolute top-1 end-1 h-6 w-6 rounded-full opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}

                    {formData.base_images.length < MAX_BASE_IMAGES && (
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isUploadingImages}
                        className={cn(
                          'flex aspect-square flex-col items-center justify-center gap-1.5 rounded-[10px] border-2 border-dashed border-border text-foreground-tertiary transition-colors',
                          isUploadingImages
                            ? 'cursor-not-allowed opacity-60'
                            : 'hover:border-foreground-tertiary hover:text-foreground-secondary'
                        )}
                      >
                        {isUploadingImages ? (
                          <Loader2 className="h-5 w-5 animate-spin" />
                        ) : (
                          <Plus className="h-5 w-5" />
                        )}
                        <span className="text-xs">{t('config.base_images_add')}</span>
                      </button>
                    )}
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      handleBaseImageFiles(e.target.files)
                      e.target.value = ''
                    }}
                  />
                  <p className="text-xs text-foreground-tertiary">
                    {formData.base_images.length === 0
                      ? t('config.base_images_empty')
                      : t('config.base_images_hint', { max: MAX_BASE_IMAGES })}
                  </p>
                </div>
              )}

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="system-prompt">
                    {isImage ? t('config.instructions_label') : t('config.system_prompt_label')}
                  </Label>
                  <div className="flex items-center gap-1">
                    {revertPrompt !== null && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={handleRevertPrompt}
                        disabled={isEnhancing}
                        className="h-auto py-1 text-xs text-foreground-secondary"
                      >
                        <Undo2 className="h-3 w-3 me-1" />
                        {t('config.revert')}
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={handleEnhancePrompt}
                      disabled={isEnhancing || !formData.system_prompt.trim()}
                      className="h-auto py-1 text-xs"
                    >
                      {isEnhancing ? (
                        <>
                          <Loader2 className="h-3 w-3 animate-spin me-1" />
                          {t('config.enhancing')}
                        </>
                      ) : (
                        <>
                          <Wand2 className="h-3 w-3 me-1" />
                          {t('config.enhance')}
                        </>
                      )}
                    </Button>
                  </div>
                </div>
                <Textarea
                  id="system-prompt"
                  value={formData.system_prompt}
                  onChange={(e) => {
                    handleChange('system_prompt', e.target.value)
                    if (revertPrompt !== null) setRevertPrompt(null)
                  }}
                  placeholder={
                    isImage
                      ? t('config.instructions_placeholder')
                      : t('config.system_prompt_placeholder')
                  }
                  rows={6}
                  className="resize-none text-sm"
                />
                <p className="text-xs text-foreground-tertiary">
                  {isImage ? t('config.instructions_hint') : t('config.system_prompt_hint')}
                </p>
              </div>

              {/* Creativity — text kind only (image models don't use temperature) */}
              {!isImage && (
                <div className="space-y-2">
                  <Label htmlFor="creativity">{t('config.creativity_label')}</Label>
                  <Select value={creativity} onValueChange={handleCreativityChange}>
                    <SelectTrigger id="creativity">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CREATIVITY_LEVELS.map((level) => (
                        <SelectItem key={level.id} value={level.id}>
                          <div className="flex flex-col items-start">
                            <span>{t(`config.creativity_${level.id}`)}</span>
                            <span className="text-xs text-foreground-tertiary">
                              {t(`config.creativity_${level.id}_hint`)}
                            </span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-foreground-tertiary">{t('config.creativity_hint')}</p>
                </div>
              )}
            </section>

            {/* ─── Sharing ─── */}
            <section className="space-y-4">
              <SectionHeader>{t('config.section_sharing')}</SectionHeader>

              <div className="space-y-2">
                <Label>{t('config.visibility_label')}</Label>
                <div
                  role="radiogroup"
                  aria-label={t('config.visibility_label')}
                  className="grid gap-2 sm:grid-cols-2"
                >
                  {VISIBILITY_OPTIONS.map(({ id, Icon, title, hint }) => {
                    const selected = formData.visibility === id
                    const locked = isEditing && id === 'project' && config?.visibility !== 'project'
                    return (
                      <button
                        key={id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => handleChange('visibility', id)}
                        disabled={locked}
                        className={cn(
                          'flex items-start gap-3 rounded-[10px] border border-border bg-background-secondary px-3 py-3 text-sm text-start transition-colors',
                          selected
                            ? 'bg-accent/10 text-foreground ring-1 ring-inset ring-accent'
                            : 'text-foreground-secondary hover:border-foreground-tertiary',
                          locked && 'cursor-not-allowed opacity-50',
                        )}
                      >
                        <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="font-medium">{title}</div>
                          <div className="truncate text-xs text-foreground-tertiary">{hint}</div>
                        </div>
                      </button>
                    )
                  })}
                </div>
                {isEditing && projectId && config?.visibility !== 'project' && (
                  <p className="text-xs text-foreground-tertiary">
                    {t('config.visibility_lock_hint')}
                  </p>
                )}
              </div>
            </section>
          </div>
        </form>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t('config.cancel')}
          </Button>
          <Button type="submit" form="config-editor-form" disabled={saveMutation.isPending}>
            {saveMutation.isPending ? t('config.saving') : isEditing ? t('config.save_changes') : t('config.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
      {dlpModal}
    </Dialog>
  )
}

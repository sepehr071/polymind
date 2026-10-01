import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, X, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../../utils/cn'
import toast from 'react-hot-toast'

// OpenRouter image refs: png/jpeg/webp/gif only. HEIC is accepted in the
// picker then converted to JPEG in-browser before the data URI is built.
export const IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif,.heic,.heif'
const OPENROUTER_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp'])
const HEIC_EXTS = new Set(['heic', 'heif'])
const OPENROUTER_MIMES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
const HEIC_MIMES = new Set(['image/heic', 'image/heif'])
const MAX_IMAGE_BYTES = 10 * 1024 * 1024

function fileExt(file) {
  return String(file?.name || '').split('.').pop()?.toLowerCase() || ''
}

export function isHeicFile(file) {
  if (!file) return false
  const mime = (file.type || '').toLowerCase()
  return HEIC_MIMES.has(mime) || HEIC_EXTS.has(fileExt(file))
}

export function isImageFile(file) {
  if (!file) return false
  const mime = (file.type || '').toLowerCase()
  if (OPENROUTER_MIMES.has(mime) || HEIC_MIMES.has(mime)) return true
  if (mime.startsWith('image/')) return true
  const ext = fileExt(file)
  if (OPENROUTER_EXTS.has(ext) || HEIC_EXTS.has(ext)) return true
  // Clipboard blobs often have empty type and no filename.
  return !mime && !ext
}

function filenameForMime(mime) {
  if (mime === 'image/jpeg') return 'image.jpg'
  if (mime === 'image/png') return 'image.png'
  if (mime === 'image/webp') return 'image.webp'
  if (mime === 'image/gif') return 'image.gif'
  return 'image.png'
}

/** Clipboard `File`s often have empty `type`; the DataTransferItem still knows. */
export function filesFromClipboard(clipboardData) {
  if (!clipboardData) return []
  const out = []
  const seen = new Set()
  const push = (file) => {
    if (!file) return
    const key = `${file.size}:${file.name}:${file.type}`
    if (seen.has(key)) return
    seen.add(key)
    out.push(file)
  }
  for (const item of Array.from(clipboardData.items || [])) {
    if (item.kind !== 'file') continue
    const raw = item.getAsFile()
    if (!raw) continue
    const mime = (raw.type || item.type || '').toLowerCase()
    if (raw.type) push(raw)
    else push(new File([raw], raw.name || filenameForMime(mime), { type: mime }))
  }
  if (!out.length) {
    for (const f of Array.from(clipboardData.files || [])) push(f)
  }
  return out
}

async function sniffImageMime(file) {
  const buf = new Uint8Array(await file.slice(0, 12).arrayBuffer())
  if (buf.length >= 8 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
    return 'image/png'
  }
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) {
    return 'image/jpeg'
  }
  if (buf.length >= 6 && buf[0] === 0x47 && buf[1] === 0x49 && buf[2] === 0x46) {
    return 'image/gif'
  }
  if (
    buf.length >= 12
    && buf[0] === 0x52 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x46
    && buf[8] === 0x57 && buf[9] === 0x45 && buf[10] === 0x42 && buf[11] === 0x50
  ) {
    return 'image/webp'
  }
  return null
}

async function ensureOpenRouterImage(file) {
  if (isHeicFile(file)) return heicToJpegFile(file)
  const mime = (file.type || '').toLowerCase()
  if (OPENROUTER_MIMES.has(mime)) return file
  const sniffed = await sniffImageMime(file)
  if (sniffed) {
    const name = fileExt(file) ? file.name : filenameForMime(sniffed)
    return new File([file], name, { type: sniffed })
  }
  if (mime.startsWith('image/')) return heicToJpegFile(file)
  throw new Error('type')
}

async function heicToJpegFile(file) {
  let bitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    throw new Error('heic')
  }
  const canvas = document.createElement('canvas')
  canvas.width = bitmap.width
  canvas.height = bitmap.height
  const ctx = canvas.getContext('2d')
  ctx.drawImage(bitmap, 0, 0)
  bitmap.close()
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('heic'))), 'image/jpeg', 0.92)
  })
  const name = String(file.name || 'image.heic').replace(/\.hei[cf]$/i, '.jpg')
  return new File([blob], name, { type: 'image/jpeg' })
}

function convertToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

/** Shared by the [+] uploader and composer paste. Toasts via `t` (layout ns). */
export async function ingestImageFiles(files, { images, maxImages, t }) {
  const fileArray = Array.from(files || []).filter(Boolean)
  if (!fileArray.length) return { ok: false, images }

  if (images.length + fileArray.length > maxImages) {
    toast.error(t('imageUpload.errorCount', { max: maxImages }))
    return { ok: false, images }
  }

  const validFiles = []
  for (const file of fileArray) {
    if (!isImageFile(file)) {
      toast.error(t('imageUpload.errorType'))
      continue
    }
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error(t('imageUpload.errorSize'))
      continue
    }
    validFiles.push(file)
  }
  if (!validFiles.length) return { ok: false, images }

  try {
    const prepared = []
    for (const file of validFiles) {
      try {
        prepared.push(await ensureOpenRouterImage(file))
      } catch (err) {
        toast.error(err?.message === 'heic' ? t('imageUpload.errorHeic') : t('imageUpload.errorType'))
      }
    }
    if (!prepared.length) return { ok: false, images }

    const newImages = await Promise.all(prepared.map(async (file) => ({
      file,
      preview: URL.createObjectURL(file),
      base64: await convertToBase64(file),
    })))
    return { ok: true, images: [...images, ...newImages] }
  } catch (error) {
    toast.error(t('common:errors.generic'))
    console.error(error)
    return { ok: false, images }
  }
}

export default function ImageUploadPreview({ images = [], maxImages = 3, onChange, disabled = false, startIndex = 0, cap = null }) {
  const { t } = useTranslation('layout')
  // Slot numbering mirrors the wire order: leading slots (startIndex) are
  // consumed by the focused edit-base + assistant bases, so the first upload is
  // Image (startIndex+1). `cap` (the model's true input_references.max) flags
  // uploads that fall past the limit and won't be sent.
  const effectiveCap = cap ?? maxImages
  const [isDragging, setIsDragging] = useState(false)
  const [loading, setLoading] = useState(false)

  // `preview` blob URLs are minted once per file in handleFiles (never per
  // render), but the parent owns the `images` array, so we mirror the live URLs
  // in a ref to revoke whatever is still outstanding on unmount — without
  // revoking a URL the parent is still rendering across re-renders.
  const previewUrlsRef = useRef([])
  previewUrlsRef.current = images.map((img) => img.preview).filter(Boolean)

  useEffect(() => {
    return () => {
      previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [])

  const handleFiles = async (files) => {
    setLoading(true)
    try {
      const result = await ingestImageFiles(files, { images, maxImages, t })
      if (result.ok) onChange(result.images)
    } finally {
      setLoading(false)
    }
  }

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)

    if (disabled) return

    const files = e.dataTransfer.files
    if (files.length > 0) {
      handleFiles(files)
    }
  }, [disabled, images, maxImages])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    if (!disabled) {
      setIsDragging(true)
    }
  }, [disabled])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleFileSelect = (e) => {
    const files = e.target.files
    if (files.length > 0) {
      handleFiles(files)
    }
    e.target.value = ''
  }

  const removeImage = (index) => {
    const removed = images[index]
    if (removed?.preview) URL.revokeObjectURL(removed.preview)
    const newImages = images.filter((_, i) => i !== index)
    onChange(newImages)
  }

  return (
    <div className="space-y-3">
      {/* Upload Area */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={cn(
          'border-2 border-dashed rounded-lg p-6 text-center transition-colors',
          isDragging && !disabled ? 'border-primary bg-primary/5' : 'border-border',
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-primary/50'
        )}
      >
        <input
          type="file"
          id="image-upload"
          multiple
          accept={IMAGE_ACCEPT}
          onChange={handleFileSelect}
          disabled={disabled || loading || images.length >= maxImages}
          className="hidden"
        />
        <label
          htmlFor="image-upload"
          className={cn(
            'flex flex-col items-center gap-2',
            disabled || loading || images.length >= maxImages ? 'cursor-not-allowed' : 'cursor-pointer'
          )}
        >
          {loading ? (
            <Loader2 className="w-8 h-8 text-foreground-tertiary animate-spin" />
          ) : (
            <Upload className="w-8 h-8 text-foreground-tertiary" />
          )}
          <div className="text-sm">
            {loading ? (
              <span className="text-foreground-secondary">{t('imageUpload.processingImages')}</span>
            ) : images.length >= maxImages ? (
              <span className="text-foreground-tertiary">{t('imageUpload.maximumImagesReached')}</span>
            ) : (
              <>
                <span className="text-foreground font-medium">{t('imageUpload.clickToUpload')}</span>
                <span className="text-foreground-secondary"> {t('imageUpload.orDragAndDrop')}</span>
              </>
            )}
          </div>
          <p className="text-xs text-foreground-tertiary">
            {t('imageUpload.imageCount', { current: images.length, max: maxImages })}
          </p>
        </label>
      </div>

      {/* Image Previews */}
      {images.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
          {images.map((image, index) => {
            const slot = startIndex + index + 1
            const overCap = effectiveCap > 0 && slot > effectiveCap
            return (
            <div
              key={index}
              className={cn(
                'relative group aspect-square bg-background-secondary rounded-lg overflow-hidden border border-border',
                overCap && 'opacity-55 ring-1 ring-error/40',
              )}
            >
              {/* Render the self-contained base64 data URI, NOT the blob
                  `preview` URL: this uploader lives inside the [+] Radix Popover
                  which unmounts on close, and the unmount cleanup revokes every
                  blob URL — but `images` is page state that outlives it, so on
                  reopen the revoked blob URLs render broken. base64 never dies. */}
              <img
                src={image.base64 || image.preview}
                alt={t('imageUpload.slotBadge', { n: slot })}
                className="w-full h-full object-cover"
              />
              {/* Slot number — the exact "Image N" the model receives, so the
                  user can address it in the prompt. Muted + struck when it
                  exceeds the model cap (dropped before sending). LTR token. */}
              <span
                dir="ltr"
                title={overCap ? t('imageUpload.slotOverCap') : undefined}
                className={cn(
                  'absolute top-1 start-1 inline-flex items-center px-1.5 h-4 rounded-full text-[10px] font-semibold pointer-events-none',
                  overCap ? 'bg-foreground-tertiary/80 text-white line-through' : 'bg-black/55 text-white',
                )}
              >
                {t('imageUpload.slotBadge', { n: slot })}
              </span>
              <button
                onClick={() => removeImage(index)}
                disabled={disabled}
                aria-label={t('imageUpload.removeImage', { index: slot })}
                className={cn(
                  'absolute top-1 end-1 p-1 bg-error text-white rounded-full',
                  'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 transition-opacity',
                  'hover:bg-error/90 disabled:opacity-50',
                  disabled && 'cursor-not-allowed'
                )}
              >
                <X className="w-4 h-4" />
              </button>
              <div className="absolute bottom-0 start-0 end-0 p-1 bg-black/50 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                <p className="text-xs text-white truncate">{image.file.name}</p>
              </div>
            </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

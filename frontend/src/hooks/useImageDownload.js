import { createElement, useCallback, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { imageService } from '@/services/imageService'
import toast from 'react-hot-toast'

/**
 * Shared image-download helper. The list/grid payloads omit the heavy full-res
 * base64, so this resolves the full data-URI (preferring an already-loaded one,
 * else fetching the full payload by id — cached under ['image', id] so a later
 * detail-open/zoom reuses it) and triggers a browser download via an anchor.
 *
 * Extracted from the duplicated logic in ImageStudioPage + ImageGrid so every
 * surface downloads the same way and shares one cache entry.
 *
 * @returns {{
 *   download: (image: object, loadedData?: string) => Promise<void>,
 *   isDownloading: boolean,
 * }}
 *   `download(image, loadedData?)` — `image` carries at least an id
 *   (`id` or `_id`) and optionally `image_data` / `prompt`; pass `loadedData`
 *   (a `data:` URI the caller already has) to skip the fetch.
 *   Re-entry while a download is in flight is a no-op. Success/failure toast
 *   from here so every surface (modal, canvas, grid) shares one UX.
 */
export function useImageDownload() {
  const queryClient = useQueryClient()
  const { t } = useTranslation('dashboard')
  const [isDownloading, setIsDownloading] = useState(false)
  const busyRef = useRef(false)
  const lastRef = useRef(null)
  const downloadRef = useRef(null)

  const triggerDownload = useCallback((imageData, promptText) => {
    const link = document.createElement('a')
    link.href = imageData
    link.download = `generated-${promptText?.slice(0, 30) || 'image'}.png`
    link.click()
  }, [])

  const download = useCallback(async (image, loadedData) => {
    if (busyRef.current) return
    lastRef.current = { image, loadedData }
    busyRef.current = true
    setIsDownloading(true)
    try {
      const id = image?.id ?? image?._id
      let data = loadedData || image?.image_data
      if (!data && id != null) {
        // Full payload by id (cached forever — immutable per image).
        const full = await queryClient.fetchQuery({
          queryKey: ['image', id],
          queryFn: () => imageService.getImage(id),
          staleTime: Infinity,
        })
        data = full?.image_data
      }
      if (!data) throw new Error('no payload')
      triggerDownload(data, image?.prompt)
      toast.success(t('imageHistory.downloadStarted'))
    } catch {
      toast.error((toastObj) => createElement(
        'span',
        { className: 'inline-flex items-center gap-2 flex-wrap' },
        createElement('span', null, t('imageStudio.failedToDownload')),
        createElement(
          'button',
          {
            type: 'button',
            className: 'underline text-accent hover:text-accent/80',
            onClick: () => {
              toast.dismiss(toastObj.id)
              const last = lastRef.current
              if (last) void downloadRef.current?.(last.image, last.loadedData)
            },
          },
          t('imageHistory.tryAgain'),
        ),
      ))
    } finally {
      busyRef.current = false
      setIsDownloading(false)
    }
  }, [queryClient, triggerDownload, t])

  downloadRef.current = download

  return { download, isDownloading }
}

export default useImageDownload

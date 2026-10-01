import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { imageService } from '../../services/imageService'
import { cn } from '../../utils/cn'

/**
 * Renders a grid <img> for a generated image, cheapest-source-first:
 *
 *   1. `fallbackData`  — a full `image_data` already on the row (fresh
 *                        generation / preloaded). Rendered immediately.
 *   2. `thumb`         — a small downscaled WebP `data:` URI (~5-15KB) shipped
 *                        in the payload-less history list. Rendered instantly,
 *                        no fetch, no IntersectionObserver.
 *   3. lazy full-by-id — only when neither of the above exists (e.g. an
 *                        un-backfilled row with `thumb: null`): the full base64
 *                        is fetched by id once the tile scrolls into view.
 *
 * The thumbnail is preview-only. `onLoaded` is invoked ONLY with the full-res
 * payload (cases 1 & 3) so the parent's download/zoom path uses full quality;
 * a thumb-only tile leaves it unset and the parent fetches the full image by id
 * on demand.
 *
 * - `id`           image id (used as the per-image query key for the full fetch)
 * - `fallbackData` optional full `image_data` already present on the row.
 * - `thumb`        optional small WebP `data:` URI from the list payload.
 * - `onLoaded(data)` invoked with the full `image_data` once available.
 *
 * Any extra props (className, alt, loading, decoding, onClick…) pass to <img>.
 */
export default function LazyImageTile({
  id,
  fallbackData,
  thumb,
  onLoaded,
  className,
  alt,
  ...imgProps
}) {
  const ref = useRef(null)
  const [visible, setVisible] = useState(false)

  // Only lazy-fetch the full payload by id when we have NOTHING to show yet
  // (no full payload, no thumb). With a thumb present the grid renders instantly
  // and the full image is fetched elsewhere on demand (download/zoom).
  const needsLazyFull = !fallbackData && !thumb

  useEffect(() => {
    if (visible || !needsLazyFull) return
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: '200px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [visible, needsLazyFull])

  const { data: fetched } = useQuery({
    queryKey: ['image', id],
    queryFn: () => imageService.getImage(id),
    enabled: visible && needsLazyFull,
    staleTime: Infinity,
  })

  const fullData = fallbackData || fetched?.image_data
  // What we actually paint: full > thumb. Thumb is preview-only.
  const displaySrc = fullData || thumb

  useEffect(() => {
    // Surface ONLY the full-res payload to the parent (never the thumb), so the
    // download/zoom path stays full quality.
    if (fullData) onLoaded?.(fullData)
  }, [fullData, onLoaded])

  if (!displaySrc) {
    return (
      <div
        ref={ref}
        className={cn('animate-pulse bg-background-tertiary', className)}
      />
    )
  }

  return (
    <img
      ref={ref}
      src={displaySrc}
      alt={alt}
      className={className}
      {...imgProps}
    />
  )
}

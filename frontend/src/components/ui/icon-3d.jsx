import { cn } from '@/lib/utils'

/**
 * Self-hosted 3D raster icon.
 *
 * Assets live in `frontend/public/icons/3d/*.png` and are served root-absolute
 * (e.g. `/icons/3d/book.png`), exactly like `/favicon.svg` — no CDN, no SDK,
 * no runtime fetch to a foreign host. This is the air-gap-safe path (prod has
 * zero foreign internet egress): the files are copied verbatim by Vite and
 * never enter the Rollup chunk graph.
 *
 * Decorative by default (`alt=''` → `aria-hidden`), because these icons sit
 * beside a visible text title. Pass a real `alt` only when the icon is the
 * sole label.
 *
 * @param {object} props
 * @param {string} props.src Root-absolute asset path, e.g. `/icons/3d/book.png`.
 * @param {number} [props.size=48] Rendered square size in px.
 * @param {string} [props.alt='']
 * @param {string} [props.className]
 * @param {React.CSSProperties} [props.style]
 */
export default function Icon3D({ src, size = 48, alt = '', className, style }) {
  return (
    <img
      src={src}
      width={size}
      height={size}
      alt={alt}
      aria-hidden={alt ? undefined : true}
      loading="lazy"
      decoding="async"
      draggable={false}
      className={cn('select-none', className)}
      style={{ objectFit: 'contain', ...style }}
    />
  )
}

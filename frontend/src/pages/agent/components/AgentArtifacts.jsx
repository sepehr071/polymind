import { API_BASE_URL } from '@/services/apiBase'
import { cn } from '@/lib/utils'

function originBase() {
  return (API_BASE_URL || '').replace(/\/api\/?$/, '')
}

/**
 * Durable agent image cards from metadata.agent_artifacts.
 *
 * Thumb = data URI (inline). Full open = /api/image-gen/{id}/file (raw image/*).
 * Never use JSON GET /api/image-gen/{id} as img src or <a href> — that opens
 * a base64 JSON dump in a new tab.
 */
function thumbSrc(a) {
  const raw = a?.thumb_b64 || a?.thumb
  if (!raw) return null
  const s = String(raw)
  if (s.startsWith('data:')) return s
  if (s.startsWith('http://') || s.startsWith('https://') || s.startsWith('/')) return s
  return `data:image/webp;base64,${s}`
}

function mediaHref(a, base) {
  if (a?.id) {
    return `${base}/api/image-gen/${a.id}/file`
  }
  const u = a?.url
  if (!u) return undefined
  // Normalize legacy /api/image-gen/{id} → /file
  const m = String(u).match(/\/api\/image-gen\/([^/?#]+)\/?$/)
  if (m && !String(u).includes('/file')) {
    return `${base}/api/image-gen/${m[1]}/file`
  }
  if (u.startsWith('http://') || u.startsWith('https://')) return u
  return `${base}${u.startsWith('/') ? u : `/${u}`}`
}

export default function AgentArtifacts({ artifacts = [], className }) {
  const list = Array.isArray(artifacts) ? artifacts : []
  const images = list.filter(
    (a) => a?.type === 'image' && (a.thumb_b64 || a.thumb || a.url || a.id),
  )
  if (!images.length) return null

  const base = originBase()

  return (
    <div className={cn('mt-3 flex flex-wrap gap-2', className)}>
      {images.map((a, i) => {
        const href = mediaHref(a, base)
        const src = thumbSrc(a) // never fall back to JSON API URL as img src

        const inner = src ? (
          <img
            src={src}
            alt={a.prompt || ''}
            className="size-full object-contain"
            loading="lazy"
          />
        ) : (
          <div className="flex size-full items-center justify-center text-[10px] text-muted-foreground">
            img
          </div>
        )

        const cls =
          'block size-20 overflow-hidden rounded-xl border border-border/50 bg-bg-2/40 transition-opacity hover:opacity-90'

        return href ? (
          <a key={a.id || i} href={href} target="_blank" rel="noreferrer" className={cls}>
            {inner}
          </a>
        ) : (
          <div key={a.id || i} className={cls}>
            {inner}
          </div>
        )
      })}
    </div>
  )
}

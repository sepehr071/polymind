import { useTranslation } from 'react-i18next'
import { Download, FileArchive, FileSpreadsheet, FileText, FileJson, File as FileIcon } from 'lucide-react'
import { IconTile } from './icon-tile'
import { fmtNumber } from '../../utils/persianLocale'
import { API_BASE_URL } from '../../services/apiBase'
import { cn } from '@/lib/utils'

/**
 * FileDownloadCard — a small, presentational download card for a single file
 * artifact produced by the backend ({ url, name, ext, size }).
 *
 * Shared primitive (lives in components/ui): no feature-specific imports, labels
 * default to the `common` namespace and can be overridden per caller.
 *
 * The href is resolved EXACTLY like the chat FileArtifact: `url` is normally a
 * root-relative '/api/uploads/<id>'. On a split-domain deploy
 * (VITE_API_BASE_URL = api.<host>/api) it must resolve to the API origin, not
 * the FE origin, so we strip the trailing '/api' off API_BASE_URL to get the
 * API origin and prefix the path. Same-origin (API_BASE_URL = '/api') → origin
 * '' → unchanged. An already-absolute http(s) URL passes through untouched. The
 * cross-origin download relies on the server's Content-Disposition: attachment
 * header, so a plain <a href download> works — no fetch/Bearer needed.
 *
 * @param {Object} props
 * @param {{ url: string, name?: string, ext?: string, size?: number }} props.artifact
 * @param {string} [props.downloadLabel]  overrides the button text
 * @param {string} [props.tone='emerald'] IconTile tone for the file glyph
 * @param {string} [props.className]
 */

// Human-readable size with localized digits (Latin/Persian per user pref).
// Mirrors the chat FileArtifact helper so both surfaces format sizes identically.
function humanFileSize(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n <= 0) return null
  if (n < 1024) return `${fmtNumber(n)} B`
  if (n < 1024 * 1024) return `${fmtNumber(Math.round((n / 1024) * 10) / 10)} KB`
  return `${fmtNumber(Math.round((n / (1024 * 1024)) * 10) / 10)} MB`
}

function iconForExt(ext) {
  const e = String(ext || '').toLowerCase()
  if (e === 'zip' || e === 'rar' || e === '7z' || e === 'tar' || e === 'gz') return FileArchive
  if (e === 'xlsx' || e === 'xls' || e === 'csv' || e === 'xlsm') return FileSpreadsheet
  if (e === 'json' || e === 'jsonl') return FileJson
  if (e === 'pdf' || e === 'txt' || e === 'md' || e === 'doc' || e === 'docx') return FileText
  return FileIcon
}

export default function FileDownloadCard({ artifact, downloadLabel, tone = 'emerald', className }) {
  const { t } = useTranslation('common')
  if (!artifact?.url) return null

  // Resolve a root-relative API path against the API origin (see header note).
  const apiOrigin = API_BASE_URL.replace(/\/api$/, '')
  const href = /^https?:\/\//i.test(artifact.url) ? artifact.url : `${apiOrigin}${artifact.url}`

  const Icon = iconForExt(artifact.ext)
  const size = humanFileSize(artifact.size)
  const label = downloadLabel ?? t('actions.download')

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-xl border border-border bg-background-secondary/30 p-3',
        className,
      )}
    >
      <IconTile icon={Icon} tone={tone} size="md" />
      <div className="min-w-0 flex-1">
        {/* dir=auto: filenames are often Persian — a hard ltr would glue the
            extension to the wrong visual side. */}
        {artifact.name && (
          <p className="truncate text-sm font-medium text-foreground" dir="auto">
            {artifact.name}
          </p>
        )}
        {size && <p className="mt-0.5 text-xs text-foreground-tertiary" dir="ltr">{size}</p>}
      </div>
      <a
        href={href}
        download
        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-background-secondary px-3 py-1.5 text-xs font-medium text-foreground-secondary transition-colors hover:bg-background-tertiary hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        {label}
      </a>
    </div>
  )
}

export { FileDownloadCard }

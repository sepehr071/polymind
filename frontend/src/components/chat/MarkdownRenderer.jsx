import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import { Highlight, themes } from 'prism-react-renderer'
import { Copy, Check, Download, ExternalLink, ZoomIn, Play } from 'lucide-react'
import { Suspense, useState, memo, useCallback, useMemo, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { containsRTL } from '../../utils/rtl'
import lazyWithRetry from '../../utils/lazyWithRetry'
import { useTheme } from '../../context/ThemeContext'
import { imageService } from '../../services/imageService'
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '../ui/dialog'

// ---------------------------------------------------------------------------
// HTML sanitization schema (SECURITY-CRITICAL).
//
// Assistant text is model-controlled and rendered through `rehype-raw`, which
// turns raw HTML in the markdown into real DOM. Without sanitization a model
// can emit `<iframe srcdoc="<script>…">` / `<script>` and run arbitrary JS in
// the app origin (stealing the JWT + refresh token from localStorage). Every
// ReactMarkdown instance runs `rehypeSanitize` with THIS schema AFTER
// `rehypeRaw` to strip that primitive.
//
// We start from the GitHub-style `defaultSchema` (which already omits
// `iframe`, `script`, `object`, `embed`, `style`, `link`, `meta`, `base`,
// `form`, `svg`/`use`, the `srcdoc` attribute and every `on*` handler — none
// of which we re-add) and EXTEND it just enough to keep KaTeX output intact:
//   - allow `className`/`style`/`aria-hidden` on the wrapper elements KaTeX
//     emits (`span`, `div`),
//   - allow the MathML element set KaTeX renders into,
//   - allow MathML/structural attributes on those elements.
// This schema is intentionally duplicated (kept in sync) in MarkdownMath.jsx;
// a shared module isn't used to keep this fix scoped to these two files.
const KATEX_MATHML_TAGS = [
  'math', 'semantics', 'mrow', 'mi', 'mo', 'mn', 'ms', 'mtext', 'mspace',
  'msup', 'msub', 'msubsup', 'mfrac', 'mroot', 'msqrt', 'mover', 'munder',
  'munderover', 'mmultiscripts', 'mprescripts', 'mtable', 'mtr', 'mtd',
  'mpadded', 'mphantom', 'menclose', 'mstyle', 'merror', 'mglyph',
  'annotation', 'annotation-xml',
]

const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames || []), ...KATEX_MATHML_TAGS],
  attributes: {
    ...defaultSchema.attributes,
    // KaTeX HTML output leans entirely on class names + inline style for
    // glyph positioning, and marks its duplicate (visual) layer aria-hidden.
    span: [
      ...(defaultSchema.attributes?.span || []),
      'className', 'style', 'ariaHidden',
    ],
    div: [
      ...(defaultSchema.attributes?.div || []),
      'className', 'style', 'ariaHidden',
    ],
    // MathML attributes used by KaTeX's MathML layer.
    math: ['xmlns', 'display'],
    annotation: ['encoding'],
    'annotation-xml': ['encoding'],
    mo: ['fence', 'stretchy', 'separator', 'lspace', 'rspace', 'maxsize', 'minsize'],
    mover: ['accent'],
    munder: ['accentunder'],
    munderover: ['accent', 'accentunder'],
    mspace: ['width', 'height', 'depth'],
    mpadded: ['width', 'height', 'depth', 'lspace', 'voffset'],
    mstyle: ['scriptlevel', 'displaystyle', 'mathcolor', 'mathbackground'],
    mtd: ['columnalign', 'rowspan', 'columnspan'],
    mtr: ['rowalign', 'columnalign'],
    mtable: ['columnalign', 'rowalign', 'rowspacing', 'columnspacing'],
    // Generic MathML token/structural attributes allowed on every element.
    '*': [
      ...(defaultSchema.attributes?.['*'] || []),
      'mathvariant', 'displaystyle', 'scriptlevel',
    ],
  },
}

// KaTeX (rehype-katex JS ~270KB + CSS + ~20 woff2 fonts) is split into an
// on-demand chunk: it only loads for messages that actually contain math.
// The plain /chat render path below never touches it.
const MarkdownMath = lazyWithRetry(() => import('./MarkdownMath'))

// Detect TeX/LaTeX math so we only pull in the katex pipeline when it's needed.
// Single-dollar inline math is now ENABLED in MarkdownMath, so this gate must
// also keep plain prose-currency ("$20 and $30") OFF the math path — otherwise
// such a pair would be mis-parsed as math. An inline $...$ therefore only counts
// as math when its inner content actually looks mathematical:
//   - a LaTeX command (\times), sub/superscript, braces, or a relational/
//     arithmetic operator (= < > + - * /), OR
//   - a single whitespace-free token ($20$, $x$, $a1$).
// Block/display math always counts: $$ … $$, \[ … \], \( … \), \begin{…}.
const BLOCK_MATH = /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\\begin\{/
const INLINE_MATH = /\$([^$\n]+?)\$/g
const MATHY_INNER = /[\\^_{}=<>+*/-]/

function looksMathy(inner) {
  // latex / structure / relation / arithmetic …
  if (MATHY_INNER.test(inner)) return true
  // … or a single token with no internal whitespace ($20$, $x$).
  return !/\s/.test(inner.trim())
}
function hasMath(content) {
  if (typeof content !== 'string') return false
  if (BLOCK_MATH.test(content)) return true
  INLINE_MATH.lastIndex = 0
  let m
  while ((m = INLINE_MATH.exec(content)) !== null) {
    if (looksMathy(m[1])) return true
  }
  return false
}

// ---------------------------------------------------------------------------
// Streaming block split (PERF).
//
// During SSE streaming `StreamingTurn` re-renders ~once/frame with the full
// accumulated text. Running the whole react-markdown + Prism pipeline over ALL
// content each frame is O(n²) over reply length — phones choke on long /
// code-heavy replies. We split the growing string into:
//   - a STABLE PREFIX (everything up to the last "safe boundary") that only
//     grows when a new block completes, rendered through the full pipeline ONCE
//     per completed block (memoised on the prefix string), and
//   - a short TAIL (the in-progress block) rendered cheaply each frame.
//
// Safe boundary = the last `\n\n` that sits OUTSIDE an unclosed code fence.
// Fence state is tracked by counting ``` markers up to a candidate boundary:
// an even count = balanced (outside a fence), odd = inside an open fence. We
// only accept a `\n\n` boundary whose prefix has an EVEN fence count, so a
// half-streamed code block never gets split mid-fence into the stable prefix.
const FENCE_RE = /```/g

function fenceCountUpTo(str, end) {
  FENCE_RE.lastIndex = 0
  let count = 0
  let m
  while ((m = FENCE_RE.exec(str)) !== null) {
    if (m.index >= end) break
    count++
  }
  return count
}

// Returns { prefix, tail, tailInFence }. `prefix` ends on a balanced `\n\n`
// boundary; `tail` is the remaining in-progress text; `tailInFence` is true
// when the tail begins inside an unclosed ``` fence.
function splitStreamingContent(content) {
  if (typeof content !== 'string' || content.length === 0) {
    return { prefix: '', tail: content || '', tailInFence: false }
  }
  // Walk paragraph breaks from the end; accept the last one that is outside a
  // fence (even ``` count before it). `\n\n` may appear as part of a longer run
  // of newlines — we split right after the break so the tail keeps leading
  // newlines stripped naturally by markdown.
  let searchFrom = content.length
  while (searchFrom > 0) {
    const brk = content.lastIndexOf('\n\n', searchFrom - 1)
    if (brk < 0) break
    const boundary = brk + 2 // include the blank line in the prefix
    if (fenceCountUpTo(content, boundary) % 2 === 0) {
      return {
        prefix: content.slice(0, boundary),
        tail: content.slice(boundary),
        tailInFence: false,
      }
    }
    searchFrom = brk
  }
  // No balanced boundary found → everything is the tail (single in-progress
  // block). The tail is in a fence when the total ``` count so far is odd.
  return {
    prefix: '',
    tail: content,
    tailInFence: fenceCountUpTo(content, content.length) % 2 === 1,
  }
}

// Build the shared react-markdown component map (IDENTICAL for plain + math
// paths so a message renders byte-for-byte the same regardless of pipeline).
function useMarkdownComponents(onRunCode) {
  const CodeBlockWithRun = useCallback((props) => (
    <CodeBlock {...props} onRunCode={onRunCode} />
  ), [onRunCode])

  return useMemo(() => ({
    code: CodeBlockWithRun,
    pre: ({ children }) => <>{children}</>,
    p: withAutoDir('p'),
    h1: withAutoDir('h1'),
    h2: withAutoDir('h2'),
    h3: withAutoDir('h3'),
    h4: withAutoDir('h4'),
    h5: withAutoDir('h5'),
    h6: withAutoDir('h6'),
    li: withAutoDir('li'),
    blockquote: withAutoDir('blockquote'),
    td: withAutoDir('td'),
    th: withAutoDir('th'),
    a: ({ href, children }) => {
      // Bare-URL link text would visually flip its segments inside an RTL
      // paragraph (e.g. "example.com/path" reorders), so force LTR when the
      // visible text is itself a URL. Descriptive link text keeps content dir.
      const childText = typeof children === 'string' ? children : ''
      const looksLikeUrl = /^\s*(https?:\/\/|www\.)\S+\s*$/i.test(childText)
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:underline"
          {...(looksLikeUrl ? { dir: 'ltr' } : {})}
        >
          {children}
        </a>
      )
    },
    table: TableBlock,
    img: ImageRenderer,
  }), [CodeBlockWithRun])
}

// Core pipeline render for a single chunk of markdown. Pulls in the katex
// chunk only when the chunk actually contains math. `components` is passed in
// so the stable-prefix memo and the live tail share one identity.
function MarkdownPipeline({ content, components }) {
  const containsMath = useMemo(() => hasMath(content), [content])
  if (containsMath) {
    return (
      <Suspense
        fallback={
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
            components={components}
          >
            {content}
          </ReactMarkdown>
        }
      >
        <MarkdownMath content={content} components={components} />
      </Suspense>
    )
  }
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
      components={components}
    >
      {content}
    </ReactMarkdown>
  )
}

// Stable-prefix renderer for the streaming path. Memoised on the prefix string
// (and the components identity) so it only re-runs the full pipeline — Prism
// included — when a NEW block completes and migrates into the prefix, NOT on
// every streamed frame. `content` here always ends on a balanced fence
// boundary, so it never holds a half-open code fence.
const StableMarkdown = memo(
  function StableMarkdown({ content, components }) {
    return <MarkdownPipeline content={content} components={components} />
  },
  (prev, next) =>
    prev.content === next.content && prev.components === next.components
)

const MarkdownRenderer = memo(function MarkdownRenderer({ content, onRunCode, streaming = false }) {
  const components = useMarkdownComponents(onRunCode)

  if (streaming) {
    return <StreamingMarkdown content={content} components={components} />
  }

  // Non-streaming path — byte-identical to the original behavior: detect RTL
  // direction + math over the full content, render through the single pipeline.
  return <StaticMarkdown content={content} components={components} />
})

export default MarkdownRenderer

// Block-level dir=auto: first strong character of THAT block wins, so a
// Persian heading and an English paragraph in one reply don't share a single
// wrapper direction (the old getTextDirection(whole) path).
function withAutoDir(Tag) {
  return function AutoDir({ node, children, ...props }) {
    return <Tag dir="auto" {...props}>{children}</Tag>
  }
}

// Non-streaming render. Font switches when any RTL script is present; direction
// is per-block via withAutoDir, not a single wrapper dir.
function StaticMarkdown({ content, components }) {
  const persian = useMemo(() => containsRTL(content), [content])
  return (
    <div className={persian ? 'font-persian' : ''}>
      <MarkdownPipeline content={content} components={components} />
    </div>
  )
}

// Streaming render: stable prefix (memoised, full pipeline) + cheap live tail.
function StreamingMarkdown({ content, components }) {
  const { prefix, tail, tailInFence } = useMemo(
    () => splitStreamingContent(content),
    [content]
  )

  const persian = useMemo(() => containsRTL(content), [content])

  return (
    <div className={persian ? 'font-persian' : ''}>
      {prefix && <StableMarkdown content={prefix} components={components} />}
      {tail && (
        tailInFence ? (
          // In-progress code fence: render as a plain mono <pre> (NO Prism) so
          // we don't re-tokenize the whole growing block each frame. Mirrors
          // CodeBlock's non-highlighted shell closely enough to avoid a jarring
          // swap; when the fence closes the block migrates into the stable
          // prefix and gets full Prism treatment ONCE. Text-only content here
          // is React-escaped — no raw HTML path, so sanitization is unaffected.
          <StreamingFenceTail content={tail} />
        ) : (
          // Open prose block: short, cheap to run through the full pipeline
          // each frame. Math on the tail renders only after it stabilizes into
          // the prefix (per FIX 2 — hasMath here is on the short tail only).
          <MarkdownPipeline content={tail} components={components} />
        )
      )}
    </div>
  )
}

// Plain, un-highlighted rendering of an in-progress code fence. Strips the
// opening ```lang line for display and shows the body in a mono <pre> matching
// CodeBlock's container chrome (border + badge + maxHeight cap) so the swap to
// the Prism-highlighted block on fence close isn't jarring.
const StreamingFenceTail = memo(function StreamingFenceTail({ content }) {
  // content starts with the opening fence: ```lang\n<body…>. Peel the fence
  // line off for the language badge + body. No closing fence yet (by def).
  const nl = content.indexOf('\n')
  const fenceLine = nl >= 0 ? content.slice(0, nl) : content
  const body = nl >= 0 ? content.slice(nl + 1) : ''
  const language = fenceLine.replace(/^```/, '').trim() || 'code'

  return (
    <div className="group my-4 rounded-lg overflow-hidden border border-border">
      <div className="flex items-center justify-between px-4 py-2 bg-background-tertiary border-b border-border">
        <span className="text-xs text-foreground-secondary font-mono">
          {language}
        </span>
      </div>
      <pre
        dir="ltr"
        className="bg-background-tertiary text-foreground"
        style={{
          margin: 0,
          padding: '1rem',
          overflow: 'auto',
          maxHeight: '55vh',
          fontSize: '0.875rem',
          lineHeight: '1.5',
          textAlign: 'left',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          whiteSpace: 'pre',
        }}
      >
        {body}
      </pre>
    </div>
  )
})

/** Match /api/image-gen/{uuid} or /api/image-gen/{uuid}/file (absolute or relative). */
function parseImageGenUrl(src) {
  if (!src || typeof src !== 'string') return null
  const m = src.match(/\/api\/image-gen\/([0-9a-fA-F-]{36})(?:\/(file|preview))?\/?(?:[?#].*)?$/)
  if (!m) return null
  return { id: m[1], kind: m[2] || 'json' }
}

const ImageRenderer = memo(function ImageRenderer({ src, alt }) {
  const { t } = useTranslation('chat')
  const [isZoomed, setIsZoomed] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [hasError, setHasError] = useState(false)
  // Resolved display URL: data URI from Studio JSON API, or /file path, or raw src.
  const [displaySrc, setDisplaySrc] = useState(null)

  useEffect(() => {
    setIsLoading(true)
    setHasError(false)
    setDisplaySrc(null)

    const parsed = parseImageGenUrl(src)
    if (!parsed) {
      // Normal remote / data URI — use as-is.
      setDisplaySrc(src)
      return
    }

    // Prefer raw /file (cookie-auth same-origin <img>). Rewrite legacy JSON URL.
    if (parsed.kind === 'file') {
      setDisplaySrc(src.includes('/file') ? src : `/api/image-gen/${parsed.id}/file`)
      return
    }

    // Legacy markdown ![alt](/api/image-gen/{id}) → binary path first.
    // Fallback: axios getImage → data URI if /file fails in onError.
    setDisplaySrc(`/api/image-gen/${parsed.id}/file`)
  }, [src])

  const handleImgError = useCallback(async () => {
    const parsed = parseImageGenUrl(src) || parseImageGenUrl(displaySrc)
    // One retry via authenticated JSON → data URI (covers auth edge cases).
    if (parsed?.id && displaySrc && !displaySrc.startsWith('data:')) {
      try {
        const image = await imageService.getImage(parsed.id)
        const data = image?.image_data || image?.b64_payload || image?.thumb
        if (data) {
          setDisplaySrc(data.startsWith('data:') ? data : `data:image/png;base64,${data}`)
          setIsLoading(true)
          setHasError(false)
          return
        }
      } catch {
        /* fall through */
      }
    }
    setIsLoading(false)
    setHasError(true)
  }, [src, displaySrc])

  const handleDownload = async () => {
    try {
      const url = displaySrc || src
      const response = await fetch(url, { credentials: 'include' })
      const blob = await response.blob()
      const objectUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = alt || 'image'
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(objectUrl)
      document.body.removeChild(a)
      toast.success(t('markdown.imageDownloaded'))
    } catch (err) {
      toast.error(t('markdown.imageDownloadFailed'))
    }
  }

  const handleOpenNew = () => {
    const url = displaySrc || src
    // Prefer /file for image-gen ids so new tab shows pixels not JSON.
    const parsed = parseImageGenUrl(url) || parseImageGenUrl(src)
    if (parsed?.id && !String(url).startsWith('data:')) {
      window.open(`/api/image-gen/${parsed.id}/file`, '_blank', 'noopener,noreferrer')
      return
    }
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  if (hasError) {
    return (
      <div className="my-4 p-4 bg-background-tertiary rounded-lg text-foreground-secondary text-sm">
        {t('markdown.imageLoadFailed')}
      </div>
    )
  }

  const paintSrc = displaySrc || src

  return (
    <>
      {/* Cap in-chat size; click / zoom still opens full res. */}
      <div className="relative my-3 group inline-block max-w-[min(100%,20rem)]">
        {isLoading && (
          <div className="absolute inset-0 flex min-h-[8rem] min-w-[8rem] items-center justify-center bg-background-tertiary rounded-lg">
            <div className="h-8 w-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {paintSrc && (
          <img
            src={paintSrc}
            alt={alt}
            className="max-h-64 max-w-full rounded-lg object-contain cursor-zoom-in transition-opacity"
            style={{ opacity: isLoading ? 0 : 1 }}
            loading="lazy"
            onLoad={() => setIsLoading(false)}
            onError={handleImgError}
            onClick={() => setIsZoomed(true)}
          />
        )}

        {/* Action buttons overlay — visible on hover OR keyboard focus */}
        <div className="absolute top-2 end-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-within:opacity-100 transition-opacity flex gap-1">
          <button
            type="button"
            onClick={handleDownload}
            className="p-1.5 rounded-lg bg-black/50 text-white hover:bg-black/70 focus-visible:opacity-100"
            title={t('markdown.download')}
            aria-label={t('markdown.download')}
          >
            <Download className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={handleOpenNew}
            className="p-1.5 rounded-lg bg-black/50 text-white hover:bg-black/70"
            title={t('markdown.openInNewTab')}
            aria-label={t('markdown.openInNewTab')}
          >
            <ExternalLink className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setIsZoomed(true)}
            className="p-1.5 rounded-lg bg-black/50 text-white hover:bg-black/70"
            title={t('markdown.zoom')}
            aria-label={t('markdown.zoom')}
          >
            <ZoomIn className="h-4 w-4" />
          </button>
        </div>

        {/* Alt text */}
        {alt && (
          <div className="absolute bottom-0 inset-x-0 px-3 py-1.5 text-xs text-white bg-black/50 rounded-b-lg opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity truncate">
            {alt}
          </div>
        )}
      </div>

      {/* Zoom dialog — real modal (focus trap, Escape, aria-modal) */}
      <Dialog open={isZoomed && !!paintSrc} onOpenChange={(o) => { if (!o) setIsZoomed(false) }}>
        <DialogContent
          className="max-w-[min(96vw,56rem)] border-0 bg-transparent p-0 shadow-none ring-0"
          showClose={false}
        >
          <DialogTitle className="sr-only">{alt || t('markdown.zoom')}</DialogTitle>
          <div className="relative flex items-center justify-center">
            {paintSrc && (
              <img
                src={paintSrc}
                alt={alt || ''}
                className="max-h-[85vh] max-w-[90vw] object-contain"
              />
            )}
            <div className="absolute top-2 end-2 flex gap-2">
              <button
                type="button"
                onClick={handleDownload}
                className="p-2 rounded-lg bg-black/60 text-white hover:bg-black/80"
                title={t('markdown.download')}
                aria-label={t('markdown.download')}
              >
                <Download className="h-5 w-5" />
              </button>
              <button
                type="button"
                onClick={handleOpenNew}
                className="p-2 rounded-lg bg-black/60 text-white hover:bg-black/80"
                title={t('markdown.openInNewTab')}
                aria-label={t('markdown.openInNewTab')}
              >
                <ExternalLink className="h-5 w-5" />
              </button>
              <button
                type="button"
                onClick={() => setIsZoomed(false)}
                className="p-2 rounded-lg bg-black/60 text-white hover:bg-black/80"
                title={t('window.close', { defaultValue: 'Close' })}
                aria-label={t('window.close', { defaultValue: 'Close' })}
              >
                ×
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
})

// ---------------------------------------------------------------------------
// Table copy (paste-into-Word).
//
// Writes BOTH `text/html` (a clean bordered <table>) and `text/plain` (TSV) to
// the clipboard via ClipboardItem so Word / Excel / Google-Docs paste a REAL
// editable table (those targets read the HTML flavor), while plain-text targets
// get tab-separated rows. Falls back to writeText(TSV) when ClipboardItem is
// unavailable (older browsers / insecure context). Cells are flattened to text
// (no nested markup) and HTML-escaped — the model controls this content.
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function serializeTable(tableEl) {
  const rows = Array.from(tableEl.querySelectorAll('tr'))
  const cellText = (c) => (c.innerText || c.textContent || '').replace(/\s+/g, ' ').trim()

  const tsv = rows
    .map((tr) => Array.from(tr.querySelectorAll('th,td')).map(cellText).join('\t'))
    .join('\n')

  const htmlRows = rows
    .map((tr) => {
      const cells = Array.from(tr.querySelectorAll('th,td'))
        .map((c) => {
          const tag = c.tagName.toLowerCase() === 'th' ? 'th' : 'td'
          return `<${tag} style="border:1px solid #999;padding:4px 8px;text-align:start;">${escapeHtml(cellText(c))}</${tag}>`
        })
        .join('')
      return `<tr>${cells}</tr>`
    })
    .join('')
  const html = `<table style="border-collapse:collapse;border:1px solid #999;">${htmlRows}</table>`

  return { tsv, html }
}

const TableBlock = memo(function TableBlock({ children }) {
  const { t } = useTranslation('chat')
  const tableRef = useRef(null)
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    const el = tableRef.current
    if (!el) return
    const { tsv, html } = serializeTable(el)
    try {
      if (navigator.clipboard?.write && window.ClipboardItem) {
        await navigator.clipboard.write([
          new window.ClipboardItem({
            'text/html': new Blob([html], { type: 'text/html' }),
            'text/plain': new Blob([tsv], { type: 'text/plain' }),
          }),
        ])
      } else {
        await navigator.clipboard.writeText(tsv)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      toast.error(t('window.copyFailed'))
    }
  }, [t])

  return (
    <div className="group/table relative my-4">
      <button
        onClick={handleCopy}
        className="absolute end-2 top-2 z-10 flex items-center gap-1 rounded-md border border-border bg-background/80 px-2 py-1 text-xs text-foreground-secondary backdrop-blur-sm transition-opacity hover:text-foreground opacity-0 group-hover/table:opacity-100 focus-visible:opacity-100 max-md:static max-md:mb-1 max-md:ms-auto max-md:w-fit max-md:opacity-100"
        title={copied ? t('markdown.tableCopied') : t('markdown.copyTable')}
        aria-label={copied ? t('markdown.tableCopied') : t('markdown.copyTable')}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-success" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
      <div className="overflow-x-auto">
        <table ref={tableRef} className="min-w-full border-collapse">
          {children}
        </table>
      </div>
    </div>
  )
})

// Check if code language is runnable in CodeCanvas
const isRunnableLanguage = (lang) => {
  const runnableLanguages = ['html', 'htm', 'css', 'javascript', 'js', 'jsx']
  return runnableLanguages.includes(lang?.toLowerCase())
}

const CodeBlock = memo(function CodeBlock({ node, inline, className, children, onRunCode, ...props }) {
  const { t } = useTranslation('chat')
  const [copied, setCopied] = useState(false)
  // Theme-aware syntax highlighting: oneLight on the (default) light theme,
  // oneDark on dark. The hardcoded dark `#1e1e1e` background was jarring on the
  // light surface; each prism theme now supplies its own matching background.
  const { isDark } = useTheme()
  const prismTheme = isDark ? themes.oneDark : themes.oneLight
  const match = /language-(\w+)/.exec(className || '')
  const language = match ? match[1] : ''
  const code = String(children).replace(/\n$/, '')
  // react-markdown v9 no longer passes the `inline` prop, so it would always be
  // undefined and every code node would render the block <pre> variant — which
  // is invalid inside react-markdown's <p> wrapper (validateDOMNesting). Derive
  // it: inline code has no `language-*` class and no newline; else it's a fence.
  const isInline = inline ?? (!className && !code.includes('\n'))

  const isRunnable = isRunnableLanguage(language) && onRunCode

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      toast.error(t('window.copyFailed'))
    }
  }

  const handleRun = () => {
    if (onRunCode) {
      onRunCode(code, language)
    }
  }

  if (isInline) {
    return (
      <code
        dir="ltr"
        className="rounded bg-background-tertiary px-1.5 py-0.5 text-foreground font-mono text-sm text-start"
        {...props}
      >
        {children}
      </code>
    )
  }

  return (
    <div className="group my-4 rounded-lg overflow-hidden border border-border">
      {/* Language badge + actions. Reachability of Run/Copy on tall blocks
          comes from the maxHeight cap on the <pre> below (the block fits the
          viewport, code scrolls internally). Do NOT make this bar sticky —
          position:sticky misplaces inside the virtualizer's translateY rows. */}
      <div className="flex items-center justify-between px-4 py-2 bg-background-tertiary border-b border-border">
        <span className="text-xs text-foreground-secondary font-mono">
          {language || 'code'}
        </span>
        <div className="flex items-center gap-2">
          {isRunnable && (
            <button
              onClick={handleRun}
              className="flex items-center gap-1 text-xs text-success hover:text-success/80 transition-colors font-medium"
              title={t('markdown.runInCodeCanvas')}
              aria-label={t('markdown.runInCodeCanvas')}
            >
              <Play className="h-3.5 w-3.5" />
              {t('codeCanvas.run')}
            </button>
          )}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-xs text-foreground-secondary hover:text-foreground transition-colors"
            aria-label={copied ? t('messageActions.copied') : t('messageActions.copy')}
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-success" />
                {t('messageActions.copied')}
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" />
                {t('messageActions.copy')}
              </>
            )}
          </button>
        </div>
      </div>

      {/* Code block with prism-react-renderer */}
      <Highlight
        theme={prismTheme}
        code={code}
        language={language || 'text'}
      >
        {({ className: highlightClassName, style, tokens, getLineProps, getTokenProps }) => (
          <pre
            dir="ltr"
            className={highlightClassName}
            style={{
              ...style,
              margin: 0,
              padding: '1rem',
              overflow: 'auto',
              // Cap tall blocks (ChatGPT-style): the code scrolls INTERNALLY,
              // so the header bar with Run/Copy stays within reach instead of
              // hundreds of lines up after the chat autoscrolls to the bottom.
              maxHeight: '55vh',
              fontSize: '0.875rem',
              lineHeight: '1.5',
              textAlign: 'left',
            }}
          >
            {tokens.map((line, i) => (
              <div key={i} {...getLineProps({ line })}>
                {line.map((token, key) => (
                  <span key={key} {...getTokenProps({ token })} />
                ))}
              </div>
            ))}
          </pre>
        )}
      </Highlight>
    </div>
  )
})

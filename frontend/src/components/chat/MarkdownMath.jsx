import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

// Math-enabled markdown render path. Imported on-demand (lazyWithRetry) by
// MarkdownRenderer only when the message actually contains TeX, so the katex
// JS + CSS + woff2 fonts never load on the plain /chat route.
//
// The `components` map is passed in from MarkdownRenderer so CodeBlock /
// ImageRenderer / table / anchor rendering is byte-identical to the plain path
// — the ONLY difference here is the added remarkMath + rehypeKatex plugins.
//
// singleDollarTextMath is ENABLED: LLMs overwhelmingly emit inline math with a
// single `$...$`, so leaving it off rendered legitimate math literally. The
// MarkdownRenderer gate already keeps prose-currency ("$20 and $30") off this
// path, so flipping it on doesn't turn prices into math.

// HTML sanitization schema (SECURITY-CRITICAL) — see the long note in
// MarkdownRenderer.jsx. Kept byte-for-byte in sync with that file's schema;
// a shared module isn't used to keep this fix scoped to these two files.
// `rehypeSanitize` runs over the raw HTML BEFORE `rehypeKatex` renders, so
// KaTeX's generated MathML/spans (produced after sanitize) survive while a
// model-injected `<iframe srcdoc="<script>…">`/`<script>` is stripped.
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
    span: [
      ...(defaultSchema.attributes?.span || []),
      'className', 'style', 'ariaHidden',
    ],
    div: [
      ...(defaultSchema.attributes?.div || []),
      'className', 'style', 'ariaHidden',
    ],
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
    '*': [
      ...(defaultSchema.attributes?.['*'] || []),
      'mathvariant', 'displaystyle', 'scriptlevel',
    ],
  },
}

// LaTeX-style \( \) / \[ \] delimiters → $ / $$ that remark-math understands
// (remark-math only tokenises dollar math). Conversion skips fenced + inline
// code spans so literal backslash sequences inside code stay intact.
const PAREN_MATH = /\\\(([\s\S]+?)\\\)/g
const BRACK_MATH = /\\\[([\s\S]+?)\\\]/g

function normalizeMathDelimiters(input) {
  if (typeof input !== 'string') return input
  if (!input.includes('\\(') && !input.includes('\\[')) return input
  return input
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((seg, i) =>
      i % 2 === 1
        ? seg // captured code span — leave untouched
        : seg
            .replace(BRACK_MATH, (_, m) => '$$' + m + '$$')
            .replace(PAREN_MATH, (_, m) => '$' + m + '$'),
    )
    .join('')
}

export default function MarkdownMath({ content, components }) {
  const normalized = normalizeMathDelimiters(content)
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: true }]]}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema], rehypeKatex]}
      components={components}
    >
      {normalized}
    </ReactMarkdown>
  )
}

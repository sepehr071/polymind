/**
 * Build a Markdown report from a Data Analyzer conversation.
 *
 * Walks the message list and, for each assistant turn, emits the prose answer
 * followed by its settled artifacts (metadata.data_artifacts.artifacts):
 *   - table   → GFM Markdown table
 *   - metric  → `**label:** value` bullet
 *   - chart   → titled blockquote (interactive chart lives in-app)
 *   - insight → blockquote
 *   - file    → download link (url + original name)
 */

function escapeMdCell(value) {
  if (value == null) return ''
  return String(value).replace(/\|/g, '\\|').replace(/\r?\n/g, ' ')
}

function tableToMarkdown(artifact) {
  const columns = Array.isArray(artifact?.columns) ? artifact.columns : []
  const rows = Array.isArray(artifact?.rows) ? artifact.rows : []
  if (columns.length === 0) return ''
  const headers = columns.map((c) => escapeMdCell(c.label || c.key))
  const sep = columns.map(() => '---')
  const lines = [`| ${headers.join(' | ')} |`, `| ${sep.join(' | ')} |`]
  for (const row of rows) {
    const cells = columns.map((c) => escapeMdCell(row?.[c.key]))
    lines.push(`| ${cells.join(' | ')} |`)
  }
  return lines.join('\n')
}

function artifactToMarkdown(artifact) {
  if (!artifact || typeof artifact !== 'object') return ''
  switch (artifact.type) {
    case 'table': {
      const body = tableToMarkdown(artifact)
      if (!body) return ''
      const title = artifact.name || artifact.title
      return title ? `### ${title}\n\n${body}` : body
    }
    case 'metric': {
      const unit = artifact.unit ? ` ${artifact.unit}` : ''
      return `- **${artifact.label ?? ''}:** ${artifact.value ?? ''}${unit}`
    }
    case 'chart': {
      const title = artifact.title || 'untitled'
      const kind = artifact.kind || 'chart'
      return `> **Chart:** ${title} (${kind})\n>\n> _Interactive chart available in the app._`
    }
    case 'insight':
      return `> ${artifact.text ?? ''}`
    case 'file': {
      const name = artifact.name || artifact.filename || artifact.original_name || 'file'
      const url = artifact.url || artifact.download_url || ''
      if (url) return `- **File:** [${name}](${url})`
      return `- **File:** ${name}`
    }
    default:
      return ''
  }
}

/**
 * @param {Array<object>} messages
 * @param {{ title?: string }} [opts]
 * @returns {string}
 */
export function buildDataReport(messages, opts = {}) {
  const list = Array.isArray(messages) ? messages : []
  const title = opts.title || 'Data Analysis Report'
  const sections = []
  for (const msg of list) {
    if (msg?.role !== 'assistant') continue
    const parts = []
    const prose = String(msg.content ?? '').trim()
    if (prose) parts.push(prose)

    const artifacts = msg.metadata?.data_artifacts?.artifacts
    if (Array.isArray(artifacts)) {
      for (const artifact of artifacts) {
        const md = artifactToMarkdown(artifact)
        if (md) parts.push(md)
      }
    }

    if (parts.length > 0) sections.push(parts.join('\n\n'))
  }

  const body = sections.join('\n\n---\n\n')
  return `# ${title}\n\n${body}\n`
}

/** Trigger a browser download of `content` as a `.md` file. */
export function downloadMarkdown(content, filename) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.md') ? filename : `${filename}.md`
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export default buildDataReport

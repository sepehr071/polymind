import MarkdownRenderer from './MarkdownRenderer'
import MessageSources from './MessageSources'
// Lazy boundary — ECharts + react-table load only when a shared snapshot
// actually contains a data-analyzer turn.
import DataAnalysisBlock from './DataAnalysis/LazyDataAnalysisBlock'
import { getInitials, avatarColors } from '../../utils/avatarColor'
import { getTextDirection } from '../../utils/rtl'
import { FileText } from 'lucide-react'

/* Sender chip above a user bubble (collaborative-chat attribution). */
function SenderTag({ sender }) {
  if (!sender?.name) return null
  const { bg, fg } = avatarColors(sender.name)
  return (
    <div className="mb-1 flex items-center gap-1.5">
      <span
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold"
        style={{ backgroundColor: bg, color: fg }}
      >
        {getInitials(sender.name)}
      </span>
      <span className="text-xs text-foreground-tertiary">{sender.name}</span>
    </div>
  )
}

function AttachmentChips({ atts }) {
  if (!atts?.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
      {atts.map((a, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background-secondary px-2 py-0.5 text-xs text-foreground-secondary"
        >
          <FileText className="h-3 w-3 shrink-0" />
          <span dir="ltr" className="max-w-[12rem] truncate">{a.filename || 'file'}</span>
        </span>
      ))}
    </div>
  )
}

/**
 * SharedChatView — read-only render of a frozen snapshot. Reuses the XSS-
 * sanitized MarkdownRenderer (onRunCode omitted → no Code-Canvas Run) and the
 * extracted MessageSources. No composer, no per-message actions.
 */
export default function SharedChatView({ messages }) {
  return (
    <div className="mx-auto w-full max-w-[768px] space-y-7 px-4 py-6">
      {(messages || []).map((m, i) => {
        const dir = getTextDirection(m.content || '')
        if (m.role === 'user') {
          return (
            <div key={i} className="flex flex-col items-end rtl:items-start">
              <SenderTag sender={m.sender} />
              <div className="max-w-[80%] rounded-2xl rounded-ee-md bg-accent px-4 py-2.5 text-[15px] leading-7 text-accent-foreground shadow-sm">
                <p
                  className="whitespace-pre-wrap break-words"
                  dir={dir}
                  style={dir === 'rtl' ? { fontFamily: "'Vazirmatn', ui-sans-serif, system-ui, sans-serif" } : {}}
                >
                  {m.content}
                </p>
              </div>
              <AttachmentChips atts={m.attachments} />
            </div>
          )
        }
        // Snapshot serializer flattens metadata fields (e.g. annotations) to the
        // top level; accept either shape for the Data Analyzer payload.
        const dataArtifacts = m.data_artifacts || m.metadata?.data_artifacts || null
        return (
          <div key={i}>
            {/* Charts/tables render ABOVE the prose answer (matches the live
                stream order + the answer's "the chart above…" wording). */}
            {dataArtifacts && (
              <DataAnalysisBlock steps={dataArtifacts.steps} artifacts={dataArtifacts.artifacts} />
            )}
            <div
              className={`markdown-content text-[15px] leading-[1.65] text-foreground${dataArtifacts ? ' mt-3' : ''}`}
              dir={dir}
            >
              <MarkdownRenderer content={m.content || ''} onRunCode={undefined} />
            </div>
            <MessageSources annotations={m.annotations} />
          </div>
        )
      })}
    </div>
  )
}

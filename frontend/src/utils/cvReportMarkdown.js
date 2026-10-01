/**
 * Build a recruiter-handoff markdown report from a CV checker result.
 * @param {object|null} r - result.result payload
 * @param {object} labels - flat string labels (caller translates)
 * @param {object} [meta]
 */
export function cvReportMarkdown(r, labels = {}, meta = {}) {
  if (!r) return ''
  const L = labels
  const lines = []

  lines.push(`# ${L.title || 'CV screening note'}`)
  lines.push('')
  if (meta.disclaimer) {
    lines.push(`> ${meta.disclaimer}`)
    lines.push('')
  }
  if (r.summary) {
    lines.push(`## ${L.summary || 'Summary'}`)
    lines.push(r.summary)
    lines.push('')
  }

  const bits = []
  if (r.overall_score != null) bits.push(`**${L.score || 'Overall'}:** ${r.overall_score}`)
  if (r.match_score != null) bits.push(`**${L.match || 'JD match'}:** ${r.match_score}`)
  if (r.recommendation) {
    const recLabel = L[`rec_${r.recommendation}`] || r.recommendation
    bits.push(`**${L.recommendation || 'Suggestion'}:** ${recLabel}`)
  }
  if (bits.length) {
    lines.push(bits.join(' · '))
    lines.push('')
  }

  const checklist = Array.isArray(r.must_have_checklist) ? r.must_have_checklist : []
  if (checklist.length) {
    lines.push(`## ${L.mustHaves || 'Must-haves'}`)
    for (const row of checklist) {
      const st = row.status || '?'
      const ev = row.evidence ? ` — ${row.evidence}` : ''
      lines.push(`- [${st}] ${row.item || ''}${ev}`)
    }
    lines.push('')
  }

  const dims = Array.isArray(r.dimensions) ? r.dimensions : []
  if (dims.length) {
    lines.push(`## ${L.dimensions || 'Dimensions'}`)
    for (const d of dims) {
      const sc = d.score != null ? ` (${d.score})` : ''
      const notes = d.notes ? `: ${d.notes}` : ''
      lines.push(`- **${d.label || d.id}**${sc}${notes}`)
    }
    lines.push('')
  }

  const kw = r.keywords || {}
  const present = Array.isArray(kw.present) ? kw.present : []
  const missing = Array.isArray(kw.missing) ? kw.missing : []
  if (present.length || missing.length) {
    lines.push(`## ${L.keywords || 'Keywords'}`)
    if (present.length) lines.push(`- **${L.keywordsPresent || 'Present'}:** ${present.join(', ')}`)
    if (missing.length) lines.push(`- **${L.keywordsMissing || 'Missing'}:** ${missing.join(', ')}`)
    lines.push('')
  }

  if (Array.isArray(r.strengths) && r.strengths.length) {
    lines.push(`## ${L.strengths || 'Strengths'}`)
    r.strengths.forEach((s) => lines.push(`- ${s}`))
    lines.push('')
  }
  if (Array.isArray(r.gaps) && r.gaps.length) {
    lines.push(`## ${L.gaps || 'Gaps'}`)
    r.gaps.forEach((s) => lines.push(`- ${s}`))
    lines.push('')
  }

  const iqs = Array.isArray(r.interview_questions) ? r.interview_questions : []
  const fallbackQs = Array.isArray(r.risks_or_questions) ? r.risks_or_questions : []
  if (iqs.length) {
    lines.push(`## ${L.questions || 'Interview questions'}`)
    iqs.forEach((q, i) => {
      const text = typeof q === 'string' ? q : q.question
      const why = typeof q === 'object' && q.rationale ? ` _( ${q.rationale} )_` : ''
      lines.push(`${i + 1}. ${text}${why}`)
    })
    lines.push('')
  } else if (fallbackQs.length) {
    lines.push(`## ${L.questions || 'Questions to verify'}`)
    fallbackQs.forEach((s) => lines.push(`- ${s}`))
    lines.push('')
  }

  const imps = Array.isArray(r.improvements) ? r.improvements : []
  if (imps.length) {
    lines.push(`## ${L.improvements || 'Improvements'}`)
    imps.forEach((row) => {
      lines.push(
        `- **[${row.priority || '?'}]** ${row.section || ''}: ${row.issue || ''} → ${row.suggestion || ''}`,
      )
    })
    lines.push('')
  }

  const bullets = Array.isArray(r.rewritten_bullets) ? r.rewritten_bullets : []
  if (bullets.length) {
    lines.push(`## ${L.rewrites || 'Rewritten bullets'}`)
    bullets.forEach((b) => {
      lines.push(`- ~~${b.original || ''}~~`)
      lines.push(`  → ${b.improved || ''}`)
    })
    lines.push('')
  }

  if (Array.isArray(r.language_notes) && r.language_notes.length) {
    lines.push(`## ${L.languageNotes || 'Language notes'}`)
    r.language_notes.forEach((s) => lines.push(`- ${s}`))
    lines.push('')
  }

  return lines.join('\n').trim() + '\n'
}

export function interviewQuestionsText(r) {
  if (!r) return ''
  const iqs = Array.isArray(r.interview_questions) ? r.interview_questions : []
  if (iqs.length) {
    return iqs
      .map((q, i) => {
        const text = typeof q === 'string' ? q : q.question
        const why = typeof q === 'object' && q.rationale ? ` (${q.rationale})` : ''
        return `${i + 1}. ${text}${why}`
      })
      .join('\n')
  }
  const fallback = Array.isArray(r.risks_or_questions) ? r.risks_or_questions : []
  return fallback.map((s, i) => `${i + 1}. ${s}`).join('\n')
}

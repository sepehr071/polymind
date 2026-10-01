/**
 * Studio DLP pre-flight message builders.
 * Must match backend app/utils/studio_dlp.py + POST /dlp/scan join:
 *   scan_text = attachment_text ? `${message}\n\n${attachment_text}` : message
 * Attachment extracts load server-side from upload_ids — FE never sends extract text.
 */

export function emailWriterScanText(templateId, fields = {}) {
  const parts = [`template:${templateId}`]
  for (const v of Object.values(fields || {})) {
    if (v == null) continue
    const s = String(v).trim()
    if (s) parts.push(s)
  }
  return parts.join('\n\n')
}

/** Non-attachment message for CV checker (focus + JD text). */
export function cvMessageText(focus = '', jdText = '') {
  const parts = []
  for (const s of [focus, jdText]) {
    if ((s || '').trim()) parts.push(s.trim())
  }
  return parts.join('\n\n')
}

/** Non-attachment message for research (query + focus). */
export function researchMessageText(query = '', focus = '') {
  const parts = []
  for (const s of [query, focus]) {
    if ((s || '').trim()) parts.push(s.trim())
  }
  return parts.join('\n\n')
}

/** Must match backend shop_message_text (need + qty + optional budget + notes). */
export function shopMessageText(need = '', qty = 1, maxBudgetToman = null, notes = '') {
  const parts = []
  if ((need || '').trim()) parts.push(need.trim())
  parts.push(`qty:${qty}`)
  if (maxBudgetToman != null && String(maxBudgetToman).trim() !== '') {
    parts.push(`budget_toman:${maxBudgetToman}`)
  }
  if ((notes || '').trim()) parts.push(notes.trim())
  return parts.join('\n\n')
}

/**
 * Mirror backend meeting_action_pack_scan_text (title + transcript + exec only).
 * Cap 200000. Sentinel when empty.
 */
export function meetingActionPackScanText(meeting, transcript, summary) {
  const title = ((meeting?.title || 'Untitled').trim() || 'Untitled')
  const lines = [`# Meeting: ${title}`, '']

  if (transcript != null) {
    const plain = (transcript.plain_text || '').trim()
    if (plain) {
      lines.push('## Transcript', '', plain, '')
    }
  }

  if (summary != null) {
    const exec = (summary.exec_summary || '').trim()
    if (exec) {
      lines.push('## Summary', '', exec, '')
    }
  }

  let text = `${lines.join('\n').replace(/\s+$/, '')}\n`
  if (text.length > 200000) text = text.slice(0, 200000)
  return text.trim() ? text : '[meeting action pack]'
}

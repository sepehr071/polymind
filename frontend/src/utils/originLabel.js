/**
 * Friendly i18n label for a usage-log `origin` value.
 *
 * `usage_logs.origin` carries raw machine values (`web`, `helper`, `dlp`,
 * `workflow`, …). Analytics breakdowns shouldn't surface those — map each to an
 * `analytics:origin.*` key so the same value reads "Chat" / "چت" per locale.
 * Unknown values fall back to a title-cased version of the raw string.
 *
 *   originLabel('web', t)   → 'Chat' / 'چت'
 *   originLabel('dlp', t)   → 'Content safety' / 'ایمن‌سازی محتوا'
 *   originLabel('foo_bar', t) → 'Foo Bar'
 *
 * @param {string|null|undefined} origin
 * @param {(key:string, fallback?:string)=>string} t  i18next t bound to 'analytics'
 * @returns {string}
 */

// Raw origin/feature → analytics i18n key (under the `origin` tree).
// Usage tab groups by `feature` (email_writer, ocr, …) and also origin (web, helper).
const ORIGIN_KEYS = {
  web: 'origin.web',
  chat: 'origin.chat',
  helper: 'origin.helper',
  meeting: 'origin.meeting',
  meeting_action_pack: 'origin.meeting_action_pack',
  dlp: 'origin.dlp',
  content_safety: 'origin.content_safety',
  dlp_guidance: 'origin.dlp_guidance',
  auto_title: 'origin.auto_title',
  workflow: 'origin.workflow',
  workflow_ai: 'origin.workflow',
  automate: 'origin.automate',
  arena: 'origin.arena',
  debate: 'origin.debate',
  image: 'origin.image',
  image_prompt: 'origin.image',
  image_generation: 'origin.image',
  email_writer: 'origin.email_writer',
  cv_checker: 'origin.cv_checker',
  ocr: 'origin.ocr',
  research: 'origin.research',
  contract: 'origin.contract',
  tender: 'origin.tender',
  shop_assistant: 'origin.shop',
  data_analyzer: 'origin.data_analyzer',
  data_pdf_extract: 'origin.data_analyzer',
  data_doc_extract: 'origin.data_analyzer',
  data_extract_cache: 'origin.data_analyzer',
  presentation: 'origin.presentation',
  presentation_image: 'origin.presentation',
  agent: 'origin.agent',
  config_suggest: 'origin.config_suggest',
  video: 'origin.video',
  payroll: 'origin.payroll',
  knowledge: 'origin.knowledge',
}

/** Title-case a raw snake/kebab value for the unknown-origin fallback. */
function titlecase(raw) {
  return String(raw)
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function originLabel(origin, t) {
  if (!origin) return ''
  const key = ORIGIN_KEYS[origin] || `origin.${origin}`
  const fallback = titlecase(origin)
  if (typeof t !== 'function') return fallback
  return t(key, { defaultValue: fallback })
}

export default originLabel

/**
 * Feature flag inventory + helper.
 *
 * The list of flag keys is the source of truth for both the frontend
 * (sidebar/route gating, command palette) and the Platform Features page.
 * Backend mirrors this list in `backend/app/models/platform_settings.py`.
 */
export const FEATURE_FLAG_KEYS = [
  'arena',
  'debate',
  'image_studio',
  'workflow',
  'knowledge',
  'automate_agent',
  'meetings',
  'code_canvas_run',
  'data_analyzer',
  'payroll',
  'presentations',
  'agent',
  'ocr_assistant',
  'email_writer',
  'cv_checker',
  'research_assistant',
  'contract_reviewer',
  'tender_assistant',
  'shop_assistant',
  'billing_enforcement',
]

/**
 * Default-deny when the features block is missing/undefined.
 * Only a strict-boolean `true` enables a feature.
 */
export function hasFeature(user, name) {
  return Boolean(user?.features?.[name])
}

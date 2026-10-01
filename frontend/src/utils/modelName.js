/**
 * Friendly model display names from OpenRouter-style slugs (`vendor/model-id`).
 *
 * Analytics + usage tables get raw slugs like `google/gemini-3.5-flash-lite`.
 * Showing the slug is ugly and the naive `.split('/').pop()` still reads
 * `gemini-3.5-flash-lite`. `prettifyModelName` first checks a curated override
 * map (seeded from the quick-model catalog), then falls back to a slug
 * prettifier: drop the vendor, strip noise suffixes, title-case each token with
 * an acronym map, and KEEP version tokens (`3.5`, `5.6`).
 *
 *   google/gemini-3.5-flash-lite  → 'Gemini 3.5 Flash Lite'
 *   openai/gpt-5-mini             → 'GPT-5 Mini'
 *   x-ai/grok-4.5                 → 'Grok 4.5'
 *
 * Memoised in a Map (analytics renders the same handful of ids per row × every
 * re-render). null/empty → ''.
 */

// Curated overrides — exact slug → display name. Seeded from the quick-model
// fallback catalog so the common models match the chat picker's labels exactly.
const OVERRIDES = {
  'google/gemini-3.5-flash-lite': 'Gemini 3.5 Flash Lite',
  'google/gemini-3.6-flash': 'Gemini 3.6 Flash',
  'anthropic/claude-opus-5': 'Claude Opus 5',
  'openai/gpt-5.6-sol': 'GPT-5.6 Sol',
  'deepseek/deepseek-v4-flash-0731': 'DeepSeek V4 Flash 0731',
  'minimax/minimax-m2.7': 'MiniMax M2.7',
  'openai/gpt-5-mini': 'GPT-5 Mini',
  'x-ai/grok-4.5': 'Grok 4.5',
  'nvidia/nemotron-3-ultra-550b-a55b:free': 'Nemotron 3 Ultra (Free)',
  'google/gemma-4-26b-a4b-it:free': 'Gemma 4 26B A4B (Free)',
  'google/gemma-4-31b-it': 'Gemma 4 31B',
  'google/gemma-4-31b-it:free': 'Gemma 4 31B (Free)',
}

// Token → canonical casing for vendor acronyms / brand names. Lower-cased keys.
const ACRONYMS = {
  gpt: 'GPT',
  gpt5: 'GPT-5',
  glm: 'GLM',
  deepseek: 'DeepSeek',
  minimax: 'MiniMax',
  grok: 'Grok',
  gemini: 'Gemini',
  claude: 'Claude',
  qwen: 'Qwen',
  llama: 'Llama',
  mistral: 'Mistral',
}

const cache = new Map()

/** Title-case a single slug token, honoring the acronym map + version tokens. */
function titleToken(token) {
  if (!token) return ''
  const lower = token.toLowerCase()
  if (ACRONYMS[lower]) return ACRONYMS[lower]
  // Pure version token (3.1, 5, 2.7) — keep as-is.
  if (/^\d+(\.\d+)*$/.test(token)) return token
  // Mixed alpha+digit like "gpt5"/"m2" — split the acronym prefix if known.
  const m = lower.match(/^([a-z]+)(\d.*)$/)
  if (m && ACRONYMS[m[1]]) return `${ACRONYMS[m[1]]}-${m[2]}`
  return token.charAt(0).toUpperCase() + token.slice(1)
}

/**
 * @param {string|null|undefined} id  OpenRouter model slug
 * @returns {string} friendly name ('' for null/empty)
 */
export function prettifyModelName(id) {
  if (!id) return ''
  if (cache.has(id)) return cache.get(id)

  let out = OVERRIDES[id]
  if (!out) {
    // vendor/model → model; strip noise suffixes; title-case the remaining tokens.
    const slug = String(id).split('/').pop() || ''
    const cleaned = slug.replace(/(-preview|-latest|:free)+$/gi, '')
    out = cleaned
      .split('-')
      .filter(Boolean)
      .map(titleToken)
      .join(' ')
      .trim()
    if (!out) out = slug
  }

  cache.set(id, out)
  return out
}

/**
 * Friendly label from an OpenRouter DISPLAY name (not a slug): drops the
 * "Vendor: " prefix and any parenthetical tech-name suffix.
 *
 *   'OpenAI: GPT-5.4 Image 2'                              → 'GPT-5.4 Image 2'
 *   'Google: Nano Banana 2 (Gemini 3.1 Flash Image Preview)' → 'Nano Banana 2'
 *   'Auto Router'                                          → 'Auto Router'
 *
 * @param {string|null|undefined} name  OpenRouter display name
 * @returns {string} friendly label ('' for null/empty)
 */
export function friendlyModelLabel(name) {
  if (!name) return ''
  return String(name)
    .replace(/^[^:]{2,24}:\s*/, '')
    .replace(/\s*\([^)]*\)\s*$/, '')
    .trim() || String(name)
}

export default prettifyModelName

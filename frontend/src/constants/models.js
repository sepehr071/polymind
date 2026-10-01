/**
 * Ordered list of quick model IDs — used to resolve live registry entries.
 */
export const QUICK_MODEL_IDS = [
  'google/gemini-3.5-flash-lite',
  'google/gemini-3.6-flash',
  'anthropic/claude-opus-5',
  'openai/gpt-5.6-sol',
  'deepseek/deepseek-v4-flash-0731',
  'x-ai/grok-4.5',
  'nvidia/nemotron-3-ultra-550b-a55b:free',
  'google/gemma-4-26b-a4b-it:free',
  // Kept LAST on purpose: QUICK_MODEL_IDS[0] is the default chat/data/assistant
  // model (ChatPage/DataAnalyzerPage/ConfigEditor) — local-ai must not be default.
  'polymind/local-ai',
]

/**
 * Static fallback — used when the live model registry is empty or unavailable.
 * MUST mirror backend `app/utils/quick_models.py:QUICK_MODELS` (id + order):
 * the backend resolver now REJECTS any `quick:<id>` not in that allowlist
 * (denial-of-wallet fix), so a drifted id here resolves to nothing and breaks
 * the default chat on the cold-cache/offline path. Keep both in sync.
 *
 * Fields:
 *  - logo: vendor key for ModelLogo (google|anthropic|openai|deepseek|xai|nvidia|gemma|local)
 *  - tier: 'free' | 'expensive' | 'local' | omitted (standard) — drives picker badges
 */
export const _FALLBACK_QUICK_MODELS = [
  {
    id: 'google/gemini-3.5-flash-lite',
    name: 'Gemini 3.5 Flash Lite',
    logo: 'google',
    descKey: 'gemini35FlashLite',
    description: 'Cheapest & fastest — reads audio, video, images',
    speed: 3,
    intelligence: 1,
    modalities: ['text', 'image', 'audio', 'video', 'file'],
  },
  {
    id: 'google/gemini-3.6-flash',
    name: 'Gemini 3.6 Flash',
    logo: 'google',
    descKey: 'gemini36Flash',
    description: 'Fast and smart multimodal from Google',
    speed: 3,
    intelligence: 3,
    modalities: ['text', 'image', 'audio', 'video', 'file'],
  },
  {
    id: 'anthropic/claude-opus-5',
    name: 'Claude Opus 5',
    logo: 'anthropic',
    tier: 'expensive',
    descKey: 'claudeOpus5',
    description: "Anthropic's most capable Opus",
    speed: 1,
    intelligence: 3,
    modalities: ['text', 'image', 'file'],
  },
  {
    id: 'openai/gpt-5.6-sol',
    name: 'GPT-5.6 Sol',
    logo: 'openai',
    tier: 'expensive',
    descKey: 'gpt56Sol',
    description: 'OpenAI flagship — top reasoning',
    speed: 1,
    intelligence: 3,
    modalities: ['text', 'image', 'file'],
  },
  {
    id: 'deepseek/deepseek-v4-flash-0731',
    name: 'DeepSeek V4 Flash 0731',
    logo: 'deepseek',
    descKey: 'deepseekV4Flash0731',
    description: 'Fast, ultra-cheap reasoning',
    speed: 2,
    intelligence: 2,
    modalities: ['text'],
  },
  {
    id: 'x-ai/grok-4.5',
    name: 'Grok 4.5',
    logo: 'xai',
    tier: 'expensive',
    descKey: 'grok45',
    description: 'xAI flagship — fast & capable',
    speed: 2,
    intelligence: 3,
    modalities: ['text', 'image', 'file'],
  },
  {
    id: 'nvidia/nemotron-3-ultra-550b-a55b:free',
    name: 'Nemotron 3 Ultra',
    logo: 'nvidia',
    tier: 'free',
    descKey: 'nemotron3UltraFree',
    description: 'Free frontier reasoning — 1M context',
    speed: 2,
    intelligence: 2,
    modalities: ['text'],
  },
  {
    // Free #2. 31B :free is chronically upstream-429; 26B A4B free is live-OK.
    id: 'google/gemma-4-26b-a4b-it:free',
    name: 'Gemma 4 26B',
    logo: 'gemma',
    tier: 'free',
    descKey: 'gemma426bFree',
    description: 'Free multimodal from Google',
    speed: 2,
    intelligence: 2,
    modalities: ['text', 'image', 'video'],
  },
  {
    // Free self-hosted (Ollama) model. Not an OpenRouter id — the backend routes
    // it to the in-house server (silent cloud fallback when unconfigured). Kept
    // LAST so it is never QUICK_MODEL_IDS[0] (the default model).
    id: 'polymind/local-ai',
    name: 'Local AI (Polymind)',
    logo: 'local',
    tier: 'local',
    descKey: 'localAi',
    description: 'Free — runs on in-house AI, stays on company infra',
    speed: 2,
    intelligence: 2,
    modalities: ['text'],
  },
]

/**
 * Backwards-compat alias — same as _FALLBACK_QUICK_MODELS.
 * Consumers not yet migrated to the live registry keep working unchanged.
 */
export const QUICK_MODELS = _FALLBACK_QUICK_MODELS

/**
 * Default models available without creating custom assistants
 * These can be used in Chat, Arena, and Debate modes.
 * Kept as an alias of _FALLBACK_QUICK_MODELS for backwards compatibility.
 */
export const DEFAULT_MODELS = _FALLBACK_QUICK_MODELS

/**
 * Models available for browser-use Automate Agent tasks
 */
export const BROWSER_USE_MODELS = [
  { id: 'claude-sonnet-4.6', label: 'Claude Sonnet 4.6' },
  { id: 'claude-opus-4.6',   label: 'Claude Opus 4.6'   },
  { id: 'gpt-5.4-mini',      label: 'GPT-5.4 Mini'      },
]

export const DEFAULT_BROWSER_USE_MODEL = 'claude-sonnet-4.6'

/**
 * Check if a config ID is a quick model
 */
export function isQuickModel(configId) {
  return configId?.startsWith('quick:')
}

/**
 * Extract model ID from quick config ID
 */
export function getModelIdFromQuick(configId) {
  if (isQuickModel(configId)) {
    return configId.replace('quick:', '')
  }
  return configId
}

/**
 * Find a default model by its ID
 */
export function findDefaultModel(modelId) {
  return DEFAULT_MODELS.find(m => m.id === modelId)
}

/**
 * Get display name for a quick model
 */
export function getQuickModelName(modelId) {
  const model = findDefaultModel(modelId)
  return model?.name || modelId
}

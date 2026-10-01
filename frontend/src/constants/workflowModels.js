// ─── AI Agent text models ───────────────────────────────────────────────────
// Must match OpenRouter model IDs (see AIAgentNode.jsx).
// Prefixed with _FALLBACK_ — live registry consumed via useModelCatalog().aiAgentModels.
export const _FALLBACK_AI_AGENT_MODELS = [
  { id: 'google/gemini-3.6-flash',  name: 'Gemini 3.6 Flash',      costIn: null, costOut: null, ctx: null },
  { id: 'google/gemini-2.5-flash-lite',   name: 'Gemini 2.5 Flash Lite', costIn: null, costOut: null, ctx: null },
  { id: 'x-ai/grok-4.1-fast',             name: 'Grok 4.1 Fast',         costIn: null, costOut: null, ctx: null },
  { id: 'openai/gpt-5.2',                 name: 'GPT-5.2',               costIn: null, costOut: null, ctx: null },
]
// Backwards-compat alias
export const AI_AGENT_MODELS = _FALLBACK_AI_AGENT_MODELS

// ─── Image generation models ─────────────────────────────────────────────────
// Must stay in sync with backend OpenRouterService.get_image_capable_models().
// Prefixed with _FALLBACK_ — live registry consumed via useModelCatalog().imageGenModels.
export const _FALLBACK_IMAGE_GEN_MODELS = [
  { id: 'google/gemini-2.5-flash-image',         name: 'Gemini 2.5 Flash Image (Nano Banana)',     maxInputs: 3,  costIn: null, costOut: null },
  { id: 'google/gemini-3.1-flash-image', name: 'Gemini 3.1 Flash Image (Nano Banana 2)',  maxInputs: 3,  costIn: null, costOut: null },
  { id: 'google/gemini-3-pro-image-preview',     name: 'Gemini 3 Pro Image (Nano Banana Pro)',    maxInputs: 14, costIn: null, costOut: null },
  { id: 'openai/gpt-5-image-mini',               name: 'GPT-5 Image Mini',                        maxInputs: 16, costIn: null, costOut: null },
  { id: 'openai/gpt-5-image',                    name: 'GPT-5 Image',                             maxInputs: 16, costIn: null, costOut: null },
  { id: 'openai/gpt-5.4-image-2',                name: 'GPT-5.4 Image 2',                         maxInputs: 16, costIn: null, costOut: null },
]
// Backwards-compat alias
export const IMAGE_GEN_MODELS = _FALLBACK_IMAGE_GEN_MODELS

// ─── TTS models ──────────────────────────────────────────────────────────────
// Verified against live OpenRouter /api/v1/tts (see TTSNode.jsx).
// Prefixed with _FALLBACK_ — live registry consumed via useModelCatalog().ttsModels.
export const _FALLBACK_TTS_MODELS = [
  { id: 'openai/gpt-4o-mini-tts-2025-12-15', name: 'GPT-4o mini TTS', costIn: null, costOut: null },
]
// Backwards-compat alias
export const TTS_MODELS = _FALLBACK_TTS_MODELS

// OpenAI voices supported by gpt-4o-mini-tts.
export const TTS_VOICES = [
  'alloy',
  'echo',
  'fable',
  'onyx',
  'nova',
  'shimmer',
  'ash',
  'ballad',
  'coral',
  'sage',
]

// Speed range config (shared between TTSNode and any inspector).
export const TTS_SPEED = { min: 0.5, max: 2.0, step: 0.1, default: 1.0 }

// ─── Video generation models ─────────────────────────────────────────────────
// Per-model param specs verified against live OpenRouter /api/v1/videos schema.
// pricePerSec in USD (source: VideoGenNode.jsx).
// Prefixed with _FALLBACK_ — live registry consumed via useModelCatalog().videoGenModels (future).
export const _FALLBACK_VIDEO_GEN_MODELS = [
  {
    id: 'google/veo-3.1',
    name: 'Veo 3.1 (Google)',
    pricePerSec: 0.40,
    defaultDuration: 8,
    defaultResolution: '1080p',
    defaultAspectRatio: '16:9',
    supportsFrameImage: true,
    supportsAudioToggle: true,
  },
  {
    id: 'openai/sora-2-pro',
    name: 'Sora 2 Pro (OpenAI)',
    pricePerSec: 0.30,
    defaultDuration: 8,
    defaultResolution: '1080p',
    defaultAspectRatio: '16:9',
    supportsFrameImage: false,
    supportsAudioToggle: false,
  },
  {
    id: 'alibaba/wan-2.7',
    name: 'Wan 2.7 (Alibaba)',
    pricePerSec: 0.30,
    defaultDuration: 6,
    defaultResolution: '720p',
    defaultAspectRatio: '16:9',
    supportsFrameImage: true,
    supportsAudioToggle: true,
  },
]
// Backwards-compat alias
export const VIDEO_GEN_MODELS = _FALLBACK_VIDEO_GEN_MODELS

// Per-model option arrays (durations/resolutions/aspectRatios vary by model).
// Keyed by model id so inspectors can look them up without embedding MODEL_SPECS logic.
export const VIDEO_MODEL_SPECS = {
  'google/veo-3.1': {
    durations: [4, 6, 8],
    resolutions: ['720p', '1080p'],
    aspectRatios: ['16:9', '9:16'],
  },
  'openai/sora-2-pro': {
    durations: [4, 8, 12],
    resolutions: ['720p', '1080p'],
    aspectRatios: ['16:9', '9:16', '1:1'],
  },
  'alibaba/wan-2.7': {
    durations: [4, 6, 8],
    resolutions: ['720p', '1080p'],
    aspectRatios: ['16:9', '9:16', '1:1'],
  },
}

// Convenience flat arrays (union of all values across models).
export const VIDEO_RESOLUTIONS   = ['720p', '1080p']
export const VIDEO_ASPECT_RATIOS = ['16:9', '9:16', '1:1']
export const VIDEO_DURATIONS     = [4, 6, 8, 12]

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Find a model entry by id from any of the model lists above.
 * Returns undefined if not found (caller should handle gracefully).
 * @param {Array<{id: string}>} list
 * @param {string} id
 */
export const findModel = (list, id) => list.find((m) => m.id === id)

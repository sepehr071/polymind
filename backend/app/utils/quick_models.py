"""
Centralized quick-models registry — single source of truth.

Used by:
  - app/utils/config_resolver.py     (resolve `quick:<id>` to a config dict)
  - app/routes/debate.py              (enrich session listings + detail)
  - app/routes/model_catalog.py       (public endpoint surfacing quick-models)
  - frontend src/constants/models.js  (frontend fetches via /api/quick-models)

When adding / removing a quick model, edit ONLY this file. Frontend can either
fetch from `/api/quick-models` at boot OR fall back to its static list (kept
in sync manually for offline / cold-cache scenarios).
"""

# Synthetic id for the free, self-hosted local (Ollama) model. NOT an OpenRouter
# id — routed to the domestic Ollama server in OpenRouterService.chat_completion
# (see is_local_model), with a silent cloud fallback when Ollama is unconfigured.
LOCAL_MODEL_ID = 'polymind/local-ai'


def is_local_model(model_id) -> bool:
    """True when the id is the synthetic free local (Ollama) model."""
    return str(model_id) == LOCAL_MODEL_ID


# Ordered dict — preserves UI sort order. First key = default model
# (FE QUICK_MODEL_IDS[0]); keep gemini-3.5-flash-lite first, LOCAL_MODEL_ID last.
QUICK_MODELS: dict[str, str] = {
    'google/gemini-3.5-flash-lite': 'Gemini 3.5 Flash Lite',
    'google/gemini-3.6-flash': 'Gemini 3.6 Flash',
    'anthropic/claude-opus-5': 'Claude Opus 5',
    'openai/gpt-5.6-sol': 'GPT-5.6 Sol',
    'deepseek/deepseek-v4-flash-0731': 'DeepSeek V4 Flash 0731',
    'x-ai/grok-4.5': 'Grok 4.5',
    'nvidia/nemotron-3-ultra-550b-a55b:free': 'Nemotron 3 Ultra (Free)',
    # Second free slot. gemma-4-31b-it:free is chronically upstream-429; 26B A4B
    # free is multimodal and was live-OK on OpenRouter (2026-08-03 scout).
    'google/gemma-4-26b-a4b-it:free': 'Gemma 4 26B A4B (Free)',
    LOCAL_MODEL_ID: 'Local AI (Polymind)',
}

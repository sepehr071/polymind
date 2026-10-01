"""Local LLM client for the DLP smart-scan classifier (privacy).

Talks to a self-hosted **Ollama** server via its *native* ``/api/chat`` endpoint
so DLP-scanned text never leaves company infra. Deliberately isolated from
``OpenRouterService``:

- Its own ``requests.Session`` with ``trust_env=False`` so it IGNORES the
  ``HTTPS_PROXY`` / ``NO_PROXY`` env (the foreign egress tunnel on the Iran VPS)
  and connects **directly** to the domestic Ollama host. Routing DLP text
  through the foreign proxy would both leak it and fail (Ollama isn't reachable
  there).
- No ``Authorization`` header / OpenRouter base URL.
- No ``usage_logs`` write — the local model is free and high-volume.

Native ``/api/chat`` (not the OpenAI-compatible ``/v1``) is required so we can
set ``think:false`` (qwen3 is a thinking MoE), ``options.num_ctx`` (the ``/v1``
endpoint drops it; default 4096 is split across ``OLLAMA_NUM_PARALLEL`` slots),
and a JSON-schema ``format`` that grammar-constrains the verdict shape — which
also prevents any ``<think>`` leakage.

Fail-open: every error path returns ``None`` (DLP falls back to its regex pass).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator, Optional

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# Dedicated session. trust_env=False is load-bearing — it makes this client
# ignore HTTPS_PROXY/NO_PROXY (the prod egress tunnel) and hit the Ollama host
# direct. No retries: smart-scan runs on the chat send path and is fail-open.
_session = requests.Session()
_session.trust_env = False
_adapter = HTTPAdapter(max_retries=0)
_session.mount('https://', _adapter)
_session.mount('http://', _adapter)

# Grammar-enforced verdict shape (Ollama `format` JSON schema). Constrains
# `category` to the exact enum and guarantees valid JSON with all three keys.
DLP_FORMAT_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'category': {'type': 'string', 'enum': ['public', 'confidential', 'restricted']},
        'reason': {'type': 'string'},
        'spans': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['category', 'reason', 'spans'],
}

# When TLS verification is disabled, log the insecure posture exactly once so it
# is VISIBLE in the logs (rather than unconditionally muting urllib3's warning).
# The InsecureRequestWarning itself is suppressed only to avoid log spam on every
# scan — the one-time logger.warning carries the same signal. Prefer pinning the
# self-signed cert via DLP_LLM_CA_BUNDLE so verification stays on instead.
_insecure_warning_silenced = False


def _silence_insecure_warning() -> None:
    global _insecure_warning_silenced
    if _insecure_warning_silenced:
        return
    logger.warning(
        "DLP local-LLM TLS verification is DISABLED (DLP_LLM_VERIFY_SSL=false, no "
        "DLP_LLM_CA_BUNDLE) — DLP-scanned text is sent to Ollama over an "
        "unverified link (LAN MITM risk). Pin the self-signed cert via "
        "DLP_LLM_CA_BUNDLE to verify it; only acceptable on a trusted isolated link."
    )
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:  # pragma: no cover - urllib3 always present with requests
        pass
    _insecure_warning_silenced = True


def dlp_classify_content(
    messages: list[dict],
    *,
    base_url: str,
    model: str,
    timeout: int,
    verify: bool | str,
    num_ctx: int,
    num_predict: int = 768,
) -> Optional[str]:
    """Run the DLP classifier prompt against the local Ollama model.

    Returns the assistant's raw message content (a JSON string) on success, or
    ``None`` on ANY failure — connection error, timeout, non-2xx, or malformed
    body. Never raises; the caller (``DLPDetector.llm_classify``) treats ``None``
    as "skip smart-scan" and falls open to the regex pass.

    Args:
        messages: OpenAI-style ``[{role, content}, ...]`` (system + user).
        base_url: Ollama base, e.g. ``https://local-ai.example.com:9443``.
        model: Model tag, e.g. ``qwen3.6:35b``.
        timeout: Whole-request timeout in seconds (send-path latency ceiling).
        verify: TLS verification — ``False`` accepts the self-signed cert (logged
            once as insecure), ``True`` requires a system-trusted cert, or a PEM
            path (``DLP_LLM_CA_BUNDLE``) pins the self-signed cert so the link
            stays verified. Passed straight to ``requests``' ``verify=``.
        num_ctx: Per-request context window (KV cache slab).
        num_predict: Output token cap (the verdict JSON is small).
    """
    if not verify:
        _silence_insecure_warning()

    url = base_url.rstrip('/') + '/api/chat'
    body = {
        'model': model,
        'messages': messages,
        'stream': False,
        'think': False,
        'format': DLP_FORMAT_SCHEMA,
        'options': {
            'temperature': 0,
            'num_ctx': num_ctx,
            'num_predict': num_predict,
        },
    }

    try:
        resp = _session.post(url, json=body, timeout=timeout, verify=verify)
        resp.raise_for_status()
        content = resp.json()['message']['content']
        return content if isinstance(content, str) else None
    except Exception as exc:
        logger.error('DLP local-LLM call failed: %s — failing open', exc)
        return None


# ---------------------------------------------------------------------------
# General-purpose local chat (free "Local AI" model + Email Writer).
#
# Unlike dlp_classify_content, this is NOT DLP-bound: no `format` schema, and it
# supports token streaming. It emits OpenRouter-shaped chunks so every existing
# chat/studio consumer (email_writer_service, chat stream/send) works unchanged.
# ---------------------------------------------------------------------------


def local_llm_available() -> bool:
    """True when a self-hosted local (Ollama) server is configured.

    The single "is-local-configured" gate (``DLP_LLM_BASE_URL`` truthy); the DLP
    path inlines this same idiom in three places. Reused to decide whether the
    ``polymind/local-ai`` model runs on Ollama or silently falls back to the cloud.
    """
    from app.settings import settings

    return bool((settings.get('DLP_LLM_BASE_URL') or '').strip())


def stream_chat(
    messages: list[dict],
    *,
    base_url: str,
    model: str,
    timeout: int,
    verify: bool | str,
    num_ctx: int,
    num_predict: int = 4096,
    temperature: float = 0.7,
    stream: bool = True,
):
    """Run a general chat completion against the local Ollama model.

    Returns an OpenRouter-shaped result so callers don't special-case the source:
      - stream=True: a generator yielding ``{'choices':[{'delta':{'content':…}}]}``
        per token, a terminal ``{'done': True, 'annotations': []}``, and on any
        failure a single ``{'error': {'message', 'code'}}`` (mirrors
        ``OpenRouterService._stream_completion``).
      - stream=False: a dict
        ``{'choices':[{'message':{'content':…},'finish_reason':'stop'}],'usage':{},'model':…}``
        so non-stream callers read ``resp['choices'][0]['message']['content']``.

    Writes NO ``usage_logs`` — the local model is free (same contract as
    ``dlp_classify_content``). OpenRouter-only features (web search/tools/
    reasoning) have no equivalent here and are simply not sent.
    """
    if not verify:
        _silence_insecure_warning()

    url = base_url.rstrip('/') + '/api/chat'
    body = {
        'model': model,
        'messages': messages,
        'stream': bool(stream),
        'think': False,  # qwen3 is a thinking MoE — suppress <think> in drafts
        'options': {
            'temperature': temperature,
            'num_ctx': num_ctx,
            'num_predict': num_predict,
        },
    }

    if stream:
        return _stream_chat_gen(url, body, timeout, verify)
    return _chat_once(url, body, timeout, verify, model)


def _stream_chat_gen(url: str, body: dict, timeout: int, verify: bool | str) -> Iterator[dict]:
    """Yield OpenRouter-shaped stream chunks from Ollama's NDJSON /api/chat."""
    try:
        resp = _session.post(url, json=body, timeout=timeout, verify=verify, stream=True)
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                obj = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                continue
            piece = ((obj.get('message') or {}).get('content')) or ''
            if piece:
                yield {'choices': [{'delta': {'content': piece}}]}
            if obj.get('done'):
                yield {'done': True, 'annotations': []}
                return
    except Exception as exc:
        logger.error('local-LLM stream failed: %s', exc)
        yield {'error': {'message': str(exc), 'code': 500}}
        return
    # Stream ended without an explicit done flag — still signal completion.
    yield {'done': True, 'annotations': []}


def _chat_once(url: str, body: dict, timeout: int, verify: bool | str, model: str) -> dict:
    """Single-shot local chat → OpenRouter-shaped response dict (or error dict)."""
    try:
        resp = _session.post(url, json=body, timeout=timeout, verify=verify)
        resp.raise_for_status()
        content = resp.json().get('message', {}).get('content')
        content = content if isinstance(content, str) else ''
        return {
            'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}],
            'usage': {},
            'model': model,
        }
    except Exception as exc:
        logger.error('local-LLM call failed: %s', exc)
        return {'error': {'message': str(exc), 'code': 500}}

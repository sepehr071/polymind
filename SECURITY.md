# Security

## Reporting a vulnerability

Email **security@example.com** (or the maintainers) with a description, reproduction
steps, and impact. Do not open public issues for unpatched vulnerabilities.

---

## Security audit & remediation — 2026-06-10

A full security audit of the platform (FastAPI backend + React frontend +
Postgres) was performed across 12 dimensions: authentication/JWT, authorization
/IDOR, SSRF, SQL injection, DLP & billing bypass, file upload/traversal,
frontend XSS/sandbox, secrets/config/CORS, prompt injection, DoS/rate-limiting,
cryptography/tokens, and privilege escalation. Each candidate finding was
independently verified against the real code before being accepted.

**Result: 17 confirmed issues — all fixed and tested.** None were remote
unauthenticated RCE or blind full-tenant data exfiltration; the highest-impact
issues were an authenticated user stealing tokens via rendered AI output, an
authenticated denial-of-service, a cross-user persona IDOR, and cost-abuse
(denial-of-wallet) vectors.

Verification: backend test suite green (445 tests across the touched modules),
frontend production build green, application import clean.

### Confirmed defenses (already correct — not changed)

- User **role is always read from the database** at request time, never trusted
  from a JWT claim — a forged-subject token only ever yields the role the DB row
  actually holds, and Keycloak tokens (which carry no app role) cannot escalate.
- Code Canvas renders LLM-generated HTML in an iframe sandboxed `allow-scripts`
  only (never `allow-same-origin`).
- DLP "send anyway" confirm tokens are HMAC-bound with a 300s TTL; DLP and spend
  gates run in the handler **before** the SSE response, so a block is a real
  403/402, not an in-stream failure.
- Public login is Keycloak-only with self-registration removed; the login
  endpoint returns a generic error and is throttled per (IP, email).

---

## Findings & fixes

### High

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 1 | **Stored/indirect-injection XSS** — assistant markdown was rendered with `rehype-raw` and no sanitizer or CSP. | Model output (steerable via indirect prompt injection) could emit `<iframe srcdoc><script>` that runs in the app origin and steals the JWT + refresh token from `localStorage`. | Added `rehype-sanitize` after `rehype-raw` in all three render paths with a KaTeX-aware allow-list that drops `iframe`/`script`/`object`/`embed`/`style`/`srcdoc`/`on*`. Files: `frontend/src/components/chat/MarkdownRenderer.jsx`, `MarkdownMath.jsx`. *(Deferred defense-in-depth: a Content-Security-Policy header and moving tokens to httpOnly cookies.)* |
| 2 | **SSE DB-pool exhaustion DoS** — streams pinned a DB connection for life, never detected client disconnect (1800s drain join), and had no per-user concurrency cap; 50-connection pool, arena pins 3-5 per request. | One authenticated user could pin all 50 connections and take the whole app down (every DB request app-wide blocks). | `sse.py` now signals producers to stop on disconnect (opt-in `stop_event`, backward-compatible); chat/arena/debate producers break and release the connection promptly. Added a per-user concurrent-stream cap of **3** (`StreamStateModel.count_active`) → `429`. Files: `backend/app/api/sse.py`, `services/stream_state.py`, `models/stream_state.py`, `routers/chat.py`, `arena.py`, `debate.py`. |
| 3 | **IDOR on chat config** — `/chat/send` and `/chat/stream` loaded any `LLMConfig` by id with no ownership check (the gate only covered project-scoped configs). | Any user could run another user's private persona by id, exfiltrate its secret system prompt and model, and inflate the victim's usage stats. | Hardened `resolve_config` so personal configs require owner-match OR public/template visibility; threaded `user_id`/`project_id` into both chat routes (and the debate resolver). Files: `backend/app/utils/config_resolver.py`, `routers/chat.py`, `debate.py`. |

### Medium

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 4 | **Model-id allowlist bypass** — the `quick:<model>` branch returned the model id verbatim with no membership check against the curated `QUICK_MODELS` set. | Any user could route to any (premium) OpenRouter model on the shared API key — denial-of-wallet. | `resolve_config` rejects off-list quick models. This surfaced a pre-existing **frontend↔backend drift** (the default model was not in the backend list); synced `frontend/src/constants/models.js` to the 9 backend ids. Files: `config_resolver.py`, `constants/models.js`. |
| 5 | **No rate limit on paid endpoints** — only helper/DLP had limiters; chat/arena/debate/image-gen had none, and the spend gate is off by default. | Cost-amplification / request-flood abuse. | New shared per-user sliding-window limiter `app/utils/rate_limit.py`, applied independent of billing enforcement. Files: `utils/rate_limit.py`, `routers/chat.py`, `arena.py`, `debate.py`, `misc_a.py`. |
| 6 | **Production config guard never ran** — `ProductionConfig.validate()` (secret-strength ≥32, required CORS) was only reachable from dead legacy code, not the live ASGI boot. | A weak `JWT_SECRET_KEY` (which also seeds the DLP HMAC) would be silently accepted, enabling token/DLP-bypass forgery. | `asgi.py` runs the validation at import, gated strictly on `FLASK_ENV=production` (dev/test unaffected). Fixed a false "validated at boot" docstring. Files: `asgi.py`, `services/dlp_tokens.py`. |
| 7 | **DLP redaction bypass** — image-gen "redact" mode re-scrubbed only the prompt, not the negative prompt. | Secrets typed in the negative prompt were sent to the provider and persisted unredacted while logged as redacted. | The negative prompt is now re-redacted on the recovery path. File: `routers/misc_a.py`. |
| 8 | **Token-type confusion** — `resolve_user_from_token` never checked the `type` claim. | A 30-day refresh token worked as a bearer credential on the entire API, collapsing the access/refresh split. | Reject any token whose `type` is present and not `access` (Keycloak RS256 tokens carry no `type` and are unaffected). File: `api/deps.py`. |

### Low (hardening)

| # | Issue | Fix |
|---|-------|-----|
| 9 | Keycloak `/sync` logged full claims (email, subject, realm roles) at WARNING on every login. | Removed; gated behind a debug flag at DEBUG with PII dropped. File: `routers/auth.py`. |
| 10 | `GET /chat/{id}/messages` skipped the project ACL applied by sibling endpoints (forward-read after project removal). | Added `check_project_access`. File: `routers/chat.py`. |
| 11 | Password change did not revoke existing access/refresh tokens. | Stamps `settings.tokens_valid_after` (epoch, JSONB — no migration); tokens with an earlier `iat` are rejected. Files: `routers/auth.py`, `api/deps.py`. |
| 12 | DLP local-LLM (Ollama) client disabled TLS verification by default. | Added `DLP_LLM_CA_BUNDLE` to pin the self-signed cert + a one-time insecure-mode warning; default kept so the existing deployment keeps working. Files: `config.py`, `services/dlp_service.py`, `local_llm_service.py`. |
| 13 | bcrypt silently truncated passwords at 72 bytes while advertising 128 chars. | Reject >72-byte passwords at validation (not pre-hash — pre-hashing would invalidate every existing stored hash). Files: `models/user.py`, `platform_admin.py`, `routers/auth.py`. |
| 14 | Login revealed account existence via bcrypt timing. | Run a constant-time dummy bcrypt verification on the unknown-account branch. Files: `routers/auth.py`, `models/user.py`, `platform_admin.py`. |
| 15 | Automate SSRF host filter missed alternate IP encodings (decimal/octal/hex/IPv6). | Route bare hosts through `utils/network.is_internal_host` (normalizes all encodings). File: `routers/automate_agent.py`. |

---

## Rate-limit settings (per user, sliding window)

| Endpoint | Limit |
|----------|-------|
| Chat (`/send` + `/stream`) | 30 / 60s |
| Arena (`/stream`) | 12 / 60s |
| Debate (`/stream`) | 12 / 60s |
| Image generation (`/generate`) | 15 / 60s |
| Helper (`/stream`) | 30 / 60s *(pre-existing)* |
| DLP scan | 60 / 60s *(pre-existing)* |

Plus a **concurrent-stream cap of 3** per user across chat/arena/debate
(`_MAX_CONCURRENT_STREAMS`). Over any limit → `429 {error, retry_after}` with a
`Retry-After` header.

> Limiters are **in-process per gunicorn worker** — the effective ceiling is
> `limit × worker_count`. This is a cost/DoS speed-bump, not an exact global
> quota; hard budget enforcement is the spend gate's job.

---

## Deferred (tracked, not yet implemented)

- **Content-Security-Policy** header and migrating auth tokens from `localStorage`
  to httpOnly cookies (defence-in-depth behind finding #1; needs real-browser
  smoke testing).
- Enabling strict TLS verification for the DLP local-LLM link by default once a
  CA bundle is deployed (finding #12).

---

## Security hardening sweep — 2026-06-12 (shipped to prod)

Fresh multi-agent audit of code landed since the 2026-06-10 pass (data-analyzer
sandbox, chat sharing, A/V multimodal, image-studio) + closure of the deferred
items above. Branch `feat/chatgpt-parity`, suite **2269 green**, live login
verified 0 CSP violations.

**CRITICAL — fixed:**
- **Cross-tenant file exfiltration (IDOR).** Client-supplied `attachments[]` was
  resolved by `upload_id` with **no owner check** (`UploadModel.find_by_id`), so
  any authenticated user could read another user's uploaded file via chat
  inlining or the data-analyzer sandbox. Fixed at the resolver
  (`find_by_id_for_user` / `get_extracted_text_for_user`), caller `user_id`
  threaded through `_read_upload_bytes` / `_attachment_extracted_text` /
  `format_messages_for_api_ex` / `prepare_dataset`, and foreign `upload_id`s
  dropped at `/send` + `/stream` (`_filter_owned_attachments`). Also stopped
  trusting client-inlined `extracted_text` (prompt injection) and forwarding a
  client image `url` to the provider (SSRF) — images now inline owned bytes.

**HIGH — fixed:**
- **Stored XSS via ECharts tooltip formatter** — model-generated chart values
  rendered as innerHTML unescaped; now `echarts.format.encodeHTML`-escaped.
- **Data-analyzer sandbox lifecycle** — cancel now kills the bwrap child (was
  holding a global semaphore slot to timeout); per-conversation workdir GC
  (disk-exhaustion); `RLIMIT_CPU` added.
- **Share-link sender PII over-serialization** to any authenticated user; raw
  user prompts printed to centralized logs; office-XML zip-bomb parse guard.

**MED — fixed:** share endpoints rate-limited + snapshot purged on
revoke/conversation-delete (erasure gap); CSV export formula-injection
neutralized; `/docs`+`/openapi` gated off in prod; `str(exc)` removed from 5xx
responses; `/health/status` kept public+always-200 (Swarm contract) but raw
exception text scrubbed; `.env_front` gitignored.

**Deferred items above — NOW DONE:**
- **CSP** shipped: `<meta>` baked at build (SPA), strict CSP on API responses
  (prod), `frame-ancestors`/`X-Frame-Options` via nginx. `script-src
  'unsafe-inline'` retained (Code Canvas srcdoc needs it; no hash alongside).
- **httpOnly cookie migration** shipped: access/refresh in `__Host-` cookies,
  cookie-first resolution + Authorization-header fallback, `/refresh` omits body
  tokens on the cookie path, CSRF via SameSite=Lax + `X-CSRF-Token` header
  (`asgi.py CsrfMiddleware`). Tokens no longer in `localStorage`.

**Still deferred / owner-side:**
- Strict TLS verify for the DLP local-LLM link (finding #12) once a CA bundle is
  deployed.
- Rotate OpenRouter / ElevenLabs keys (exposed on disk); origin nginx
  rate-limiting (needs the CDN edge-IP CIDRs — the origin only sees the
  edge IP, so naive per-IP limits would throttle everyone); CDN `/assets/*` edge
  cache. See `docs/ops/infra-optimization-and-bugs.md` + `your deployment docs`.
- **Product call:** DLP `disabled_rules` can disable critical/block-tier rules,
  defeating the "critical→block immutable" floor (owner-gated, looks deliberate
  per commit `e6da5ec`). Re-lock or keep — owner decision.

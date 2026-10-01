# Changelog

All notable changes to this project will be documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Fixed — Keycloak org workspaces on SSO login (2026-09-29)

- `/keycloak/sync` loads organisation membership from `GET /realms/{realm}/account/organizations` with the user's access token (`KeycloakClient.account_organizations`). Realm-role mapping is unchanged. One team workspace per org. Admin API and the token `organization` claim stay fallbacks. Do not add scope `organization` (`invalid_scope` on client `ai-aggregator`). Blank `KEYCLOAK_ADMIN_*` no longer drops org companies; the live member roster still needs those creds. First 100 orgs. Next SSO login. Shipped to staging: backend overlay + `unichat-backend` restart. No alembic, no frontend rebuild.

### Changed — Home tiles and admin company switcher (2026-09-28)

- Colored hub icons (`frontend/src/assets/hub-icons/`, `hubIconFor`). Compact tile: icon, one-line title, one-line subtitle, corner chevron. No privacy chip. `ToolCard` is `w-full` so it fills the grid cell (a shrink-wrapped link was ~112px and wrapped the Persian subtitle).
- `/dashboard` backdrop is `AuroraBackground` again.
- Super-admin (`role==='admin'`) company menu in `AppTopBar` (`AdminOrgSwitcher`) lists every company. A non-member selection sticks via `WorkspaceContext` adminHold.
- Frontend-only ship to staging. `gen_hub_icons.py` is retired.

### Changed — Content Safety warn or block (2026-09-28)

- Live DLP actions are warn and block. `require_confirm` / Send anyway is gone. JWT, card, IBAN, Iran national ID, and generic API key now block. Email, phone, private IP, and high-entropy token still warn. Scrub-and-send stays. No migration. Shipped to staging 2026-09-28: backend overlay + `unichat-backend` restart, then frontend dist.

### Changed — Poe prototype shell (2026-09-26)

- Home category pills, assistant chips with icons, bordered composer cards (chat + image studio), `PageHeader` extrabold accent glyph (no IconTile), `MuiCard` hairline + soft brand shadow (none in dark). App sidebar holds chat history. `/gallery` is the image library.
- Sidebar off-canvas translate is `max-lg` only. A bare `rtl:` translate was hiding the desktop column (blank white strip). Shipped to staging.
- Prototype leftovers intentionally not copied: backdrop-blur, `rounded-3xl`, `/files`, mic, fake per-message credit, Ctrl/⌘K, Polymind wordmark, avatars on chat turns.

### Changed — Product chrome, ERP palette, Chat image-gen (2026-09-19)

- **Personal settings tabs:** `profile | preferences | ai | usage` (Security tab hidden; `SecuritySection.jsx` kept). Preferences = two-column `PrefRow` (40×240 controls); language + timezone share Select RTL chevron; numerals + theme share segmented control. Settings tab row: close in-row, `overflow-x-auto overflow-y-hidden` (no dual scrollbars).
- **Team chrome hidden:** `TEAMS_UI_VISIBLE=false` (`frontend/src/constants/productFlags.js`) hides `ScopePillBar` + UserMenu Teams. `/projects` + ProjectContext stay. Flip the flag to restore.
- **Chat image-gen:** identity prompt redirects to Image Studio and STOPs — no attachment analysis.
- **Usage + Helper names:** `originLabel` + `helper_features.NAME_FA` use FA glossary (`نویسنده ایمیل / نامه`, not “Email Writer”).
- **Email-writer privacy badge:** hub and page share `displayPrivacyForPath` + `/api/models/local-status`. Ollama configured → local; blank `DLP_LLM_BASE_URL` → cloud (staging currently cloud).
- **Palette:** ERP tokens (`erp-mui-theme.md`) in `tokens.js` / `index.css`. AppTopBar `h-14`, header cells vertically centered.

### Fixed / Changed — Research, email UX, light glass (2026-07-21)

- **Deep research models:** dropped Perplexity allowlist. Defaults: `deep`/`deep_files` → `openai/o4-mini-deep-research` (32k max tokens, files OK), `premium` → `openai/o3-deep-research` (64k), `quick` → Gemini Flash Lite + `web_search`. **Never send `temperature`** to `*-deep-research` (OpenAI 400 — stripped in `openrouter_service.chat_completion`).
- **Research UX:** SSE progress phases + keepalives (15s) while non-stream OR call runs; activity checklist + elapsed timer; failed state (not green “done”); raise on OR `{error}` / empty report; FE idle 600s.
- **Email writer UX:** template cards, sectioned form (To/Body/From), sticky generate + preview, en/fa hints.
- **Light glass contrast:** higher light `--glass-bg-opacity` / strong, slate rim; opaque Input/Textarea; strong glass on Card/Section/AppTopBar; placeholder no 0.6 fade.
- Redeployed prod after temperature fix.

### Added — Tier A studio assistants (2026-07-21)

Iran-company studio tools (FA-first, DLP + spend before SSE, shared `studioStream.js` / `studio_dlp` scan-text contract). Master plan: `docs/superpowers/plans/2026-07-21-tier-a-assistants/`. Deployed prod 2026-07-21 (alembic head `0023`).

| Tool | Route | Flag | DLP / spend |
|------|-------|------|-------------|
| Email / letter writer | `/email-writer` | `email_writer` ON | `email_writer` |
| CV checker | `/cv-checker` | `cv_checker` ON | `cv_checker` |
| Deep research | `/research` | `research_assistant` ON | `research` |
| Contract reviewer | `/contracts` | `contract_reviewer` OFF | `contract` |
| Tender / RFQ | `/tenders` | `tender_assistant` OFF | `tender` |
| Meeting action pack | `/meetings/:id` | existing `meetings` | DLP `meeting` · spend `meeting_action_pack` |

- **Migrations:** `0022_dlp_tier_a_sources` (DLP CHECK + sources), `0023_meeting_summary_memo` (`meeting_summaries.memo`).
- **Backend:** routers `email_writer`, `cv_checker`, `research`, `contracts`, `tenders`; services + prompts per tool; `utils/studio_dlp.py` (FE/BE confirm_token text parity); meetings `POST /{id}/action-pack`.
- **Frontend:** hub studio cards, FeatureGates, en/fa i18n namespaces; research idle timeout 600s; OpenAI deep-research defaults (see Fixed above).
- **Product rules:** contracts/tenders not legal advice; CV human final decision + anti-bias; tenders Rial/Toman; email copy-only (no SMTP).
- Smoke: `docs/deploy/tier-a-assistants-smoke.md`.

### Added — OCR assistant (`/ocr`)

- Hub extract for images/PDFs; flag `ocr_assistant` ON; DLP source `ocr` (mig `0021`); SSE via Gemini Flash Lite.
- Spec: `docs/superpowers/specs/2026-07-21-ocr-assistant-design.md`.

### Added — All-in-one Agent (`/agent`)

- Hybrid orchestrator surface: fixed model (`AGENT_ORCHESTRATOR_MODEL`, default `google/gemini-3.5-flash`), feature flag `agent` (default ON).
- Tools: `ask_user` (blocking clarify + resume), `generate_image`, `run_python` (only when data files present), OpenRouter `web_search` / `web_fetch`; optional `openrouter:subagent` (`AGENT_SUBAGENT=1`).
- Backend: `api/routers/agent.py`, `services/agent_service.py`, `prompts/agent_orchestrator.py`; mig `0020_agent_kind_dlp` (`conversations.kind='agent'`, DLP source `agent`).
- Frontend: `pages/agent/`, `agentService.js`, hub nav card, en/fa `agent` i18n.
- OpenRouter transport retries on proxy/connection blips; clearer Persian errors when egress fails.
- Spec: `docs/superpowers/specs/2026-07-18-all-in-one-agent-design.md`.

## [3.1.0] — 2026-04-27

### Added — Native Telegram streaming

- **`sendMessageDraft`** (Bot API 9.3+, opened to all bots in 9.5): replaces the edit-message loop. Telegram clients now render bot replies with the native streaming animation while tokens arrive; the final assistant message lands as a real persisted message via `send_full()` (splits at 4000 chars to stay under the 4096 cap).
- Bumped `aiogram>=3.27,<4` (`Bot.send_message_draft` shipped in 3.27.0).
- `bot/services/stream.py` rewritten around `stream_to_tg_draft()` + `send_full()`. New behaviour: tighter cadence (80 chars or 0.6s, no per-message edit-rate concerns), stable random `draft_id` for animated transitions, no placeholder message before streaming.
- 5 new stream tests; full bot suite at 15/15.

### Fixed — Bot runtime

- **"Popped wrong app context"**: `bot/services/chat.py:call_openrouter_stream` no longer wraps its `yield` loop in `with flask_app.app_context()`. The lexical context push survived across yields and collided with the handler's per-chunk push when the LIFO context stack was popped from a different worker thread. Caller (`handlers/chat.py:_next`) now owns app_context exclusively.
- **`<ContextVar 'flask.app_ctx'>` leak in error reply**: `loop.run_in_executor` doesn't propagate contextvars to worker threads in our setup, so `current_app.config` reads inside `OpenRouterService.get_headers()` raised raw `ContextVar` reprs that leaked to users. Handler's `_next()` now pushes `flask_app.app_context()` per chunk, so the first `requests.post(headers=get_headers())` runs under context.
- **Error replies with `parse_mode=HTML` rejected by Telegram** when the exception text contained HTML-like fragments (e.g. `<ContextVar...>` repr). Switched error replies to `parse_mode=None` so any exception text is delivered safely.

### Changed

- `frontend/package.json` → 3.1.0.

---

## [3.0.0] — 2026-04-27

### Added — Telegram Bot Gateway

Linked uni-chat users can now chat with the platform from inside Telegram (text only, v1).

- **New `bot/` service** — separate `aiogram v3` process that reuses backend models/services via `pip install -e ../backend`, sharing MongoDB and OpenRouter. Polling in dev (`POLLING=1`), webhook in prod.
- **Linking flow** — Settings → Telegram tab → "Link Telegram" mints a one-time token (10-min TTL), opens `t.me/<TELEGRAM_BOT_USERNAME>?start=<token>`, bot consumes and binds `users.telegram_id` (unique sparse index).
- **Slash commands** — `/start`, `/new`, `/model`, `/assistant`, `/history`, `/unlink`, `/help`. Inline keyboards for model and assistant pickers (5 quick models + up to 10 saved assistants).
- **Streaming** — adaptive edit-in-place into the Telegram message (buffer ≥80 chars OR ≥1.2s since last edit). Markdown → Telegram-HTML allowlist (`<b><i><code><pre><a><blockquote>`). Splits at 4000 chars to stay under Telegram's 4096 cap.
- **Rate limit** — sliding window persisted on `users.telegram_rate_limit` (20 msg/60s, bypassed for `ADMIN_EMAIL`).
- **State** — `telegram_active_conversation_id`, `telegram_active_config_id`, `telegram_rate_limit`. Telegram chats are real `conversations` with `title='Telegram chat'`, visible immediately in the web app.

### Added — Backend

- `backend/app/models/telegram_link_token.py` — `TelegramLinkTokenModel` with TTL index on `expires_at` and atomic find-and-delete consume.
- `backend/app/routes/telegram_link.py` — `/api/users/telegram/{status,generate-token,unlink}`.
- `UserModel.find_by_telegram_id` / `set_telegram_link` / `clear_telegram_link` + unique sparse index on `telegram_id`.
- `backend/pyproject.toml` so the bot venv can `pip install -e ../backend`.
- **JWT diagnostic loaders** — `expired/invalid/missing/revoked` token callbacks log structured lines and return JSON `{error, code, detail?}`. Frontend interceptor only checks status, so the response shape is forward-compatible.
- **JWT secret key length** — placeholders in `.env.example` are now ≥32 bytes (RFC 7518 / PyJWT 2.10+ `InsecureKeyLengthWarning`).

### Added — Frontend

- `frontend/src/services/telegramService.js` — REST client for the link endpoints.
- `frontend/src/pages/dashboard/components/TelegramLinkPanel.jsx` — status panel, "Link Telegram" button, post-link polling, unlink action.
- New **Telegram** tab in `SettingsPage.jsx`.

### Added — Deploy

- `deploy/unichat-bot.service` — systemd unit for the bot.
- `deploy/nginx-telegram.conf` — webhook proxy snippet to merge into the existing API server block.
- `.github/workflows/deploy-bot.yml` — auto-deploy on push to `main` when `bot/**` or `backend/**` changes.

### Changed

- `CLAUDE.md` — top-level "Run (3 terminals)" section, bot architecture and feature notes, dev MongoDB path (`D:\MongoDB\data`) and recovery hint, two new Known Issues entries (bot dotenv ordering, `setuptools<81` for `mongomock`).
- Domain references replaced with `your-domain.example` placeholders in `frontend/vercel.json`, `bot/.env.example`, `bot/README.md`, `deploy/nginx-telegram.conf`. Update before redeploying.

### Fixed

- **Bot 401 from OpenRouter** — backend's `Config` class evaluates `os.environ` at class-definition time. Loading `bot/.env` from `bot/flask_ctx.py` was too late: handlers' `from app.models...` imports already ran the Config class with empty values, locking `OPENROUTER_API_KEY=''`. Moved `load_dotenv(override=True)` into `bot/bot/__init__.py` so it runs before any `app.*` import.
- **Silent bot failures** — chat handler now propagates OpenRouter error chunks to the user (`Error: <code>: <message>`) and edits the placeholder with "empty response from model" if the stream yields nothing, instead of leaving a stuck "…".

### Breaking

- `MONGO_URI` must include the database name before query params (e.g. `mongodb+srv://.../unichat?retryWrites=true&w=majority`). Missing DB name yields `'NoneType' object is not subscriptable`. Documented in Known Issues.
- The previous `sepijan.xyz` domain is no longer owned. Production deploys require updating placeholder URLs in `vercel.json`, bot env, nginx snippet, and webhook URL before redeploy.

### Database

New collection: `telegram_link_tokens` (TTL on `expires_at`).
New fields on `users`: `telegram_id`, `telegram_username`, `telegram_linked_at`, `telegram_active_conversation_id`, `telegram_active_config_id`, `telegram_rate_limit`.

---

## [2.8.0] and earlier

See `git log v2.8.0` for prior history (workflow editor overhaul, automate agent via browser-use Cloud, knowledge vault, debate mode, code canvas, image generation, etc.).

# Product

## Register

product

## Users

Employees of an Iranian corporate holding: CEO and holding admins, company managers, and team members. Persian-first (RTL, Vazirmatn, Shamsi dates, optional Persian numerals), English secondary. They work in chat all day: drafting, asking, generating images, running workflows, transcribing meetings. Context is the office desktop browser, sometimes a phone. Iran air-gap constraints: no external CDNs, everything bundled.

## Product Purpose

Polymind AI is the company's single gateway to many AI models (via OpenRouter): chat, the all-in-one Agent (routes to image/data/tools and clarifies when stuck), model comparison (`/arena`), debate, image studio, workflow automation, knowledge vault, meeting transcription, image text reader (OCR), and **Tier A studio assistants** (formal email/letter drafts, CV screen/improve, deep research with citations, contract risk review, tender/RFQ compliance packs, meeting action pack). It replaces scattered AI subscriptions with one governed workspace: budgets, DLP content safety, role hierarchy (holding → company → team). Success: people reach for it first for any AI task, and admins trust the spend and safety controls.

### Studio assistants (Tier A, 2026-07-21)

| Surface | Flag | Notes |
|---|---|---|
| Email / letter writer `/email-writer` | `email_writer` (ON) | Formal FA/EN drafts; copy only — no SMTP |
| CV checker `/cv-checker` | `cv_checker` (ON) | HR screen or improve; anti-bias; human decides |
| Deep research `/research` | `research_assistant` (ON) | UI: پژوهش عمیق. OpenAI `o4-mini-deep-research` (default) / `o3-deep-research` (premium); quick = Gemini + web; 600s; activity SSE; citations; no `temperature` on deep models |
| Contract reviewer `/contracts` | `contract_reviewer` (OFF until pilot) | Risk matrix; **not legal advice** |
| Tender / RFQ `/tenders` | `tender_assistant` (OFF until pilot) | Compliance matrix + FA cover letter; Rial/Toman |
| Meeting action pack | existing `meetings` | On done meetings: actions, decisions, FA email, memo |

## Brand Personality

Friendly, warm, approachable. An assistant that feels like a helpful colleague, not a sterile enterprise console. Soft glass surfaces, generous spacing, gentle motion. Confidence without coldness; Persian copy is conversational (چت, راهنما), never bureaucratic.

## Anti-references

- Generic SaaS dashboard: gradient hero metrics, identical icon-card grids, purple-on-white template feel.
- Anything that reads "AI-generated template" at first glance.

## Design Principles

- Chat is home: the conversation surface and history always come first; admin and analytics serve it, never crowd it.
- Warm minimalism: few elements, soft contrast, glass used on chrome only, color used to welcome rather than alert.
- Persian-first craft: RTL layouts, logical CSS properties, localized digits and dates are first-class, not retrofits.
- One pattern everywhere: shared primitives (ui/*, charts, dialogs) over bespoke one-offs; reuse before invention.
- Quiet power for admins: dense data lives behind progressive disclosure, owner-only cost details, friendly empty states.
- Settings honesty (2026-07-14): copy matches real powers (Polymind admin funds company credits; company membership ≠ team access; SSO users do not see a dead password form). Destructive member actions confirm. Denied settings toast to hub, never a silent bounce. Manager company setup is a short checklist; team advanced tabs and DLP/billing detail stay folded until needed. User-facing hierarchy is **Company → Team** only (DB may still say workspace/project).

## Accessibility & Inclusion

WCAG AA: 4.5:1 body-text contrast, visible focus rings, full keyboard reach. Reduced motion respected app-wide (CSS keyframe freeze + framer guards already wired). Reduced transparency softens glass blur. Color never the sole signal; lucide icons plus text labels.

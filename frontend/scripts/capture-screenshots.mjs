// Captures the README screenshots from the real SPA with a mocked /api.
// No backend needed: every /api call is answered with synthetic demo data
// (fictional "Acme Research" workspace, user "Alice Moradi").
//
// Usage (from frontend/):
//   pnpm dev --host 127.0.0.1 --port 4150        # in another terminal
//   node scripts/capture-screenshots.mjs          # writes ../docs/images/*.png
// Env: BASE_URL (default http://127.0.0.1:4150), PW_CHANNEL (default "chrome";
// set to "" to use Playwright's bundled Chromium).
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = process.env.BASE_URL || 'http://127.0.0.1:4150'
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/images')
const CHANNEL = process.env.PW_CHANNEL ?? 'chrome'

// ---------------------------------------------------------------- demo data
const now = Date.now()
const iso = (h) => new Date(now - h * 3600e3).toISOString()

const FEATURES = Object.fromEntries(['agent', 'arena', 'automate_agent', 'contract_reviewer', 'cv_checker', 'data_analyzer', 'debate', 'email_writer', 'image_studio', 'knowledge', 'meetings', 'ocr_assistant', 'payroll', 'presentations', 'research_assistant', 'shop_assistant', 'tender_assistant', 'workflow'].map((k) => [k, true]))
const USER = {
  id: 'u_alice', _id: 'u_alice', email: 'alice@acme.example', role: 'admin',
  profile: { display_name: 'Alice Moradi', avatar_url: null, bio: '' },
  settings: { onboarding_seen_at: '2026-01-01T00:00:00Z' },
  usage: { messages_sent: 412, tokens_used: 1830000, tokens_limit: 5000000 },
  created_at: '2026-01-01T00:00:00Z', features: FEATURES, sso: false,
}
const WS = { _id: 'ws1', id: 'ws1', name: 'Acme Research', type: 'team', role: 'owner', member_count: 6 }

const CONVS = [
  ['c1', 'Q3 churn analysis: cohort breakdown', 0.3, true],
  ['c2', 'Compare pricing page copy variants', 1.2],
  ['c3', 'مقایسه قرارداد تأمین‌کننده با نسخه قبلی', 3],
  ['c4', 'Postgres index strategy for audit logs', 5],
  ['c5', 'Draft onboarding email sequence', 26],
  ['c6', 'Summarize vendor security questionnaire', 30],
  ['c7', 'خلاصه جلسه برنامه‌ریزی فصل پاییز', 50],
  ['c8', 'Kubernetes rollout checklist', 80],
  ['c9', 'Explain RAG chunking trade-offs', 120],
].map(([id, title, h, pin]) => ({ _id: id, id, title, created_at: iso(h), updated_at: iso(h), last_message_at: iso(h), is_pinned: !!pin, message_count: 6 }))

const CHAT = [
  { role: 'user', content: 'We have churn by signup cohort for Q3. Which cohort should we focus on, and what would you test first?' },
  { role: 'assistant', model: 'anthropic/claude-opus-5', content: `The **June signup cohort** stands out: its week-4 retention drops to 41%, while May and July hold above 55%.

### What likely changed
| Cohort | Week 1 | Week 4 | Onboarding |
|---|---|---|---|
| May | 82% | 58% | Guided |
| June | 79% | 41% | Self-serve |
| July | 84% | 56% | Guided |

The dip lines up with the self-serve onboarding experiment, so test that first.

### Next steps
1. Re-run the guided flow for a 10% holdout of new signups.
2. Track *time to first workflow* as the leading metric.

\`\`\`sql
SELECT cohort_month,
       AVG(active_w4::int) AS w4_retention
FROM   signups
GROUP  BY cohort_month;
\`\`\`` },
].map((m, i) => ({ _id: 'm' + i, conversation_id: 'c1', role: m.role, content: m.content, created_at: iso(0.3), model_id: m.model, metadata: m.model ? { model_id: m.model } : {} }))

const ARENA_PROMPT = 'Explain vector databases to a product manager in 3 bullet points.'
const ARENA = {
  'quick:anthropic/claude-opus-5': `- **What it stores:** text, images or tickets turned into *embeddings*, lists of numbers that capture meaning.
- **What it does:** finds the items closest in meaning to a query, even when no keywords match.
- **Why you care:** it powers semantic search and RAG, so an assistant can answer from *your* documents.`,
  'quick:openai/gpt-5.6-sol': `- A vector database indexes **meaning**, not words: "refund policy" finds "money-back guarantee".
- It answers "what is most similar to this?" in milliseconds across millions of items.
- Typical uses: support search, recommendations, and grounding chatbots in company knowledge.`,
  'quick:google/gemini-3.6-flash': `- Think of it as **search by similarity**: every item gets a coordinate in "meaning space".
- Queries return the nearest neighbours, ranked by how close they are.
- Trade-off to know: great recall for fuzzy questions, but you still need filters for exact facts like prices or dates.`,
}

const DEBATE_TOPIC = 'Should a 10-person startup self-host its LLMs?'
const DEBATERS = ['quick:anthropic/claude-opus-5', 'quick:openai/gpt-5.6-sol', 'quick:deepseek/deepseek-v4-flash-0731']
const DEBATE = [
  {
    'quick:anthropic/claude-opus-5': 'Not yet. With ten people, engineering time is the scarcest resource. A hosted API gives frontier quality on day one, and a DLP gateway in front of it covers most data-exposure concerns without running GPUs.',
    'quick:openai/gpt-5.6-sol': 'Partly. Keep frontier models hosted, but self-host one small open model for the sensitive path (contracts, HR, customer PII). It is cheap on a single GPU and removes the hardest compliance question.',
    'quick:deepseek/deepseek-v4-flash-0731': 'Yes, if data is the product. Open-weight models are close enough for most internal tasks, and owning the stack avoids per-token costs that grow with usage.',
  },
  {
    'quick:anthropic/claude-opus-5': 'I accept the hybrid point. A local classifier or small model for sensitive text is a reasonable exception, as long as the team does not end up maintaining a full inference platform.',
    'quick:openai/gpt-5.6-sol': 'Agreed on scope: one model, one box, one use case. Everything else goes through the hosted gateway with budgets and audit logs.',
    'quick:deepseek/deepseek-v4-flash-0731': 'Fair. Cost only wins at scale; at ten people the hybrid setup captures the privacy benefit without the ops burden. I concede.',
  },
]
const VERDICT = `### Verdict: hybrid, hosted by default

All three debaters converged on the same position by round 2:

1. **Use hosted frontier models** for general work, behind a gateway with budgets, audit logs and DLP scanning.
2. **Self-host one small model** only for the sensitive path, such as classifying or redacting confidential text.
3. **Revisit** full self-hosting once usage volume makes per-token pricing the dominant cost.

The strongest argument was engineering time: at ten people, operating inference infrastructure costs more than the tokens it saves.`

const DLP_TEXT = 'Can you debug this? Our prod key is sk-ant-api03-DEMO0000000000000000FAKE and the card on file is 4111 1111 1111 1111'
const DLP_SCAN = {
  result: {
    highest_action: 'block',
    matches: [
      { rule_id: 'anthropic_api_key', rule_name: 'Anthropic API key', severity: 'critical', action: 'block', source: 'builtin', snippet: 'sk-ant-api03-DE…FAKE' },
      { rule_id: 'credit_card', rule_name: 'Credit card number', severity: 'high', action: 'block', source: 'builtin', snippet: '4111 •••• •••• 1111' },
    ],
  },
  redacted_preview: 'Can you debug this? Our prod key is [REDACTED:API_KEY] and the card on file is [REDACTED:CARD]',
  redactable: true,
}

// "30-Second Product Ad" from backend/scripts/seed.py (workflow templates).
const TEMPLATE = {
  _id: 'tpl22', name: '30-Second Product Ad',
  description: 'Generate a complete 30-second product ad: brief -> script -> hero image -> voiceover + video clip with native audio.',
  nodes: [
    { id: 'brief-15', type: 'textInput', position: { x: 50, y: 300 }, data: { label: 'Product Brief', text: 'Sparkling water brand Zest launching a new mango-chili flavor. Target audience: Gen Z. Tone: bold, playful, energetic.', placeholder: 'Describe your product, target audience, and tone...' } },
    { id: 'scriptwriter-15', type: 'aiAgent', position: { x: 400, y: 300 }, data: { label: 'Scriptwriter', model: 'google/gemini-2.5-flash-lite', systemPrompt: 'You are an ad copywriter. Given the product brief, write a ~60-word 30-second voiceover script. Output ONLY the voiceover text.', user_prompt_template: '{{input}}', output: null } },
    { id: 'visual-prompt-15', type: 'aiAgent', position: { x: 750, y: 150 }, data: { label: 'Visual Prompt', model: 'google/gemini-2.5-flash-lite', systemPrompt: 'You are an art director. Write ONE detailed visual prompt for a hero-shot image. Under 40 words.', user_prompt_template: '{{input}}', output: null } },
    { id: 'voiceover-15', type: 'ttsNode', position: { x: 750, y: 500 }, data: { label: 'Voiceover', model: 'openai/gpt-4o-mini-tts-2025-12-15', voice: 'alloy', speed: 1.0, text: '', audioDataUri: null } },
    { id: 'keyframe-15', type: 'imageGen', position: { x: 1100, y: 150 }, data: { label: 'Keyframe', model: 'google/gemini-2.5-flash-image', prompt: '', negativePrompt: 'blurry, low quality, text, watermark', generatedImage: null } },
    { id: 'ad-clip-15', type: 'videoGenNode', position: { x: 1450, y: 300 }, data: { label: 'Ad Clip', model: 'google/veo-3.1', prompt: '', duration: 8, resolution: '1080p', aspect_ratio: '16:9', generate_audio: true, videoUrl: null } },
  ],
  edges: [
    { id: 'e1', source: 'brief-15', target: 'scriptwriter-15', sourceHandle: 'output', targetHandle: 'input-0' },
    { id: 'e2', source: 'scriptwriter-15', target: 'visual-prompt-15', sourceHandle: 'output', targetHandle: 'input-0' },
    { id: 'e3', source: 'scriptwriter-15', target: 'voiceover-15', sourceHandle: 'output', targetHandle: 'input-0' },
    { id: 'e4', source: 'visual-prompt-15', target: 'keyframe-15', sourceHandle: 'output', targetHandle: 'input-0' },
    { id: 'e5', source: 'keyframe-15', target: 'ad-clip-15', sourceHandle: 'output', targetHandle: 'frame_image' },
    { id: 'e6', source: 'visual-prompt-15', target: 'ad-clip-15', sourceHandle: 'output', targetHandle: 'prompt_text' },
  ],
}

// ---------------------------------------------------------------- SSE helpers
const sse = (events) => events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join('')

function arenaStream(configIds) {
  const ev = [['arena_session_created', { session: { _id: 'as1' } }], ['arena_user_message', { message: { content: ARENA_PROMPT } }]]
  for (const id of configIds) {
    ev.push(['arena_message_start', { config_id: id }])
    ev.push(['arena_message_complete', { config_id: id, content: ARENA[id] || ARENA['quick:anthropic/claude-opus-5'] }])
  }
  return sse(ev)
}

function debateStream() {
  const ev = [['debate_session_started', { is_infinite: false }]]
  DEBATE.forEach((round, i) => {
    ev.push(['debate_round_start', { round: i + 1 }])
    for (const id of DEBATERS) {
      ev.push(['debate_message_start', { round: i + 1, config_id: id }])
      ev.push(['debate_message_complete', { round: i + 1, config_id: id, content: round[id] }])
    }
    ev.push(['debate_round_complete', { round: i + 1, concluded_count: 0, total_debaters: 3 }])
  })
  ev.push(['debate_judge_start', {}], ['debate_judge_complete', { verdict: VERDICT }], ['debate_session_complete', {}])
  return sse(ev)
}

// ---------------------------------------------------------------- routing
function apiResponse(p, url, method, body, opts) {
  if (p === '/auth/me') return USER
  if (p === '/workspaces/list') return [WS]
  if (p === '/projects/list') return []
  if (p === '/conversations') return { conversations: url.searchParams.get('kind') === 'chat' ? CONVS : [], page: 1, has_more: false }
  if (p === '/conversations/c1') return { conversation: { ...CONVS[0], share: { is_shared: false } }, messages: CHAT, active_branch: 'main' }
  if (p === '/configs') return { configs: [] }
  if (p.startsWith('/usage/me')) return { total_cost: 3.42, total_requests: 128, data: [{ key: 'chat', count: 96 }, { key: 'arena', count: 21 }, { key: 'debate', count: 11 }], items: [], groups: [] }
  if (p.startsWith('/models/catalog')) return { data: [] }
  if (p === '/dlp/scan') return opts.dlp ? DLP_SCAN : { result: { highest_action: 'allow', matches: [] } }
  if (p === '/debate/sessions' && method === 'POST') return { session: { _id: 'ds1', topic: DEBATE_TOPIC } }
  if (p === '/workflow/templates') return { templates: [TEMPLATE] }
  if (p === '/workflow/list') return { workflows: [] }
  return {}
}

async function newPage(browser, { scheme = 'dark', lang = 'en', width = 1440, height = 900, dlp = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, colorScheme: scheme })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.error('  page error:', e.message.split('\n')[0]))
  await page.addInitScript(({ scheme, lang }) => {
    localStorage.setItem('auth_present', '1')
    localStorage.setItem('active_workspace_id', 'ws1')
    localStorage.setItem('unichat-theme', scheme)
    localStorage.setItem('unichat-language', lang)
  }, { scheme, lang })
  await page.route('**/api/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const p = url.pathname.replace(/^\/api/, '')
    if (p === '/arena/stream') {
      const ids = JSON.parse(req.postData() || '{}').config_ids || []
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: arenaStream(ids) })
    }
    if (p === '/debate/stream') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: debateStream() })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(apiResponse(p, url, req.method(), req.postData(), { dlp })) })
  })
  return page
}

async function open(page, route) {
  await page.goto(BASE + route, { waitUntil: 'load', timeout: 90000 })
  // Hide transient toasts so they don't end up in the stills.
  await page.addStyleTag({ content: '[data-rht-toaster]{display:none!important}' })
  await page.waitForTimeout(4000)
}

// Close the cloud-AI notice and scroll the thread back to the first message.
async function showThreadTop(page) {
  await page.getByRole('button', { name: 'Dismiss' }).first().click().catch(() => {})
  await page.waitForTimeout(500)
  await page.evaluate(() => document.querySelectorAll('*').forEach((el) => { if (el.scrollTop > 0) el.scrollTop = 0 }))
}

async function shot(page, name) {
  await page.waitForTimeout(800)
  await page.screenshot({ path: path.join(OUT, name) })
  console.log('saved', name)
  await page.context().close()
}

// ---------------------------------------------------------------- scenes
const scenes = {
  async arena(browser) {
    const page = await newPage(browser)
    await open(page, '/arena')
    await page.getByRole('button', { name: 'Select Configs' }).first().click()
    for (const m of ['Claude Opus 5', 'GPT-5.6 Sol', 'Gemini 3.6 Flash']) {
      await page.getByRole('dialog').getByRole('button', { name: m }).click()
    }
    await page.getByRole('button', { name: /Start comparison/ }).click()
    await page.getByPlaceholder(/.+/).last().fill(ARENA_PROMPT)
    await page.keyboard.press('Enter')
    await page.waitForTimeout(1500)
    await shot(page, 'arena-compare.png')
  },

  async chat(browser) {
    const page = await newPage(browser)
    await open(page, '/chat/c1')
    await showThreadTop(page)
    await shot(page, 'chat-conversation.png')
  },

  async debate(browser) {
    const page = await newPage(browser)
    await open(page, '/debate')
    await page.getByPlaceholder('Enter a topic for the AI debate...').fill(DEBATE_TOPIC)
    const quick = page.locator('button', { hasText: /^(Claude Opus 5|GPT-5\.6 Sol|DeepSeek V4 Flash 0731)$/ })
    for (const m of ['Claude Opus 5', 'GPT-5.6 Sol', 'DeepSeek V4 Flash 0731']) await quick.filter({ hasText: m }).first().click()
    await page.locator('button', { hasText: /^Gemini 3\.6 Flash$/ }).last().click()
    await page.getByRole('button', { name: '2', exact: true }).click()
    await page.getByRole('button', { name: 'Start Debate' }).click()
    await page.waitForTimeout(2500)
    await page.getByText('Round 2 of 2').scrollIntoViewIfNeeded()
    await page.evaluate(() => document.querySelectorAll('h3').forEach((h) => h.textContent.startsWith('Verdict') && h.scrollIntoView({ block: 'center' })))
    // Back off a little so the sticky header + cloud-AI notice don't cover the debater names.
    await page.evaluate(() => document.querySelectorAll('*').forEach((el) => { if (el.scrollTop > 0) el.scrollTop -= 70 }))
    await shot(page, 'debate-verdict.png')
  },

  async workflow(browser) {
    const page = await newPage(browser)
    await open(page, '/workflow')
    await page.getByRole('button', { name: 'Browse templates' }).click()
    await page.getByText('30-Second Product Ad').first().click()
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: 'Dismiss hint' }).click().catch(() => {})
    await shot(page, 'workflow-canvas.png')
  },

  async dlp(browser) {
    const page = await newPage(browser, { scheme: 'light', dlp: true })
    await open(page, '/chat')
    await page.getByPlaceholder('Type a message...').fill(DLP_TEXT)
    await page.keyboard.press('Enter')
    await page.getByText("We can't send this one").waitFor()
    await shot(page, 'dlp-block.png')
  },

  async persian(browser) {
    const page = await newPage(browser, { scheme: 'light', lang: 'fa' })
    await open(page, '/dashboard')
    await shot(page, 'persian-rtl-home.png')
  },

  async mobile(browser) {
    const page = await newPage(browser, { width: 390, height: 844 })
    await open(page, '/chat/c1')
    await showThreadTop(page)
    await shot(page, 'mobile-chat.png')
  },
}

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch(CHANNEL ? { channel: CHANNEL } : {})
const only = process.argv.slice(2)
for (const [name, run] of Object.entries(scenes)) {
  if (only.length && !only.includes(name)) continue
  try { await run(browser) } catch (e) { console.error('FAILED', name, e.message.split('\n')[0]) }
}
await browser.close()

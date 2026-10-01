/**
 * citations.js — resolve OpenRouter / Vertex grounding url_citation annotations
 * into clean, displayable source descriptors.
 *
 * OpenRouter puts the retrieved page in `url_citation.url` and the page title
 * in `title`. `content` is an excerpt and is not a list of sources.
 * Vertex grounding rewrites `url` into an opaque redirect
 * (vertexaisearch.cloud.google.com / *.googleusercontent.com). The real
 * domain is in `title`. Use that. Never surface the redirect host, and never
 * take a link out of the excerpt.
 */

/** Grounding redirect hosts whose hostname must NOT be shown to users. */
export const REDIRECT_HOSTS = new Set([
  'vertexaisearch.cloud.google.com',
  'googleusercontent.com',
])

const DOMAIN_RE = /^[a-z0-9.-]+\.[a-z]{2,}$/i
const HTTP_URL_RE = /https?:\/\/[^\s)\]>'"<]+/i

/** True when `host` is a known grounding-redirect host (incl. subdomains). */
export function isRedirectHost(host) {
  if (!host) return false
  if (REDIRECT_HOSTS.has(host)) return true
  return host.endsWith('.googleusercontent.com')
    || host.endsWith('.vertexaisearch.cloud.google.com')
    || host.includes('vertexaisearch.cloud.google.com')
}

export function hostnameOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

export function isGroundingRedirectUrl(url) {
  const host = hostnameOf(url)
  return !!host && isRedirectHost(host)
}

function stripUrlTrail(url) {
  return String(url || '').replace(/[.,;:)}\]"']+$/g, '')
}

function extractHttpUrl(text) {
  if (!text) return ''
  const m = String(text).match(HTTP_URL_RE)
  return m ? stripUrlTrail(m[0]) : ''
}

/**
 * Resolve a single `url_citation` object into a display descriptor.
 *
 * OpenRouter's chat-completions schema (docs: Web Search → Parsing web search
 * results) puts the source that was actually retrieved in `url`. `title` is the
 * page title. `content` is an excerpt and often contains OTHER links — those
 * are not the citation. Replacing `url` with a URL mined from the excerpt
 * showed unrelated hosts (including this app) as sources.
 *
 * Gemini grounding stores an opaque vertexaisearch redirect in `url` and the
 * real site in `title` (often a bare domain). Use that domain. Never mine
 * `content` — excerpts contain unrelated links, including this app.
 *
 * @param {{ url?: string, title?: string, content?: string, snippet?: string }} c
 * @returns {{ href: string, domain: string, title: string, snippet: string, isRedirect: boolean }}
 */
export function resolveCitation(c) {
  const src = c || {}
  const rawTitle = String(src.title || '').trim()
  const snippet = String(src.content || src.snippet || '').trim()
  let href = stripUrlTrail((src.url || '').trim())
  let host = hostnameOf(href)
  const redirect = !!host && isRedirectHost(host)
  const realHttp = !!href && /^https?:\/\//i.test(href) && !redirect

  if (!realHttp) {
    const fromTitle = extractHttpUrl(rawTitle)
    if (fromTitle && !isGroundingRedirectUrl(fromTitle)) {
      href = fromTitle
      host = hostnameOf(href)
    } else if (DOMAIN_RE.test(rawTitle)) {
      // Vertex: title is the source domain, url is only the redirect wrapper.
      host = rawTitle.toLowerCase().replace(/^www\./, '')
      href = `https://${host}`
    } else {
      return { href: '', domain: '', title: '', snippet, isRedirect: true }
    }
  }

  const domain = (host || '').replace(/^www\./, '')
  let title = rawTitle
  if (
    !title
    || isGroundingRedirectUrl(title)
    || title.includes('grounding-api-redirect')
    || DOMAIN_RE.test(title)
  ) {
    title = domain
  }

  return {
    href,
    domain,
    title: title || domain,
    snippet,
    isRedirect: false,
  }
}

/**
 * Resolve + dedupe a list of `url_citation` objects.
 * Dedupes by resolved `domain` (fallback `href`). Safe for null/empty input.
 * @param {Array<object>|null|undefined} urlCitations
 * @returns {Array<{ href: string, domain: string, title: string, snippet: string, isRedirect: boolean }>}
 */
export function dedupeCitations(urlCitations) {
  if (!Array.isArray(urlCitations) || urlCitations.length === 0) return []

  const seen = new Set()
  const out = []
  for (const c of urlCitations) {
    const resolved = resolveCitation(c)
    const key = resolved.domain || resolved.href
    if (!key || seen.has(key)) continue
    // Drop pure grounding redirects with no recoverable domain
    if (!resolved.domain && isGroundingRedirectUrl(resolved.href)) continue
    seen.add(key)
    out.push(resolved)
  }
  return out
}

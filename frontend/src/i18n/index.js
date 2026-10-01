import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { toPersianDigits, fmtNumber, fmtCurrency } from '@/utils/persianLocale'

// ---------------------------------------------------------------------------
// Global interpolation format — runs for EVERY `{{value}}` i18next interpolates
// (i18next calls `interpolation.format(value, format, lng)`; `format` is the
// text after the comma in `{{value, format}}`, or undefined when unspecified).
// Plural-rule selection happens BEFORE interpolation, so this never sees a key
// — only the substituted values — and so can't disturb plural matching.
//
// Goal: every numeric interpolation honors the user's numeral-script preference
// (Latin default / Persian when toggled) without per-call wiring. A bare number
// is digit-converted only (no grouping → safe for years/ids/counts); explicit
// `number`/`currency` formats opt into locale grouping via the persianLocale
// formatters. Non-numbers pass through untouched (never double-format strings —
// callers that pre-format a number to a string already applied the digits).
// ---------------------------------------------------------------------------
function interpolationFormat(value, format) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return value
  const fmt = typeof format === 'string' ? format.trim().toLowerCase() : ''
  if (fmt === 'number') return fmtNumber(value)
  if (fmt === 'currency') return fmtCurrency(value)
  // Bare numeric value: convert the digit script only, no grouping.
  return toPersianDigits(value)
}

const SUPPORTED = ['en', 'fa']
const FALLBACK_LNG = 'fa'
const STORAGE_KEY = 'unichat-language'

// Per-namespace dynamic importers for EVERY locale file (NOT eager).
// Vite emits one async chunk per language group, so a fa-only user never
// downloads or parses the English JSON (and vice-versa).
// Shape: { './locales/<lng>/<ns>.json': () => import(...) }
const lazyLocaleFiles = import.meta.glob('./locales/**/*.json')

// Group importers by language: { <lng>: { <ns>: importerFn } }
const importersByLang = {}
for (const path in lazyLocaleFiles) {
  const match = path.match(/\.\/locales\/([^/]+)\/([^/]+)\.json$/)
  if (!match) continue
  const [, lng, ns] = match
  if (!importersByLang[lng]) importersByLang[lng] = {}
  importersByLang[lng][ns] = lazyLocaleFiles[path]
}

// Track which languages have their full namespace set registered in the store.
const loadedLanguages = new Set()

// Resolve every namespace bundle for a language into a plain { ns: data } map.
async function fetchLanguageResources(lng) {
  const importers = importersByLang[lng] || {}
  const entries = await Promise.all(
    Object.entries(importers).map(async ([ns, importer]) => {
      const mod = await importer()
      return [ns, mod && mod.default ? mod.default : mod]
    })
  )
  return Object.fromEntries(entries)
}

/** Whether a language's full namespace set is already registered in the store. */
export function isLanguageLoaded(lng) {
  return loadedLanguages.has(lng)
}

/**
 * Lazily fetch + register every namespace bundle for a language, then mark it
 * loaded. Idempotent: an already-loaded language resolves immediately. Resolves
 * only once all namespaces are added so callers can switch without a
 * missing-key flash.
 */
export async function loadLanguage(lng) {
  if (!SUPPORTED.includes(lng)) return
  if (loadedLanguages.has(lng)) return
  const data = await fetchLanguageResources(lng)
  for (const ns in data) {
    if (i18n.hasResourceBundle(lng, ns)) continue
    i18n.addResourceBundle(lng, ns, data[ns], true, true)
  }
  loadedLanguages.add(lng)
}

// Mirror i18next-browser-languagedetector's synchronous resolution
// (order: ['localStorage', 'htmlTag']) so we eager-load ONLY the namespaces
// for the language i18next is about to settle on. A brand-new visitor with no
// stored preference inherits <html lang> (currently "fa") and downloads zero
// English JSON.
function detectInitialLanguage() {
  if (typeof window === 'undefined') return FALLBACK_LNG
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && SUPPORTED.includes(saved)) return saved
  } catch {
    /* localStorage may be unavailable (private mode) */
  }
  const htmlLang = document.documentElement.getAttribute('lang')
  const base = htmlLang ? String(htmlLang).toLowerCase().split('-')[0] : null
  return SUPPORTED.includes(base) ? base : FALLBACK_LNG
}

/**
 * Initialize i18next with ONLY the initial language's namespaces inlined.
 * Awaited by main.jsx before React mounts, so every synchronous i18n.t() / read
 * (including LanguageProvider's useState initializer reading i18n.language) sees
 * a populated store — identical runtime guarantee to the old eager-all init,
 * minus the other language's bytes.
 */
export async function initI18n() {
  const initialLng = detectInitialLanguage()
  const initialResources = await fetchLanguageResources(initialLng)

  await i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      resources: { [initialLng]: initialResources },
      lng: initialLng,
      fallbackLng: FALLBACK_LNG,
      supportedLngs: SUPPORTED,
      nonExplicitSupportedLngs: true,
      defaultNS: 'common',
      fallbackNS: 'common',
      interpolation: { escapeValue: false, format: interpolationFormat },
      detection: {
        order: ['localStorage', 'htmlTag'],
        lookupLocalStorage: STORAGE_KEY,
        caches: ['localStorage'],
      },
      returnEmptyString: false,
    })

  loadedLanguages.add(initialLng)

  // Make the fallback language (fa) available for genuine missing-key fallback
  // when the active language is NOT the fallback. Deferred so it never blocks
  // first paint. In the default fa-active case this is a no-op.
  if (initialLng !== FALLBACK_LNG) {
    const deferFallback = () => loadLanguage(FALLBACK_LNG)
    if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
      window.requestIdleCallback(deferFallback)
    } else if (typeof window !== 'undefined') {
      window.setTimeout(deferFallback, 0)
    } else {
      deferFallback()
    }
  }

  return i18n
}

export default i18n

/**
 * Persian locale helpers — Western Arabic digit (0-9) → Persian (۰-۹) conversion,
 * a small wrapper around `Date#toLocaleTimeString('fa-IR')` for time pills, plus
 * language-aware number / currency formatters (`fmtNumber`, `fmtCurrency`).
 *
 * The digit/time helpers stay side-effect-free (no React, no i18n import) so
 * they tree-shake into any context (tests, web workers). The number/currency
 * formatters read the ACTIVE language from the shared i18n instance so callers
 * never thread a locale through; their `Intl.NumberFormat` instances are
 * memoised at module scope keyed by (lang, kind) — never built per call.
 */

import i18n from '../i18n'

const PERSIAN_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹']

// ---------------------------------------------------------------------------
// Numeral-system preference (user toggle, DEFAULT Latin) — independent of the
// UI language. Controls only the DIGIT SCRIPT of every formatted number / date
// / time: 'latin' → 1234, 'persian' → ۱۲۳۴ (the calendar itself, Shamsi for a
// Persian UI, is unaffected). Persisted in localStorage('numerals').
// `setNumerals` emits i18next 'languageChanged' so every `useTranslation()`
// consumer (the number/date-dense screens) re-renders with the new digits
// without a real language switch.
// ---------------------------------------------------------------------------
const NUMERALS_KEY = 'numerals'
let _numerals = 'latin'
try {
  if (typeof localStorage !== 'undefined') {
    const saved = localStorage.getItem(NUMERALS_KEY)
    if (saved === 'persian' || saved === 'latin') _numerals = saved
  }
} catch { /* private mode / SSR — keep the Latin default */ }

export function getNumerals() {
  return _numerals
}

export function setNumerals(mode) {
  const next = mode === 'persian' ? 'persian' : 'latin'
  _numerals = next
  try { localStorage.setItem(NUMERALS_KEY, next) } catch { /* ignore */ }
  try { i18n.emit('languageChanged', i18n.language) } catch { /* ignore */ }
}

/** CLDR numbering-system id for the active numeral preference. */
export function numeralSystem() {
  return _numerals === 'persian' ? 'arabext' : 'latn'
}

/**
 * Replace every ASCII digit (0-9) in `value` with its Persian counterpart —
 * ONLY when the numeral preference is 'persian'. With the Latin default it
 * returns the digits unchanged, so every date/number path that runs through it
 * honors the user's switch automatically. Returns the input unchanged when
 * `value == null`.
 */
export function toPersianDigits(value) {
  if (value == null) return value
  const str = typeof value === 'string' ? value : String(value)
  if (_numerals !== 'persian') return str
  return str.replace(/[0-9]/g, (d) => PERSIAN_DIGITS[Number(d)])
}

// ---------------------------------------------------------------------------
// Language-aware number / currency formatters
//
// `Intl.NumberFormat` construction is expensive; we cache one instance per
// (lang, kind) so a list of hundreds of cost cells doesn't rebuild a formatter
// on every render. `kind` encodes the option signature (decimals / currency).
// ---------------------------------------------------------------------------

/** Locale for number/currency/time formatting — driven by the NUMERAL
 *  preference (not the UI language), so digits + grouping follow the user's
 *  Latin/Persian choice (default Latin → en-US). */
function activeLocale() {
  return _numerals === 'persian' ? 'fa-IR' : 'en-US'
}

const numberFormatCache = new Map()
const currencyFormatCache = new Map()

function numberFormatter(locale, decimals) {
  const key = `${locale}|n|${decimals == null ? '' : decimals}`
  let fmt = numberFormatCache.get(key)
  if (!fmt) {
    const opts =
      decimals == null
        ? { maximumFractionDigits: 20 }
        : { minimumFractionDigits: decimals, maximumFractionDigits: decimals }
    fmt = new Intl.NumberFormat(locale, opts)
    numberFormatCache.set(key, fmt)
  }
  return fmt
}

function currencyFormatter(locale, currency) {
  const key = `${locale}|c|${currency}`
  let fmt = currencyFormatCache.get(key)
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    })
    currencyFormatCache.set(key, fmt)
  }
  return fmt
}

/**
 * Locale-aware grouped number. `fa` → Persian digits, `en` → en-US grouping.
 * @param {number|string|null|undefined} value
 * @param {{ decimals?: number }} [opts] - fixed fraction-digit count; omit for natural precision.
 * @returns {string} formatted number, or '' for null/undefined.
 */
export function fmtNumber(value, opts = {}) {
  if (value == null) return ''
  const num = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(num)) return ''
  return numberFormatter(activeLocale(), opts.decimals).format(num)
}

/**
 * Locale-aware money string. Keeps the USD symbol ($) but localises the digits
 * per the active i18n language (`fa` → Persian digits).
 * @param {number|string|null|undefined} value
 * @param {{ currency?: 'USD' }} [opts]
 * @returns {string} formatted currency, or '' for null/undefined.
 */
export function fmtCurrency(value, opts = {}) {
  if (value == null) return ''
  const num = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(num)) return ''
  return currencyFormatter(activeLocale(), opts.currency || 'USD').format(num)
}

// Compact-currency formatter cache — chart value axes / on-bar labels need a
// SHORT money string ($1.2k), and tiny sub-cent costs need significant digits
// (a flat 2-dp `$0.00` would erase a $0.004 row). Memoised per (locale, kind)
// like the others, never built per call.
const compactCurrencyCache = new Map()

function compactCurrencyFormatter(locale, kind) {
  const key = `${locale}|cc|${kind}`
  let fmt = compactCurrencyCache.get(key)
  if (!fmt) {
    const base = { style: 'currency', currency: 'USD' }
    const opts =
      kind === 'compact'
        ? { ...base, notation: 'compact', maximumFractionDigits: 1 }
        : kind === 'sig'
          ? { ...base, maximumSignificantDigits: 2 }
          : { ...base, minimumFractionDigits: 2, maximumFractionDigits: 2 }
    fmt = new Intl.NumberFormat(locale, opts)
    compactCurrencyCache.set(key, fmt)
  }
  return fmt
}

/**
 * Compact USD for chart axes / on-bar labels. Digits follow the numeral
 * preference (the locale already does this). Keeps the `$` symbol.
 *
 *  - null / NaN              → ''
 *  - |value| < 1             → 2 significant figures ($0.42, $0.0042)
 *  - |value| >= 1000         → compact notation ($1.2k, $3.4M)
 *  - otherwise               → 2 decimal places ($12.34)
 *
 * @param {number|string|null|undefined} value
 * @returns {string}
 */
export function fmtCurrencyCompact(value) {
  if (value == null) return ''
  const num = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(num)) return ''
  const abs = Math.abs(num)
  const kind = abs < 1 && num !== 0 ? 'sig' : abs >= 1000 ? 'compact' : 'plain'
  return compactCurrencyFormatter(activeLocale(), kind).format(num)
}

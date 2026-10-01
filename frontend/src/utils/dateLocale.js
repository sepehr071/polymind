import { format, formatDistanceToNow } from 'date-fns'
import { faIR } from 'date-fns/locale'
import i18n from '../i18n'
import { toPersianDigits, numeralSystem } from './persianLocale'

function currentLocale() {
  return i18n.language === 'fa' ? faIR : undefined
}

// Digit script follows the user's numeral preference (default Latin) via
// toPersianDigits — a no-op under the Latin default, converts under 'persian'.
// Independent of the UI language and the (language-driven) calendar choice.
function localizeDigits(out) {
  return toPersianDigits(out)
}

// ---------------------------------------------------------------------------
// Shamsi (Jalali) absolute-date rendering for the `fa` language.
//
// date-fns has no Jalali calendar (and `date-fns-jalali` is a new dep we won't
// add), so for `fa` we derive `Intl.DateTimeFormat` options from the date-fns
// format token string and format against the Persian calendar. This keeps the
// SAME `fmtDate(date, formatStr)` signature every caller already uses while
// switching fa output from Gregorian to Shamsi — unifying the app with the
// meetings views (which already render Shamsi via `formatJalali`).
//
// Relative / distance strings ("۳ روز پیش") are calendar-agnostic, so those
// wrappers keep delegating to date-fns with the faIR locale.
// ---------------------------------------------------------------------------

const jalaliFormatCache = new Map()

/** Does the date-fns format string contain calendar-date tokens (y/M/d)? */
function hasDateTokens(formatStr) {
  return /[yMdD]/.test(formatStr)
}

/** Does the date-fns format string contain clock-time tokens (h/H/m/s/a)? */
function hasTimeTokens(formatStr) {
  return /[hHmsa]/.test(formatStr)
}

/**
 * Build Persian-calendar Intl options approximating the date-fns format string.
 * - Long month token (MMM/MMMM, or the localised `P`/`PP`/`PPP` presets) → long month name.
 * - Numeric month (MM/M) → numeric month.
 * - 12-hour token (`h`/`a`) → 12-hour clock, else 24-hour.
 */
function jalaliOptionsFor(formatStr) {
  const opts = {}
  const wantDate = hasDateTokens(formatStr)
  const wantTime = hasTimeTokens(formatStr)
  const usesPreset = /P/.test(formatStr) // date-fns localised presets (PP, PPpp, ...)

  if (wantDate) {
    // Only emit a year when the format string actually has a year token — else
    // a `MMM d` axis label leaks the Shamsi year ("۱۲ خرداد ۱۴۰۵" → "۱۲ خرداد").
    if (/y/.test(formatStr)) opts.year = 'numeric'
    // Long month for word-style formats (MMM/MMMM) and the P-presets; numeric otherwise.
    const longMonth = /MMM/.test(formatStr) || usesPreset
    opts.month = longMonth ? 'long' : 'numeric'
    opts.day = 'numeric'
  }
  if (wantTime || usesPreset) {
    const twelveHour = /h/.test(formatStr) || /a/.test(formatStr)
    opts.hour = '2-digit'
    opts.minute = '2-digit'
    opts.hour12 = twelveHour
    if (/s/.test(formatStr)) opts.second = '2-digit'
  }
  // Bare time-only string with neither date nor explicit time token cannot occur,
  // but guard against an empty options object producing the default full datetime.
  if (Object.keys(opts).length === 0) {
    opts.year = 'numeric'
    opts.month = 'long'
    opts.day = 'numeric'
  }
  return opts
}

function formatJalaliDate(date, formatStr) {
  // Shamsi calendar; digit script (latn/arabext) follows the numeral preference.
  const ns = numeralSystem()
  const key = `${formatStr}|${ns}`
  let fmt = jalaliFormatCache.get(key)
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(`fa-IR-u-ca-persian-nu-${ns}`, jalaliOptionsFor(formatStr))
    jalaliFormatCache.set(key, fmt)
  }
  return fmt.format(date instanceof Date ? date : new Date(date))
}

export function fmtDate(date, formatStr) {
  if (i18n.language === 'fa') {
    try {
      // Shamsi via Intl; digits emitted per the numeral preference (nu ext).
      return formatJalaliDate(date, formatStr)
    } catch {
      // Fall through to date-fns (Gregorian) on any Intl failure.
    }
  }
  return localizeDigits(format(date, formatStr, { locale: currentLocale() }))
}

export function fmtDistanceToNow(date, options = {}) {
  return localizeDigits(formatDistanceToNow(date, { ...options, locale: currentLocale() }))
}

/**
 * Null-safe relative-time helper: empty string for a missing/invalid timestamp,
 * never throws (date-fns raises on an invalid Date). Wraps `fmtDistanceToNow`
 * so the localized digits + locale handling are shared. Replaces the
 * `formatRelative` guard duplicated across the projects list/card views.
 */
export function fmtDistanceToNowSafe(ts, opts = { addSuffix: true }) {
  if (!ts) return ''
  try {
    return fmtDistanceToNow(new Date(ts), opts)
  } catch {
    return ''
  }
}

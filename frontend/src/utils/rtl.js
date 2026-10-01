/**
 * RTL (Right-to-Left) text detection utilities
 * Supports Persian, Arabic, and Hebrew scripts
 */

import i18n from '../i18n'
import { numeralSystem } from './persianLocale'

// Unicode ranges for RTL scripts:
// - Arabic: \u0600-\u06FF (basic), \u0750-\u077F (supplement),
//   \u08A0-\u08FF (extended-A), \uFB50-\uFDFF (presentation forms A),
//   \uFE70-\uFEFF (presentation forms B)
// - Hebrew: \u0590-\u05FF
const RTL_REGEX = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\u0590-\u05FF]/
const RTL_CHAR_REGEX = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\u0590-\u05FF]/g

/**
 * Check if text contains any RTL characters
 * @param {string} text - Text to check
 * @returns {boolean} - True if text contains RTL characters
 */
export function containsRTL(text) {
  if (!text || typeof text !== 'string') return false
  return RTL_REGEX.test(text)
}

/**
 * Check if text is predominantly RTL (>30% RTL characters)
 * Uses a lower threshold to catch mixed content that starts with RTL
 * @param {string} text - Text to check
 * @returns {boolean} - True if text is predominantly RTL
 */
export function isRTL(text) {
  if (!text || typeof text !== 'string') return false

  // Remove code blocks and inline code before checking (they should remain LTR)
  const textWithoutCode = text
    .replace(/```[\s\S]*?```/g, '') // Remove fenced code blocks
    .replace(/`[^`]+`/g, '')        // Remove inline code
    .trim()

  if (!textWithoutCode) return false

  const rtlMatches = textWithoutCode.match(RTL_CHAR_REGEX)
  if (!rtlMatches) return false

  // Count only letter characters (exclude spaces, numbers, punctuation)
  const letterCount = textWithoutCode.replace(/[\s\d\p{P}]/gu, '').length
  if (letterCount === 0) return false

  const rtlRatio = rtlMatches.length / letterCount
  return rtlRatio > 0.3 // 30% threshold
}

/**
 * Get the text direction for a given text
 * @param {string} text - Text to analyze
 * @returns {'rtl' | 'ltr'} - Text direction
 */
export function getTextDirection(text) {
  return isRTL(text) ? 'rtl' : 'ltr'
}

// ---------------------------------------------------------------------------
// Meeting-assistant port helpers
//
// These mirror `meeting-assistant/frontend/lib/rtl.ts` so ported meeting
// components can keep their original imports. Kept alongside the broader
// uni-chat RTL helpers above rather than in a separate module.
// ---------------------------------------------------------------------------

const PERSIAN_RANGE = /[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]/

/**
 * Returns true if the text contains any character in the Persian/Arabic
 * Unicode ranges. Strict char-presence test (no ratio threshold).
 * Internal helper backing `dirOf`; not exported (no external consumer).
 *
 * @param {string} text
 * @returns {boolean}
 */
function isPersian(text) {
  if (typeof text !== 'string') return false
  return PERSIAN_RANGE.test(text)
}

/**
 * @param {string} text
 * @returns {'rtl' | 'ltr'}
 */
export function dirOf(text) {
  return isPersian(text) ? 'rtl' : 'ltr'
}

/**
 * Format an ISO-8601 timestamp as a calendar date string honouring the ACTIVE
 * UI language: Jalali (Persian calendar, Persian digits) for `fa`, Gregorian
 * (en-US) for every other language. Falls back to the raw input on any
 * formatter failure.
 *
 * @param {string|null|undefined} iso
 * @returns {string}
 */
export function formatJalali(iso) {
  if (!iso) return ''
  // Calendar follows the UI language (Shamsi for fa); digit script follows the
  // numeral preference (default Latin).
  const ns = numeralSystem()
  const isFa = i18n.language === 'fa'
  const locale = isFa ? `fa-IR-u-ca-persian-nu-${ns}` : `en-US-u-nu-${ns}`
  try {
    return new Intl.DateTimeFormat(locale, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

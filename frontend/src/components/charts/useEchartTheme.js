import { useCallback, useEffect, useState } from 'react'
import i18n from '@/i18n'
import { useLanguage } from '@/context/LanguageContext'
import { FONT_FAMILY } from '@/theme/tokens'

/**
 * Resolve the analytics chart theme from live CSS custom properties into the
 * LITERAL color strings an ECharts canvas needs.
 *
 * Why this exists: the DOM accepts `hsl(var(--chart-1))`, but the ECharts
 * canvas painter does NOT read CSS variables — it needs a concrete color. The
 * `--chart-N` / `--foreground*` / `--border` tokens are stored as
 * space-separated HSL triplets (e.g. `199 89% 48%`), so we read each off
 * `getComputedStyle(documentElement)` and wrap it as `hsl(199 89% 48%)`.
 *
 * Recomputes when the theme actually changes:
 *  - `.dark` class / attribute flips on <html>  → MutationObserver
 *  - i18next 'languageChanged'  → covers UI language AND the numeral toggle
 *    (setNumerals emits it); RTL + font follow the language.
 *
 * `fontFamily` = Vazirmatn stack from theme/tokens (canvas won't inherit CSS).
 *
 * @returns {{
 *   palette: string[],   // 6 resolved series colors (--chart-1..6)
 *   axisColor: string,   // --foreground-tertiary
 *   gridColor: string,   // --border (split lines)
 *   fgColor: string,     // --foreground
 *   fgSecondary: string, // --foreground-secondary
 *   tooltipBg: string,   // --background-elevated
 *   fontFamily: string,
 *   isRTL: boolean,
 * }}
 */

/** Read a CSS-var HSL triplet and wrap it as a literal `hsl(...)` color. */
function resolveHsl(styles, name, fallback) {
  const raw = styles.getPropertyValue(name).trim()
  return raw ? `hsl(${raw})` : fallback
}

function readTheme(isRTL) {
  // SSR / pre-mount guard — return a usable default palette.
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return {
      palette: ['#1E47D1', '#6D5EF7', '#14B8A6', '#F79009', '#EC4899', '#12B76A'],
      axisColor: 'rgba(148,163,184,0.65)',
      gridColor: 'rgba(148,163,184,0.25)',
      fgColor: '#e5e5e5',
      fgSecondary: '#9ca3af',
      tooltipBg: '#1f1f1f',
      fontFamily: FONT_FAMILY,
      isRTL,
    }
  }

  const styles = getComputedStyle(document.documentElement)
  const palette = Array.from({ length: 6 }, (_, i) =>
    resolveHsl(styles, `--chart-${i + 1}`, '#38bdf8'),
  )

  return {
    palette,
    axisColor: resolveHsl(styles, '--foreground-tertiary', 'rgba(148,163,184,0.65)'),
    gridColor: resolveHsl(styles, '--border', 'rgba(148,163,184,0.25)'),
    fgColor: resolveHsl(styles, '--foreground', '#e5e5e5'),
    fgSecondary: resolveHsl(styles, '--foreground-secondary', '#9ca3af'),
    tooltipBg: resolveHsl(styles, '--background-elevated', '#1f1f1f'),
    fontFamily: FONT_FAMILY,
    isRTL,
  }
}

export function useEchartTheme() {
  const { isRTL } = useLanguage()
  const [theme, setTheme] = useState(() => readTheme(isRTL))

  const recompute = useCallback(() => {
    setTheme(readTheme(isRTL))
  }, [isRTL])

  // Recompute on dark-class toggle (and on the isRTL change captured above).
  useEffect(() => {
    recompute()

    const observer = new MutationObserver(recompute)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'data-theme', 'style'],
    })

    // language + numerals both surface as 'languageChanged'.
    i18n.on('languageChanged', recompute)

    return () => {
      observer.disconnect()
      i18n.off('languageChanged', recompute)
    }
  }, [recompute])

  return theme
}

export default useEchartTheme

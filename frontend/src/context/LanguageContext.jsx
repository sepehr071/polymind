import { createContext, useContext, useEffect, useRef, useState, useCallback, useMemo } from 'react'
import i18n, { loadLanguage, isLanguageLoaded } from '../i18n'
import { getNumerals, setNumerals as setNumeralsModule } from '../utils/persianLocale'

const LanguageContext = createContext(null)

const SUPPORTED = ['en', 'fa']
const STORAGE_KEY = 'unichat-language'

function normalize(lang) {
  if (!lang) return 'fa'
  const base = String(lang).toLowerCase().split('-')[0]
  return SUPPORTED.includes(base) ? base : 'fa'
}

export function LanguageProvider({ children }) {
  const [language, setLanguageState] = useState(() => {
    if (typeof window === 'undefined') return 'fa'
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && SUPPORTED.includes(saved)) return saved
    const detected = normalize(i18n.language)
    return detected
  })

  // Tracks the latest requested language so an out-of-order async bundle load
  // (rapid toggles) never applies a stale switch.
  const pendingRef = useRef(language)

  useEffect(() => {
    pendingRef.current = language
    const root = document.documentElement
    const dir = language === 'fa' ? 'rtl' : 'ltr'
    localStorage.setItem(STORAGE_KEY, language)

    const apply = () => {
      // Bail if a newer switch superseded this one mid-load.
      if (pendingRef.current !== language) return
      root.lang = language
      root.dir = dir
      root.classList.toggle('font-persian', language === 'fa')
      if (i18n.language !== language) {
        i18n.changeLanguage(language)
      }
    }

    // Ensure the target language's namespaces are registered BEFORE applying,
    // so changeLanguage never renders against an empty store (missing-key
    // flash). The initial/default language is already eager-loaded, so apply
    // synchronously on first paint (no microtask delay to the lang/dir attrs);
    // only a genuinely-not-yet-loaded language defers behind its bundle fetch.
    if (isLanguageLoaded(language)) {
      apply()
    } else {
      loadLanguage(language).then(apply)
    }
  }, [language])

  const setLanguage = useCallback((next) => {
    const norm = normalize(next)
    setLanguageState(norm)
  }, [])

  // Numeral-script preference ('latin' default | 'persian'), independent of the
  // UI language. The module setter persists it + emits a re-render for every
  // number/date-dense screen; local state re-renders this provider's consumers.
  const [numerals, setNumeralsState] = useState(() => getNumerals())
  const setNumerals = useCallback((mode) => {
    const next = mode === 'persian' ? 'persian' : 'latin'
    setNumeralsModule(next)
    setNumeralsState(next)
  }, [])

  const value = useMemo(() => ({
    language,
    setLanguage,
    isRTL: language === 'fa',
    dir: language === 'fa' ? 'rtl' : 'ltr',
    numerals,
    setNumerals,
  }), [language, setLanguage, numerals, setNumerals])

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLanguage() {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error('useLanguage must be used within a LanguageProvider')
  return ctx
}

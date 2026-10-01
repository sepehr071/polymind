import { useState, useEffect } from 'react'

/**
 * SSR-safe `matchMedia` subscription. Returns whether `query` currently matches
 * and re-renders on change. Mirrors the inline pattern at
 * HeroSection.jsx (the WebGL viewport gate) but reusable app-wide.
 *
 *   const isWide = useMediaQuery('(min-width: 1024px)')
 */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/**
 * True on touch / mobile-like devices (phones, tablets). The signal used to
 * shed expensive continuous motion + paint on the landing page, independent of
 * the user's reduced-motion preference.
 */
export function useCoarsePointer() {
  return useMediaQuery('(pointer: coarse)')
}

export default useMediaQuery

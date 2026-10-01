import { useMemo } from 'react'
import { CacheProvider } from '@emotion/react'
import { ThemeProvider } from '@mui/material/styles'
import { useLanguage } from '@/context/LanguageContext'
import { getEmotionCache } from './emotionCache'
import { createAppTheme } from './createAppTheme'

// No CssBaseline — Tailwind preflight owns the reset. Dark mode is driven by the
// existing `.light`/`.dark` class on <html> (ThemeContext) via colorSchemeSelector:'class'.
// Direction is driven by LanguageContext; the RTL Emotion cache flips MUI styles.
//
// colorSchemeNode={null} is load-bearing: with `cssVariables` + `colorSchemes`,
// MUI v9's ThemeProvider runs its CssVarsProvider, which by default OWNS the mode
// — a layout effect writes the scheme class onto <html> from `mui-mode`/OS
// (defaultMode:'system'), clobbering ThemeContext's stored choice on reload.
// Passing null disables that DOM write (createCssVarsProvider guards on
// `colorSchemeNode`), leaving ThemeContext the single source of truth while MUI
// still emits the scoped `.light{}`/`.dark{}` CSS-var stylesheets the class selects.
// LiquidGlassFilter removed — quiet-glass uses CSS blur only, no SVG refraction.
export default function MuiProvider({ children }) {
  const { dir } = useLanguage()
  const cache = getEmotionCache(dir)
  const theme = useMemo(() => createAppTheme(dir), [dir])
  return (
    <CacheProvider value={cache}>
      <ThemeProvider theme={theme} colorSchemeNode={null}>
        {children}
      </ThemeProvider>
    </CacheProvider>
  )
}

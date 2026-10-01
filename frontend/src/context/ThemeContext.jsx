import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'

const ThemeContext = createContext(null)

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    // Initialize from localStorage or default to 'light'
    if (typeof window !== 'undefined') {
      const savedTheme = localStorage.getItem('unichat-theme')
      return savedTheme || 'light'
    }
    return 'light'
  })

  useEffect(() => {
    // Apply theme class to document root
    const root = document.documentElement
    root.classList.remove('light', 'dark')
    root.classList.add(theme)

    // Save to localStorage
    localStorage.setItem('unichat-theme', theme)
  }, [theme])

  const setTheme = useCallback((newTheme) => {
    if (newTheme === 'light' || newTheme === 'dark') {
      setThemeState(newTheme)
    }
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState(prev => (prev === 'dark' ? 'light' : 'dark'))
  }, [])

  const value = useMemo(() => ({
    theme,
    setTheme,
    toggleTheme,
    isDark: theme === 'dark',
    isLight: theme === 'light',
  }), [theme, setTheme, toggleTheme])

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}

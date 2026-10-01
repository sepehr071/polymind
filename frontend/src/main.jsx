import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import App from './App'
import { AuthProvider } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import { LanguageProvider } from './context/LanguageContext'
import AppDirectionProvider from './components/providers/AppDirectionProvider'
import MuiProvider from './theme/MuiProvider'
import { TooltipProvider } from './components/ui/tooltip'
import Toast from './components/ui/Toast'
import RewardPop from './components/ui/reward-pop'
import { initI18n } from './i18n'
// Self-hosted fonts (no Google Fonts CDN — air-gapped / Iran).
// UI = Vazirmatn 400–700 only. Mono for code. Landing display weights trimmed.
import '@fontsource/vazirmatn/400.css'
import '@fontsource/vazirmatn/500.css'
import '@fontsource/vazirmatn/600.css'
import '@fontsource/vazirmatn/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/geist-mono/400.css'
import '@fontsource/geist-mono/500.css'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
      // List queries (workspaces/projects/etc.) shouldn't refire on every
      // tab focus once stale — the auth/me query opts back IN per-query when
      // it needs to pick up platform-feature toggles.
      refetchOnWindowFocus: false,
    },
  },
})

// Load the active language's translation bundle (only that language's JSON)
// BEFORE mounting React, so every synchronous i18n read on first paint sees a
// populated store — same guarantee as the old eager-all init, minus the other
// language's bytes.
initI18n().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ThemeProvider>
            <LanguageProvider>
              <AppDirectionProvider>
                <MuiProvider>
                <AuthProvider>
                  <TooltipProvider delayDuration={300}>
                    <App />
                  </TooltipProvider>
                <Toaster
                  position="top-center"
                  gutter={10}
                  toastOptions={{
                    duration: 4000,
                    success: { duration: 3500 },
                    error: { duration: 6000 },
                    loading: { duration: Infinity },
                  }}
                >
                  {(t) => <Toast t={t} />}
                </Toaster>
                {/* App-root reward overlay: a 3D icon pops at milestones (next
                    to confetti). Mounted here so it survives route changes
                    (onboarding fires it then navigates to /chat). */}
                <RewardPop />
                </AuthProvider>
                </MuiProvider>
              </AppDirectionProvider>
            </LanguageProvider>
          </ThemeProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </React.StrictMode>,
  )
})

import { useState, useEffect, useCallback, Suspense } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import AppTopBar from './AppTopBar'
import AppSidebar from './AppSidebar'
import PageTransition from './PageTransition'
import ShortcutsHelpModal from './ShortcutsHelpModal'
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts'
import lazyWithRetry from '../../utils/lazyWithRetry'

const SettingsDialog = lazyWithRetry(() => import('../settings/SettingsDialog'))

const SIDEBAR_KEY = 'app-sidebar-collapsed'

function readSidebarCollapsed() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Authenticated shell: 280px sidebar + slim top bar over the page outlet.
 * Chat history lives in the sidebar. Per-tool rails (data, agent, OCR) stay
 * on their own pages.
 */
export default function AppShell() {
  const navigate = useNavigate()
  const { t } = useTranslation('layout')
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [settingsModal, setSettingsModal] = useState(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)

  const collapseSidebar = useCallback(() => {
    setSidebarCollapsed(true)
    try {
      localStorage.setItem(SIDEBAR_KEY, '1')
    } catch {
      /* keep in-memory */
    }
  }, [])

  const expandSidebar = useCallback(() => {
    setSidebarCollapsed(false)
    try {
      localStorage.setItem(SIDEBAR_KEY, '0')
    } catch {
      /* keep in-memory */
    }
  }, [])

  const closeMobile = useCallback(() => setMobileOpen(false), [])

  useKeyboardShortcuts({
    'mod+shift+o': () => navigate('/chat'),
    'shift+escape': () => window.dispatchEvent(new CustomEvent('chat:composer-focus')),
    'mod+/': () => setShortcutsOpen((o) => !o),
  })

  useEffect(() => {
    const onOpen = (e) => setSettingsModal({ section: e.detail?.section || 'profile' })
    window.addEventListener('open-settings', onOpen)
    return () => window.removeEventListener('open-settings', onOpen)
  }, [])

  return (
    <>
      <div
        className="flex h-app-dvh overflow-hidden bg-background"
        style={{
          paddingTop: 'var(--safe-top)',
          paddingBottom: 'var(--safe-bottom)',
          paddingLeft: 'var(--safe-start)',
          paddingRight: 'var(--safe-end)',
        }}
      >
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-2 focus:start-2 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:shadow-md focus:outline-none focus:ring-2 focus:ring-ring"
        >
          {t('skipToContent', { defaultValue: 'Skip to content' })}
        </a>

        {mobileOpen && (
          <button
            type="button"
            aria-label={t('sidebar.closeMenu')}
            className="fixed inset-0 z-30 bg-black/45 lg:hidden"
            onClick={closeMobile}
          />
        )}

        <AppSidebar
          collapsed={sidebarCollapsed}
          mobileOpen={mobileOpen}
          onNavigate={closeMobile}
          onClose={closeMobile}
          onCollapse={collapseSidebar}
        />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <AppTopBar
            sidebarCollapsed={sidebarCollapsed}
            mobileOpen={mobileOpen}
            onOpenSidebar={() => setMobileOpen(true)}
            onExpandSidebar={expandSidebar}
          />
          <main id="main-content" tabIndex={-1} className="flex min-h-0 flex-1 flex-col overflow-hidden outline-none">
            <div className="min-h-0 flex-1 overflow-hidden">
              <PageTransition>
                <Outlet />
              </PageTransition>
            </div>
          </main>
        </div>
      </div>

      <ShortcutsHelpModal open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      {settingsModal && (
        <Suspense fallback={null}>
          <SettingsDialog
            open
            initialSection={settingsModal.section}
            onOpenChange={(next) => {
              if (!next) setSettingsModal(null)
            }}
          />
        </Suspense>
      )}
    </>
  )
}

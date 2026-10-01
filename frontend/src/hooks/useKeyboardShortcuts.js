import { useEffect, useCallback } from 'react'

/**
 * Hook for handling keyboard shortcuts
 * @param {Object} shortcuts - Map of key combinations to callback functions
 * @param {boolean} enabled - Whether shortcuts are enabled
 */
export function useKeyboardShortcuts(shortcuts, enabled = true) {
  const handleKeyDown = useCallback((event) => {
    if (!enabled) return

    // Don't trigger shortcuts when typing in inputs or textareas
    const target = event.target
    const isInput = target.tagName === 'INPUT' ||
                    target.tagName === 'TEXTAREA' ||
                    target.isContentEditable

    // Build the key combination string
    const parts = []
    if (event.metaKey || event.ctrlKey) parts.push('mod')
    if (event.shiftKey) parts.push('shift')
    if (event.altKey) parts.push('alt')
    parts.push(event.key.toLowerCase())
    const combo = parts.join('+')

    // Check for matching shortcut
    const callback = shortcuts[combo]
    if (callback) {
      // These ChatGPT-muscle-memory combos are fired *from* the composer
      // constantly (new chat / focus / help), so they must work even while a
      // text field has focus. Plain `escape` is intentionally NOT here —
      // modals/dropdowns own Esc; a global Esc handler would steal it.
      const allowInInput = ['mod+shift+o', 'shift+escape', 'mod+/'].includes(combo)
      if (!isInput || allowInInput) {
        event.preventDefault()
        callback(event)
      }
    }
  }, [shortcuts, enabled])

  useEffect(() => {
    if (!enabled) return

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown, enabled])
}

/**
 * Shortcut catalog for the help modal. Only the shortcuts that are actually
 * wired live here (no vaporware rows) — the modal renders straight from this.
 * `keys` are display tokens resolved per-OS by `formatShortcut`; descriptions
 * are i18n keys (ns `layout`) the modal translates.
 *
 * newChat / focusComposer / help are global (wired in MainLayout via
 * `useKeyboardShortcuts`). sendMessage / newline are composer-local (handled
 * in ChatInput's own keydown) — listed here purely for discoverability.
 */
export const SHORTCUTS = {
  newChat: { keys: ['Ctrl/Cmd', 'Shift', 'O'], descriptionKey: 'shortcutsHelp.newChat' },
  focusComposer: { keys: ['Shift', 'Esc'], descriptionKey: 'shortcutsHelp.focusComposer' },
  help: { keys: ['Ctrl/Cmd', '/'], descriptionKey: 'shortcutsHelp.help' },
  sendMessage: { keys: ['Enter'], descriptionKey: 'shortcutsHelp.sendMessage' },
  newline: { keys: ['Shift', 'Enter'], descriptionKey: 'shortcutsHelp.newline' },
}

/**
 * Format shortcut for display based on OS
 */
export function formatShortcut(keys) {
  const isMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform)

  return keys.map(key => {
    if (key === 'Ctrl/Cmd') return isMac ? '⌘' : 'Ctrl'
    if (key === 'Shift') return isMac ? '⇧' : 'Shift'
    if (key === 'Alt') return isMac ? '⌥' : 'Alt'
    if (key === 'Esc') return 'Esc'
    return key
  }).join(' + ')
}

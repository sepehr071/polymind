import { useSyncExternalStore } from 'react'

function subscribe(callback) {
  window.addEventListener('online', callback)
  window.addEventListener('offline', callback)
  return () => {
    window.removeEventListener('online', callback)
    window.removeEventListener('offline', callback)
  }
}

/**
 * Live `navigator.onLine` as React state. Primitive boolean snapshot, so the
 * useSyncExternalStore same-ref bail-out gotcha doesn't apply.
 */
export function useOnlineStatus() {
  return useSyncExternalStore(subscribe, () => navigator.onLine, () => true)
}

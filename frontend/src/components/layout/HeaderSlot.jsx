import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

/**
 * HeaderSlot — lets a route page inject controls into the single global top bar
 * (one thin bar app-wide, not a per-page second header band).
 *
 * AppTopBar renders two empty mount points:
 *   - #header-route-start (after the back-to-hub + scope pills, inline-start)
 *   - #header-route-end   (trailing cluster, before the switcher + account)
 *
 * `side` picks the target. We resolve the DOM node in an effect so the first
 * paint after mount finds it (AppTopBar mounts before route content in AppShell,
 * but the effect guards against the target being absent — missing target →
 * render nothing rather than throw).
 */
export default function HeaderSlot({ side = 'start', children }) {
  const targetId = side === 'end' ? 'header-route-end' : 'header-route-start'
  const [target, setTarget] = useState(null)

  useEffect(() => {
    setTarget(document.getElementById(targetId))
  }, [targetId])

  if (!target) return null
  return createPortal(children, target)
}

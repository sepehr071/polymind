import { Suspense, lazy } from 'react'
import { useLocation } from 'react-router-dom'
import { getRouteSectionKey } from '../../utils/routeSection'

// The motion-bearing transition (AnimatePresence + slide/fade) is code-split so
// `motion/react` loads on demand rather than in the entry/app-shell chunk that
// MainLayout/App pull eagerly. The chunk is fetched the moment the layout
// mounts; until it arrives we render children plainly (no transition, no blank
// frame) via the Suspense fallback below.
const MotionPageTransition = lazy(() => import('./MotionPageTransition'))

/**
 * Page-transition wrapper (light shell). Delegates the actual slide+fade to a
 * lazily-loaded motion component (see MotionPageTransition) to keep framer-motion
 * out of the entry bundle.
 *
 * The Suspense fallback renders the children directly in the same `h-full w-full`
 * box, keyed on the route section, so the very first paint shows content
 * instantly (the transition simply kicks in once the chunk resolves — typically
 * before the user's first navigation).
 */
export default function PageTransition({ children }) {
  const location = useLocation()

  return (
    <Suspense
      fallback={
        <div key={getRouteSectionKey(location.pathname)} className="h-full w-full">
          {children}
        </div>
      }
    >
      <MotionPageTransition>{children}</MotionPageTransition>
    </Suspense>
  )
}

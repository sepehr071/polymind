import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useLocation } from 'react-router-dom'
import { getRouteSectionKey } from '../../utils/routeSection'
import { useLanguage } from '@/context/LanguageContext'

/**
 * Motion-bearing page transition — code-split out of `PageTransition.jsx` so
 * framer-motion (`motion/react`) is NOT pulled into the entry/app-shell chunk
 * (MainLayout/App import the light wrapper, which lazy-loads this).
 *
 * Wraps children in <AnimatePresence mode="wait"> keyed on the top-level route
 * section (see getRouteSectionKey), so only section changes trigger a symmetric
 * slide + fade. Param-only navigation within a section (e.g. /chat → /chat/<id>)
 * keeps the same key, so the routed subtree is NOT remounted — this is what
 * prevents the first chat message from "refreshing" the page mid-stream.
 *
 * Respects prefers-reduced-motion: durations collapse to 0 and the
 * x-translate is skipped, so the swap is instant with no jarring snap.
 *
 * The slide direction is mirrored for RTL — under `dir="rtl"` the enter/exit
 * x-offsets flip sign so the new page slides in from the correct edge instead
 * of fighting the reading direction.
 */
export default function MotionPageTransition({ children }) {
  const location = useLocation()
  const reduce = useReducedMotion()
  const { isRTL } = useLanguage()

  const dir = isRTL ? -1 : 1
  const distance = reduce ? 0 : 20 * dir
  const duration = reduce ? 0 : 0.2

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={getRouteSectionKey(location.pathname)}
        initial={{ opacity: 0, x: distance }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -distance }}
        transition={{ duration, ease: 'easeOut' }}
        className="h-full w-full"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  )
}

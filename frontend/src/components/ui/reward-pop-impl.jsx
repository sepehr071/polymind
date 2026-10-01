import { useEffect } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'

import Icon3D from './icon-3d'

/**
 * Motion-bearing reward overlay — code-split out of `reward-pop.jsx` so
 * framer-motion (`motion/react`) is NOT pulled into the entry/app-shell chunk.
 * This module is lazy-imported by the root `<RewardPop>` wrapper only on the
 * first `fireReward(...)` of the session (a rare milestone), so the chunk
 * downloads on demand instead of at startup.
 *
 * Renders a 3D icon that springs in over the confetti burst, then auto-dismisses
 * via the parent's timer. Decorative (`aria-hidden`) — the success toast already
 * announces the outcome to assistive tech. Reduce-motion → plain fade, no
 * transform (Lottie/CSS keyframes are frozen elsewhere; this is JS-driven so it
 * must self-gate). Pointer-events-none + z above MUI modals (1300) so it floats
 * over dialogs without ever blocking input.
 */
export default function RewardPopImpl({ reward, src, duration, clear }) {
  const reduceMotion = useReducedMotion()

  useEffect(() => {
    if (!reward) return undefined
    const timer = setTimeout(clear, reduceMotion ? 1000 : duration)
    return () => clearTimeout(timer)
  }, [reward, reduceMotion, duration, clear])

  return (
    <AnimatePresence>
      {src && (
        <motion.div
          key={reward.id}
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 z-[1500] flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <motion.div
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.4, y: 28 }}
            animate={reduceMotion ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.85, y: -18 }}
            transition={
              reduceMotion
                ? { duration: 0.2 }
                : { type: 'spring', stiffness: 320, damping: 17, mass: 0.7 }
            }
          >
            <Icon3D src={src} size={144} alt="" className="drop-shadow-2xl" />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

import { useEffect, useRef, useState } from 'react'
import { useInView } from 'react-intersection-observer'
import { useMediaQuery } from './useMediaQuery'

const UNSET = Symbol('unset')

// Local reduced-motion read (was framer-motion's `useReducedMotion`). This hook
// is hoisted into the entry chunk by rollup (StatTile → many lazy pages), so a
// `motion/react` import here dragged the whole framer-motion vendor into the
// app-shell bundle. matchMedia via the shared useMediaQuery keeps it dependency-free.
function usePrefersReducedMotion() {
  return useMediaQuery('(prefers-reduced-motion: reduce)')
}

/**
 * Animated count-up hook. Tweens an integer from 0 → `end` with an ease-out-cubic
 * curve over `duration` ms, optionally deferring the start until the element is
 * scrolled into view.
 *
 * Returns the live `count` as a NUMBER — the caller owns formatting (so digits
 * follow the user's Persian/Latin numeral preference via `fmtNumber`, never a raw
 * `.toLocaleString()`).
 *
 * Honors `prefers-reduced-motion`: with motion reduced the value snaps straight
 * to `end` (no animation), so reduced-motion users still see the final figure.
 *
 * @param {number} end                 target value
 * @param {number} [duration=2000]      tween length in ms
 * @param {boolean} [startOnView=true]  defer the tween until in view (IntersectionObserver, once)
 * @returns {{ count: number, ref: (node?: Element | null) => void }}
 */
export function useCountUp(end, duration = 2000, startOnView = true) {
  const reduceMotion = usePrefersReducedMotion()
  const [count, setCount] = useState(reduceMotion ? end : 0)
  const [ref, inView] = useInView({ triggerOnce: true })
  // Live mirror of `count` so a re-tween starts from the displayed value
  // without making the effect depend on `count` (which would loop).
  const countRef = useRef(reduceMotion ? end : 0)
  // Symbol sentinel: collision-proof against callers passing null/undefined as `end`.
  const prevEndRef = useRef(UNSET)
  const rafRef = useRef(0)

  useEffect(() => {
    if (startOnView && !inView) return
    // Re-tween whenever the target changes (async data arriving after the
    // first in-view render with a placeholder 0 must restart the animation).
    if (prevEndRef.current === end) return
    prevEndRef.current = end

    // Reduced motion: skip the tween entirely, land on the final value.
    if (reduceMotion) {
      countRef.current = end
      setCount(end)
      return
    }

    const startTime = performance.now()
    const startValue = countRef.current

    const animate = (now) => {
      const progress = Math.min((now - startTime) / duration, 1)
      // Ease out cubic.
      const eased = 1 - Math.pow(1 - progress, 3)
      const value = Math.round(startValue + (end - startValue) * eased)
      countRef.current = value
      setCount(value)

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate)
      }
    }

    rafRef.current = requestAnimationFrame(animate)

    return () => cancelAnimationFrame(rafRef.current)
  }, [end, duration, inView, startOnView, reduceMotion])

  return { count, ref }
}

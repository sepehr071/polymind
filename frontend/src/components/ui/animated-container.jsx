import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { cn } from '@/lib/utils'
import {
  fadeVariants,
  slideUpVariants,
  slideInLeftVariants,
  slideInRightVariants,
  scaleVariants,
  staggerItemVariants,
  mediumTransition,
} from '../../utils/animations'

const variantMap = {
  fade: fadeVariants,
  slideUp: slideUpVariants,
  slideLeft: slideInLeftVariants,
  slideRight: slideInRightVariants,
  scale: scaleVariants,
}

/**
 * AnimatedContainer - wraps content with enter/exit animations
 */
export function AnimatedContainer({
  children,
  className,
  variant = 'fade', // 'fade' | 'slideUp' | 'slideLeft' | 'slideRight' | 'scale'
  show = true,
  ...props
}) {
  const variants = variantMap[variant] || fadeVariants
  const reduceMotion = useReducedMotion()

  return (
    <AnimatePresence mode="wait">
      {show && (
        <motion.div
          className={className}
          initial={reduceMotion ? 'animate' : 'initial'}
          animate="animate"
          exit={reduceMotion ? 'animate' : 'exit'}
          variants={variants}
          transition={reduceMotion ? { duration: 0 } : mediumTransition}
          {...props}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/**
 * FadeIn - simple fade in animation on mount
 */
export function FadeIn({ children, className, delay = 0, ...props }) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduceMotion ? { opacity: 1 } : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={reduceMotion ? { duration: 0 } : { ...mediumTransition, delay }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * SlideUp - slide up and fade in on mount
 */
export function SlideUp({ children, className, delay = 0, ...props }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...mediumTransition, delay }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * StaggerContainer - for staggered list animations.
 *
 * Fires the reveal once on mount only (motion's initial→animate runs on mount;
 * a same-key re-render from a react-query refetch / filter change keeps the node
 * mounted and does NOT replay). To re-trigger intentionally (e.g. a tab swap),
 * change the React `key`.
 *
 * The cascade is bounded: each child is delayed by `min(domIndex, maxStagger)
 * * stagger`, so children past `maxStagger` all snap in on the same final beat
 * instead of accruing an unbounded delay — a 100-item list reveals in
 * `maxStagger * stagger` (~0.48s) rather than crawling for seconds. This uses
 * motion's `delayChildren(index, total)` function form, which fully replaces
 * the built-in `index * staggerChildren` formula and reads true DOM order, so
 * children need no per-item index prop. Transform is y/opacity only (RTL-safe).
 */
export function StaggerContainer({
  children,
  className,
  stagger = 0.04,
  maxStagger = 12,
  ...props
}) {
  const reduceMotion = useReducedMotion()

  if (reduceMotion) {
    return (
      <div className={className} {...props}>
        {children}
      </div>
    )
  }

  const variants = {
    initial: {},
    animate: {
      transition: {
        delayChildren: (index) => Math.min(index, maxStagger) * stagger,
      },
    },
  }

  return (
    <motion.div
      className={className}
      initial="initial"
      animate="animate"
      variants={variants}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * StaggerItem - child of StaggerContainer. Reduce-motion renders a plain div
 * (no transform); the per-child delay is owned by the parent (see above).
 */
export function StaggerItem({ children, className, ...props }) {
  const reduceMotion = useReducedMotion()

  if (reduceMotion) {
    return (
      <div className={className} {...props}>
        {children}
      </div>
    )
  }

  return (
    <motion.div
      className={className}
      variants={staggerItemVariants}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * MotionDiv - generic motion wrapper for custom animations
 */
export function MotionDiv({ children, className, ...props }) {
  return (
    <motion.div className={className} {...props}>
      {children}
    </motion.div>
  )
}

export default AnimatedContainer

import { motion, useReducedMotion } from 'motion/react'

/**
 * Small wrapper that lifts its child on hover.
 *
 * Usage:
 *   <HoverLift y={-5}>{children}</HoverLift>
 *   <HoverLift as={motion.button}>...</HoverLift>
 *
 * Respects prefers-reduced-motion: the lift collapses to 0 so there's
 * no movement at all when the user has opted out.
 */
export default function HoverLift({
  children,
  y = -5,
  as,
  className,
  ...props
}) {
  const reduce = useReducedMotion()
  const Component = as || motion.div

  return (
    <Component
      whileHover={{ y: reduce ? 0 : y }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className={className}
      {...props}
    >
      {children}
    </Component>
  )
}

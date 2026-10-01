import { motion, useReducedMotion } from 'motion/react'
import { LANDING_SURFACE } from '../lib/landingStyles'

const PAD = { lg: 'p-8', md: 'p-6', sm: 'p-5' }

/**
 * Bento feature card. Icon sits inline-start of the title (no tinted tile above).
 * Hover affordance comes from LANDING_SURFACE itself (border brighten + warm glow);
 * we only add a small lift. 'lg' cards carry an aria-hidden decorative motif in the
 * lower area (org-tree for the holding-model card).
 *
 * @param {{ icon: import('lucide-react').LucideIcon, title: string,
 *   description: string, size?: 'lg' | 'md' | 'sm', motif?: 'org-tree' }} props
 */
export default function FeatureCard({ icon: Icon, title, description, size = 'md', motif }) {
  const reduceMotion = useReducedMotion()

  return (
    <motion.div
      whileHover={reduceMotion ? undefined : { y: -3 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={`${LANDING_SURFACE} ${PAD[size]} flex h-full flex-col overflow-hidden`}
    >
      <div className="flex items-center gap-2.5">
        <Icon className="size-4 shrink-0 text-foreground-tertiary" aria-hidden="true" />
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
      </div>

      <p
        className={`mt-3 text-sm leading-relaxed text-foreground-secondary ${
          size === 'lg' ? 'max-w-md' : ''
        }`}
      >
        {description}
      </p>

      {motif === 'org-tree' && <OrgTreeMotif />}
    </motion.div>
  )
}

/**
 * Subtle holding-model org tree: one root, two managers, four leaves, linked by
 * hairlines. Pure divs + borders, accent dots. Decorative only.
 */
function OrgTreeMotif() {
  const dot = 'size-2 rounded-full bg-accent/70 shadow-[0_0_10px_hsl(var(--accent)/0.5)]'
  const leaf = 'size-1.5 rounded-full bg-foreground-tertiary/60'
  const hair = 'bg-white/[0.08]'

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none mt-auto flex flex-col items-center pt-10 opacity-80 select-none"
    >
      {/* root */}
      <div className={dot} />
      {/* trunk */}
      <div className={`h-5 w-px ${hair}`} />
      {/* horizontal bus feeding the two managers */}
      <div className={`h-px w-32 ${hair}`} />
      <div className="flex w-32 justify-between">
        <div className={`h-4 w-px ${hair}`} />
        <div className={`h-4 w-px ${hair}`} />
      </div>
      <div className="flex w-32 justify-between">
        {/* manager A subtree */}
        <div className="flex flex-col items-center">
          <div className={dot} />
          <div className={`h-3 w-px ${hair}`} />
          <div className={`h-px w-12 ${hair}`} />
          <div className="flex w-12 justify-between">
            <div className={`h-3 w-px ${hair}`} />
            <div className={`h-3 w-px ${hair}`} />
          </div>
          <div className="flex w-12 justify-between">
            <div className={leaf} />
            <div className={leaf} />
          </div>
        </div>
        {/* manager B subtree */}
        <div className="flex flex-col items-center">
          <div className={dot} />
          <div className={`h-3 w-px ${hair}`} />
          <div className={`h-px w-12 ${hair}`} />
          <div className="flex w-12 justify-between">
            <div className={`h-3 w-px ${hair}`} />
            <div className={`h-3 w-px ${hair}`} />
          </div>
          <div className="flex w-12 justify-between">
            <div className={leaf} />
            <div className={leaf} />
          </div>
        </div>
      </div>
    </div>
  )
}

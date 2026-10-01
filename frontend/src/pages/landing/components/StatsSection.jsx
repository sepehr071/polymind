import { motion, useReducedMotion } from 'motion/react'
import { useTranslation } from 'react-i18next'
import { useCountUp } from '@/hooks/useCountUp'
import { fmtNumber } from '@/utils/persianLocale'
import { revealVariants, viewportOnce } from '../lib/landingStyles'

/**
 * Inline count-up rendered before its word. The hook snaps straight to `end`
 * under reduced motion, so the figure is always legible. Digits follow the
 * user's Persian/Latin numeral preference via `fmtNumber` (never raw
 * `.toLocaleString()`).
 */
function CountSegment({ end, word }) {
  const { count, ref } = useCountUp(end, 2000, true)

  return (
    <motion.span ref={ref} variants={revealVariants} className="inline-flex items-baseline gap-x-3">
      <span className="text-accent tabular-nums">{fmtNumber(count)}</span>
      <span>{word}</span>
    </motion.span>
  )
}

/* Orchestrates the segment cascade — staggerChildren only fires from inside a
   resolved variant transition, not a top-level `transition` prop. */
const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.15 } },
}

/**
 * Editorial stat line — the former 4-tile grid distilled to one typographic
 * statement. Segment-level entrance stagger; pure base background (no aurora,
 * no orbs). Type leans on `font-display` so FA falls back to Vazirmatn.
 */
export default function StatsSection() {
  const { t } = useTranslation('landing')
  const reduceMotion = useReducedMotion()

  return (
    <section className="relative px-6 py-[clamp(6rem,15vh,11rem)]">
      <div className="landing-noise" aria-hidden="true" />

      <motion.div
        className="relative mx-auto flex max-w-4xl flex-wrap justify-center gap-x-3 gap-y-2 text-center font-display text-[clamp(1.75rem,4vw,3.25rem)] font-bold leading-tight text-foreground"
        variants={containerVariants}
        initial={reduceMotion ? false : 'hidden'}
        whileInView="visible"
        viewport={viewportOnce}
      >
        <motion.span variants={revealVariants}>
          {t('stats.statement.workspace')}
        </motion.span>

        <CountSegment end={7} word={t('stats.statement.tools')} />

        <CountSegment end={3} word={t('stats.statement.governance')} />

        <motion.span variants={revealVariants}>
          {t('stats.statement.subscriptions')}
        </motion.span>
      </motion.div>
    </section>
  )
}

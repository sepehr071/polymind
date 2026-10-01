import { useRef } from 'react'
import { motion, useScroll, useTransform, useReducedMotion } from 'motion/react'
import { useTranslation } from 'react-i18next'
import { ShieldCheck, Building2, Sparkles } from 'lucide-react'
import { useLanguage } from '@/context/LanguageContext'
import { toPersianDigits } from '@/utils/persianLocale'
import {
  EYEBROW_EN,
  EYEBROW_FA,
  H2_CLASS,
  revealVariants,
  viewportOnce,
} from '../lib/landingStyles'

/**
 * HowItWorks — three numbered steps, editorial and quiet.
 * Oversized thin numerals carry the rhythm; a desktop-only gradient hairline
 * draws itself in behind the row as the section enters view. No aurora here so
 * the page breathes darker between the ProductShowcase and the StatLine.
 */

const STEPS = [
  { key: 'signin', icon: ShieldCheck },
  { key: 'workspace', icon: Building2 },
  { key: 'work', icon: Sparkles },
]

// Parent container: drives the staggered child reveal below the fold.
const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12, delayChildren: 0.05 } },
}

export default function HowItWorksSection() {
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const reduceMotion = useReducedMotion()

  const ref = useRef(null)
  // Third (and final) page-wide useScroll subscription — see motion budget.
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'center center'],
  })
  const scaleX = useTransform(scrollYProgress, [0, 1], [0, 1])

  return (
    <section
      ref={ref}
      className="relative overflow-hidden bg-background py-[clamp(5rem,12vh,9rem)]"
    >
      <div className="landing-noise" aria-hidden="true" />

      <div className="relative mx-auto max-w-5xl px-6">
        {/* Header */}
        <motion.div
          variants={revealVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          className="mb-[clamp(3rem,7vh,5rem)] text-center"
        >
          <p className={isRTL ? EYEBROW_FA : EYEBROW_EN}>{t('how.badge')}</p>
          <h2 className={`${H2_CLASS} font-display mt-4 text-foreground`}>
            {t('how.title')}
          </h2>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-foreground-secondary">
            {t('how.subtitle')}
          </p>
        </motion.div>

        {/* Steps */}
        <div className="relative">
          {/* Desktop-only connector: gradient hairline behind/above the numerals
              row, drawn from the inline-start edge as the section scrolls in. */}
          <motion.div
            aria-hidden="true"
            className="absolute inset-x-0 top-[clamp(1.5rem,3vw,2.25rem)] hidden h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent md:block"
            style={
              reduceMotion
                ? undefined
                : { scaleX, transformOrigin: isRTL ? 'right' : 'left' }
            }
          />

          <motion.ol
            variants={containerVariants}
            initial={reduceMotion ? false : 'hidden'}
            whileInView="visible"
            viewport={viewportOnce}
            className="grid gap-10 md:grid-cols-3"
          >
            {STEPS.map((step, i) => {
              const Icon = step.icon
              // Zero-pad in Latin, then localize the digit script (۰۱ for fa
              // when Persian numerals are on, 01 otherwise).
              const numeral = toPersianDigits('0' + (i + 1))

              return (
                <motion.li
                  key={step.key}
                  variants={revealVariants}
                  className="relative"
                >
                  <span
                    aria-hidden="true"
                    className="block font-display text-[clamp(3rem,6vw,4.5rem)] font-extralight leading-none text-foreground-tertiary"
                  >
                    {numeral}
                  </span>

                  <h3 className="mt-6 flex items-center gap-2 text-lg font-semibold text-foreground">
                    <Icon className="size-4 shrink-0 text-foreground-tertiary" aria-hidden="true" />
                    {t(`how.steps.${step.key}.title`)}
                  </h3>

                  <p className={`mt-3 text-sm leading-relaxed text-foreground-secondary ${isRTL ? '' : 'font-light'}`}>
                    {t(`how.steps.${step.key}.description`)}
                  </p>
                </motion.li>
              )
            })}
          </motion.ol>
        </div>
      </div>
    </section>
  )
}

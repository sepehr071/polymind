import { useMemo } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { ArrowRight, Check, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLanguage } from '@/context/LanguageContext'
import { useCoarsePointer } from '@/hooks/useMediaQuery'
import {
  LANDING_SURFACE,
  AURORA_CTA,
  EYEBROW_EN,
  EYEBROW_FA,
  revealVariants,
  viewportOnce,
  easeOutExpo,
} from '../lib/landingStyles'
import { useAppEntry } from '../lib/useAppEntry'

export default function CTASection() {
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const reduceMotion = useReducedMotion()
  const coarse = useCoarsePointer()
  const { isAuthed, href } = useAppEntry()

  // Compute particle positions/timings ONCE so they stay stable across renders
  // (an inline Math.random() per render reshuffles every dot every paint).
  const particles = useMemo(
    () =>
      Array.from({ length: 12 }, (_, i) => ({
        left: `${Math.random() * 100}%`,
        top: `${Math.random() * 100}%`,
        // alternate sky / warm lamp tint
        tint:
          i % 2 === 0
            ? 'hsl(var(--accent) / 0.5)'
            : 'hsl(var(--landing-warm) / 0.5)',
        duration: 7 + Math.random() * 4,
        delay: Math.random() * 3,
      })),
    []
  )

  const trustItems = [
    { key: 'no_card', label: t('cta.trust.no_card') },
    { key: 'free', label: t('cta.trust.free') },
    { key: 'open_source', label: t('cta.trust.open_source') },
  ]

  return (
    <section className="relative overflow-hidden py-[clamp(5rem,12vh,9rem)]">
      {/* Static warm-pocket aurora — no infinite background animation */}
      <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
        <div className="absolute inset-0" style={AURORA_CTA} />
      </div>
      <div className="landing-noise" aria-hidden="true" />

      {/* Floating particle dots — the one tolerated ambient motion, gated on motion pref
          and skipped on coarse pointers (phones never run 12 repeat:Infinity springs) */}
      {!reduceMotion && !coarse && (
        <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
          {particles.map((p, i) => (
            <motion.span
              key={i}
              className="absolute size-1 rounded-full"
              style={{ left: p.left, top: p.top, backgroundColor: p.tint }}
              animate={{ y: [0, -24, 0], opacity: [0.25, 0.6, 0.25] }}
              transition={{
                duration: p.duration,
                repeat: Infinity,
                delay: p.delay,
                ease: 'easeInOut',
              }}
            />
          ))}
        </div>
      )}

      <div className="relative mx-auto max-w-3xl px-6">
        <motion.div
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          variants={revealVariants}
          className={`${LANDING_SURFACE} p-10 text-center sm:p-14`}
        >
          {/* Eyebrow */}
          <span
            className={`inline-flex items-center gap-2 ${isRTL ? EYEBROW_FA : EYEBROW_EN}`}
          >
            <Sparkles className="size-4 text-accent" aria-hidden="true" />
            {t('cta.badge')}
          </span>

          {/* Heading — solid, no gradient */}
          <h2 className="mt-5 font-display font-bold text-[clamp(2rem,4.5vw,3.75rem)] leading-tight text-foreground">
            {t('cta.title')}
          </h2>

          <p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-foreground-secondary">
            {t('cta.subtitle')}
          </p>

          {/* CTAs */}
          <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Button asChild size="lg" className="group px-8">
              <Link to={href}>
                <span className="flex items-center">
                  {isAuthed ? t('navbar.enter_app') : t('cta.primary')}
                  <ArrowRight
                    className="ms-1 size-4 transition-transform duration-300 group-hover:translate-x-1 rtl:group-hover:-translate-x-1"
                    aria-hidden="true"
                  />
                </span>
              </Link>
            </Button>
            <Button asChild variant="outline" size="lg" className="group">
              <Link to="/login">
                <span className="transition-colors group-hover:text-accent">
                  {t('cta.secondary')}
                </span>
              </Link>
            </Button>
          </div>

          {/* Trust indicators — staggered reveal, checkmarks spring in */}
          <div className="mt-10 flex flex-wrap justify-center gap-x-6 gap-y-3">
            {trustItems.map((item, i) => (
              <motion.div
                key={item.key}
                initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={viewportOnce}
                transition={{ delay: 0.3 + i * 0.1, duration: 0.5, ease: easeOutExpo }}
                className="flex items-center gap-2 text-sm text-foreground-secondary"
              >
                <motion.span
                  initial={reduceMotion ? false : { scale: 0 }}
                  whileInView={{ scale: 1 }}
                  viewport={viewportOnce}
                  transition={{ delay: 0.4 + i * 0.1, type: 'spring', stiffness: 300, damping: 18 }}
                  className="flex size-5 items-center justify-center rounded-full bg-accent/10"
                >
                  <Check className="size-3 text-accent" aria-hidden="true" />
                </motion.span>
                <span>{item.label}</span>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}

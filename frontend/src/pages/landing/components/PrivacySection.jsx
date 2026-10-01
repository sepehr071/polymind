import { motion, useReducedMotion } from 'motion/react'
import { useTranslation } from 'react-i18next'
import {
  Lock,
  Server,
  ShieldCheck,
  Building2,
  MessageSquare,
  BookOpen,
  Cloud,
  Ban,
} from 'lucide-react'
import { useLanguage } from '@/context/LanguageContext'
import {
  EYEBROW_EN,
  EYEBROW_FA,
  H2_CLASS,
  revealVariants,
  viewportOnce,
  easeOutExpo,
} from '../lib/landingStyles'

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
}

// Cool (sky + teal) backdrop — deliberately distinct from the warm sections so
// the security beat reads as a calm, trustworthy pocket in the scroll.
const COOL_AURORA = {
  backgroundImage:
    'radial-gradient(40rem 40rem at 18% 12%, hsl(var(--accent) / 0.10), transparent 60%), ' +
    'radial-gradient(34rem 34rem at 85% 88%, hsl(var(--teal) / 0.08), transparent 60%)',
}

const PILLARS = [
  { key: 'residency', icon: Lock, tone: 'text-accent bg-accent/15' },
  { key: 'local', icon: Server, tone: 'text-teal bg-[hsl(var(--teal)/0.15)]' },
  {
    key: 'dlp',
    icon: ShieldCheck,
    tone: 'text-[hsl(var(--landing-warm))] bg-[hsl(var(--landing-warm)/0.15)]',
  },
]

const BOUNDARY_CHIPS = [
  { key: 'chat', icon: MessageSquare, tone: 'text-accent bg-accent/15' },
  { key: 'knowledge', icon: BookOpen, tone: 'text-teal bg-[hsl(var(--teal)/0.15)]' },
  {
    key: 'model',
    icon: Server,
    tone: 'text-[hsl(var(--landing-warm))] bg-[hsl(var(--landing-warm)/0.15)]',
  },
]

// "Data stays inside the company" diagram: a dashed company boundary holding the
// chat / knowledge / local-model surfaces, a DLP scan badge on its edge, then a
// blocked link down to the public internet. Decorative + labelled, RTL-safe.
function PrivacyDiagram({ t }) {
  return (
    <div className="flex w-full max-w-sm flex-col items-center">
      {/* Company boundary */}
      <div className="w-full rounded-2xl border border-dashed border-accent/30 bg-accent/[0.04] p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-2 text-xs font-semibold text-foreground">
            <Building2 className="size-4 text-accent" aria-hidden="true" />
            {t('privacy.diagram.company')}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] text-foreground-secondary">
            <ShieldCheck className="size-3 text-[hsl(var(--landing-warm))]" aria-hidden="true" />
            {t('privacy.diagram.scan')}
          </span>
        </div>
        <div className="grid gap-2">
          {BOUNDARY_CHIPS.map((c) => (
            <div
              key={c.key}
              className="flex items-center gap-2.5 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2"
            >
              <span className={`grid size-7 shrink-0 place-items-center rounded-lg ${c.tone}`}>
                <c.icon className="size-3.5" aria-hidden="true" />
              </span>
              <span className="text-xs font-medium text-foreground">
                {t(`privacy.diagram.${c.key}`)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Blocked link to the outside */}
      <span className="h-4 w-px bg-white/15" aria-hidden="true" />
      <span className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] bg-background px-2.5 py-1 text-[11px] font-medium text-foreground-secondary">
        <Ban className="size-3.5 text-foreground-tertiary" aria-hidden="true" />
        {t('privacy.diagram.blocked')}
      </span>
      <span className="h-4 w-px bg-white/[0.08]" aria-hidden="true" />

      {/* Public internet — faded, outside the walls */}
      <div className="flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-white/10 px-4 py-3 opacity-60">
        <Cloud className="size-4 text-foreground-tertiary" aria-hidden="true" />
        <span className="text-xs text-foreground-tertiary">
          {t('privacy.diagram.external')}
        </span>
      </div>
    </div>
  )
}

export default function PrivacySection() {
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const reduceMotion = useReducedMotion()
  const eyebrowClass = isRTL ? EYEBROW_FA : EYEBROW_EN

  return (
    <section id="privacy" className="relative overflow-hidden px-6 py-[clamp(5rem,12vh,9rem)]">
      <div className="absolute inset-0 pointer-events-none" style={COOL_AURORA} aria-hidden="true" />
      <div className="landing-noise" aria-hidden="true" />

      <div className="relative mx-auto grid max-w-6xl items-center gap-12 lg:grid-cols-2">
        {/* Content */}
        <motion.div
          variants={containerVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
        >
          <motion.span variants={revealVariants} className={`block ${eyebrowClass}`}>
            {t('privacy.badge')}
          </motion.span>
          <motion.h2
            variants={revealVariants}
            className={`mt-4 font-display text-foreground ${H2_CLASS}${isRTL ? '' : ' tracking-[-0.02em]'}`}
          >
            {t('privacy.title')}
          </motion.h2>
          <motion.p
            variants={revealVariants}
            className="mt-4 text-lg font-light leading-relaxed text-foreground-secondary"
          >
            {t('privacy.subtitle')}
          </motion.p>

          <div className="mt-8 flex flex-col gap-5">
            {PILLARS.map((p) => (
              <motion.div key={p.key} variants={revealVariants} className="flex items-start gap-3.5">
                <span className={`grid size-9 shrink-0 place-items-center rounded-xl ${p.tone}`}>
                  <p.icon className="size-4" aria-hidden="true" />
                </span>
                <div>
                  <h3 className="text-base font-semibold text-foreground">
                    {t(`privacy.pillars.${p.key}.title`)}
                  </h3>
                  <p className="mt-1 text-sm leading-relaxed text-foreground-secondary">
                    {t(`privacy.pillars.${p.key}.description`)}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Visual: inset screen well + the data-residency diagram */}
        <motion.div
          variants={revealVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          transition={{ duration: 0.7, ease: easeOutExpo }}
          className="flex justify-center"
        >
          <div className="relative flex w-full max-w-md justify-center overflow-hidden rounded-2xl border border-white/[0.06] bg-black/[0.18] p-6 sm:p-9">
            <div
              aria-hidden="true"
              className="absolute inset-0 pointer-events-none"
              style={{
                backgroundImage:
                  'radial-gradient(20rem 20rem at 50% 30%, hsl(var(--accent) / 0.12), transparent 62%)',
              }}
            />
            <div className="relative z-10 w-full">
              <PrivacyDiagram t={t} />
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  )
}

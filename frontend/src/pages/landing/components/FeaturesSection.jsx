import { motion, useReducedMotion } from 'motion/react'
import { useTranslation } from 'react-i18next'
import {
  MessageSquare,
  GitBranch,
  BookOpen,
  Code,
  Building2,
  ShieldCheck,
  Wallet,
} from 'lucide-react'
import FeatureCard from './FeatureCard'
import { useLanguage } from '@/context/LanguageContext'
import {
  AURORA_MID,
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

/**
 * Bento packing (lg:grid-cols-6, zero holes):
 *   [ roles 3×2 (LG, org-tree motif) | dlp 3 ]
 *   [ roles cont.                    | workflows 3 ]
 *   [ cost 2 | chat 2 | knowledge 2 ]
 *   [ canvas 6 (slim closing strip) ]
 * roles anchors a 2-row tower on the inline-start; the right column stacks the two
 * governance/automation pillars beside it; a supporting triad; canvas spans full
 * width to close. Mobile collapses to one column in this DOM order.
 */
const FEATURES = [
  { icon: Building2, key: 'roles', size: 'lg', span: 'lg:col-span-3 lg:row-span-2', motif: 'org-tree' },
  { icon: ShieldCheck, key: 'dlp', size: 'md', span: 'lg:col-span-3' },
  { icon: GitBranch, key: 'workflows', size: 'md', span: 'lg:col-span-3' },
  { icon: Wallet, key: 'cost', size: 'sm', span: 'lg:col-span-2' },
  { icon: MessageSquare, key: 'chat', size: 'sm', span: 'lg:col-span-2' },
  { icon: BookOpen, key: 'knowledge', size: 'sm', span: 'lg:col-span-2' },
  { icon: Code, key: 'canvas', size: 'md', span: 'lg:col-span-6' },
]

export default function FeaturesSection() {
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const reduceMotion = useReducedMotion()

  return (
    <section
      id="features"
      className="relative overflow-hidden px-6 py-[clamp(5rem,12vh,9rem)]"
    >
      <div className="absolute inset-0 pointer-events-none" style={AURORA_MID} aria-hidden="true" />
      <div className="landing-noise" aria-hidden="true" />

      <div className="relative mx-auto max-w-7xl">
        {/* Header, start-aligned */}
        <motion.div
          variants={containerVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          className="mb-12 max-w-2xl text-start"
        >
          <motion.span variants={revealVariants} className={`block ${isRTL ? EYEBROW_FA : EYEBROW_EN}`}>
            {t('features.badge')}
          </motion.span>
          <motion.h2
            variants={revealVariants}
            className={`mt-4 font-display text-foreground ${H2_CLASS}${
              isRTL ? '' : ' tracking-[-0.02em]'
            }`}
          >
            {t('features.title')}
          </motion.h2>
          <motion.p
            variants={revealVariants}
            className="mt-4 text-lg font-light leading-relaxed text-foreground-secondary"
          >
            {t('features.subtitle')}
          </motion.p>
        </motion.div>

        {/* Bento */}
        <motion.div
          variants={containerVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          className="grid grid-cols-1 gap-4 lg:auto-rows-fr lg:grid-cols-6"
        >
          {FEATURES.map(({ icon, key, size, span, motif }) => (
            <motion.div
              key={key}
              variants={revealVariants}
              transition={{ duration: 0.7, ease: easeOutExpo }}
              className={span}
            >
              <FeatureCard
                icon={icon}
                title={t(`features.items.${key}.title`)}
                description={t(`features.items.${key}.description`)}
                size={size}
                motif={motif}
              />
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}

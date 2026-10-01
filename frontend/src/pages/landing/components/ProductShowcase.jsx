import { useRef } from 'react'
import {
  motion,
  useScroll,
  useTransform,
  useSpring,
  useReducedMotion,
} from 'motion/react'
import { useTranslation } from 'react-i18next'
import {
  MessageSquare,
  Workflow,
  BookOpen,
  ArrowUp,
  Sparkles,
  Check,
} from 'lucide-react'
import { useLanguage } from '@/context/LanguageContext'
import { useCoarsePointer } from '@/hooks/useMediaQuery'
import {
  LANDING_GLASS,
  LANDING_GLASS_SOLID,
  LANDING_SURFACE,
  AURORA_MID,
  EYEBROW_EN,
  EYEBROW_FA,
  H2_CLASS,
  revealVariants,
  viewportOnce,
} from '../lib/landingStyles'

/** One faux sidebar nav row. Active row carries a sky tint; rest stay muted. */
function NavRow({ icon: Icon, label, active }) {
  return (
    <div
      className={
        'flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs ' +
        (active
          ? 'bg-accent/15 text-accent'
          : 'text-foreground-tertiary')
      }
    >
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </div>
  )
}

export default function ProductShowcase() {
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const reduceMotion = useReducedMotion()
  const coarse = useCoarsePointer()
  const motionOff = reduceMotion || coarse
  const ref = useRef(null)

  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  })

  // Window lifts as it crosses the viewport; tilt flattens by mid-scroll.
  const windowYRaw = useTransform(scrollYProgress, [0, 1], [60, -60])
  const windowY = useSpring(windowYRaw, { stiffness: 80, damping: 20 })
  const rotateX = useTransform(scrollYProgress, [0, 0.5], [8, 0])

  // Warm lamp orb drifts up and shrinks behind the frame.
  const orbY = useTransform(scrollYProgress, [0, 1], [0, -120])
  const orbScale = useTransform(scrollYProgress, [0, 1], [1.1, 0.9])

  // Two abstract chips floating around the window, staggered depths.
  const chipAY = useTransform(scrollYProgress, [0, 1], [40, -80])
  const chipBY = useTransform(scrollYProgress, [0, 1], [20, -50])

  return (
    <section className="relative overflow-hidden py-[clamp(5rem,12vh,9rem)]">
      <div
        className="absolute inset-0 pointer-events-none"
        style={AURORA_MID}
        aria-hidden="true"
      />
      <div className="landing-noise" aria-hidden="true" />

      <div className="relative mx-auto max-w-6xl px-6">
        {/* Section header */}
        <motion.div
          variants={revealVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          className="mx-auto mb-14 max-w-2xl text-center"
        >
          <span className={isRTL ? EYEBROW_FA : EYEBROW_EN}>
            {t('showcase.badge')}
          </span>
          <h2 className={`${H2_CLASS} font-display mt-4 text-foreground`}>
            {t('showcase.title')}
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-foreground-secondary">
            {t('showcase.subtitle')}
          </p>
        </motion.div>

        {/* Mock stage */}
        <motion.div
          variants={revealVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          className={`relative mx-auto max-w-4xl ${coarse ? '' : '[perspective:1200px]'}`}
        >
          {/* Warm glow orb behind the window */}
          <motion.div
            className="absolute start-1/2 top-1/2 -z-10 h-[26rem] w-[26rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[hsl(var(--landing-warm)/0.18)] blur-[120px] max-md:h-[18rem] max-md:w-[18rem] max-md:blur-[55px]"
            style={motionOff ? undefined : { y: orbY, scale: orbScale }}
            aria-hidden="true"
          />

          {/* Floating abstract chips */}
          <motion.div
            className={`${LANDING_SURFACE} absolute -top-5 end-6 z-10 hidden items-center justify-center p-2.5 sm:flex`}
            style={motionOff ? undefined : { y: chipAY }}
            aria-hidden="true"
          >
            <Sparkles className="size-4 text-accent" />
          </motion.div>
          <motion.div
            className={`${LANDING_SURFACE} absolute -bottom-4 start-8 z-10 hidden items-center justify-center p-2.5 sm:flex`}
            style={motionOff ? undefined : { y: chipBY }}
            aria-hidden="true"
          >
            <Check className="size-4 text-teal" />
          </motion.div>

          {/* GLASS MOMENT 2: the mock window */}
          <motion.div
            className={`${coarse ? LANDING_GLASS_SOLID : LANDING_GLASS} overflow-hidden`}
            style={motionOff ? undefined : { y: windowY, rotateX }}
          >
            {/* Window chrome bar */}
            <div className="flex items-center border-b border-white/[0.06] px-4 py-3">
              <div className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full bg-white/[0.12]" />
                <span className="size-2.5 rounded-full bg-white/[0.12]" />
                <span className="size-2.5 rounded-full bg-white/[0.12]" />
              </div>
              <span
                dir="ltr"
                className="flex-1 text-center text-xs font-medium text-foreground-tertiary"
              >
                {t('showcase.mock.title')}
              </span>
              {/* Spacer mirrors the dots cluster to keep the title centered */}
              <div className="w-[42px]" aria-hidden="true" />
            </div>

            {/* Body grid: sidebar hint + conversation */}
            <div className="flex">
              <div className="hidden w-44 shrink-0 flex-col gap-1 border-e border-white/[0.06] p-3 md:flex">
                <NavRow
                  icon={MessageSquare}
                  label={t('showcase.mock.nav_chat')}
                  active
                />
                <NavRow
                  icon={Workflow}
                  label={t('showcase.mock.nav_workflows')}
                />
                <NavRow
                  icon={BookOpen}
                  label={t('showcase.mock.nav_knowledge')}
                />
              </div>

              <div className="flex min-h-[340px] flex-1 flex-col gap-3 p-4 sm:p-6">
                {/* User bubble */}
                <div className="self-end rounded-2xl rounded-ee-md border border-accent/20 bg-accent/20 px-4 py-2.5 text-sm text-foreground max-w-[80%]">
                  {t('showcase.mock.user_message')}
                </div>

                {/* Assistant bubble */}
                <div className="self-start rounded-2xl rounded-ss-md border border-white/[0.06] bg-white/[0.04] px-4 py-3 text-sm leading-relaxed text-foreground-secondary max-w-[85%]">
                  <p>{t('showcase.mock.assistant_line_1')}</p>
                  <p className="mt-1.5">
                    {t('showcase.mock.assistant_line_2')}
                  </p>
                  <div
                    className={`mt-3 h-3.5 w-2/3 rounded-full ${coarse ? 'bg-white/[0.06]' : 'animate-shimmer'}`}
                    aria-hidden="true"
                  />
                </div>

                {/* Faux composer */}
                <div className="mt-auto flex items-center gap-2 rounded-full border border-white/[0.06] bg-white/[0.04] py-2 ps-4 pe-2">
                  <span className="flex-1 truncate text-sm text-foreground-tertiary">
                    {t('showcase.mock.composer_placeholder')}
                  </span>
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-background">
                    <ArrowUp className="size-4 rtl:-scale-x-100" aria-hidden="true" />
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

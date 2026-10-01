import { Suspense, useState, useEffect, useRef } from 'react'
import {
  motion,
  useScroll,
  useTransform,
  useSpring,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
} from 'motion/react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import lazyWithRetry from '@/utils/lazyWithRetry'
import { ArrowRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLanguage } from '@/context/LanguageContext'
import { useCoarsePointer } from '@/hooks/useMediaQuery'
import { AURORA_HERO, LANDING_SURFACE, easeOutExpo } from '../lib/landingStyles'
import { useAppEntry } from '../lib/useAppEntry'

// three.js + @react-three/fiber/drei/postprocessing (~1.6MB) lands in its own
// on-demand chunk so it never blocks the hero paint on this invite-only landing.
const ParticleBackground = lazyWithRetry(() => import('@/components/landing/ParticleBackground'))

// Static, WebGL-free aurora shown as the Suspense fallback AND as the permanent
// background for mobile / reduced-motion users (Canvas never mounts for them).
function StaticHeroBackground() {
  return (
    <div className="absolute inset-0 overflow-hidden" style={{ zIndex: 0 }} aria-hidden="true">
      <div className="absolute inset-0 pointer-events-none" style={AURORA_HERO} />
      <div className="landing-noise" aria-hidden="true" />
    </div>
  )
}

// Per-word blur-in for the display headline. Words animate y/opacity/filter only.
const wordVariants = {
  hidden: { opacity: 0, y: 24, filter: 'blur(8px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.7, ease: easeOutExpo },
  },
}

function HeadlineWords({ text, className }) {
  const words = text.split(' ')
  return words.map((word, i) => (
    <motion.span key={`${word}-${i}`} variants={wordVariants} className={`inline-block ${className}`}>
      {word}
      {i < words.length - 1 ? ' ' : ''}
    </motion.span>
  ))
}

// Interactive hero cursor: a springy accent ring + instant dot + a soft
// spotlight glow that trail the pointer. Pointer-events-none so it never blocks
// clicks; the ring swells over links/buttons. Mounted only on fine-pointer,
// motion-enabled viewports (see enableCursor) — touch/reduced-motion keep the
// native cursor.
function HeroCursor({ containerRef }) {
  const x = useMotionValue(-200)
  const y = useMotionValue(-200)
  const ringX = useSpring(x, { stiffness: 320, damping: 28, mass: 0.5 })
  const ringY = useSpring(y, { stiffness: 320, damping: 28, mass: 0.5 })
  const [visible, setVisible] = useState(false)
  const [active, setActive] = useState(false)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onMove = (e) => {
      x.set(e.clientX)
      y.set(e.clientY)
      setActive(!!(e.target instanceof Element && e.target.closest('a, button')))
    }
    const onEnter = () => setVisible(true)
    const onLeave = () => setVisible(false)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerenter', onEnter)
    el.addEventListener('pointerleave', onLeave)
    return () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerenter', onEnter)
      el.removeEventListener('pointerleave', onLeave)
    }
  }, [containerRef, x, y])

  return (
    <div aria-hidden="true" className="pointer-events-none">
      {/* Spotlight glow — lags behind on a soft spring */}
      <motion.div
        className="fixed left-0 top-0 z-[60] rounded-full"
        style={{
          x: ringX,
          y: ringY,
          marginLeft: -150,
          marginTop: -150,
          width: 300,
          height: 300,
          background: 'radial-gradient(circle, hsl(var(--accent) / 0.10), transparent 60%)',
        }}
        animate={{ opacity: visible ? 1 : 0 }}
        transition={{ duration: 0.3 }}
      />
      {/* Ring — springs toward the pointer, swells over interactive targets */}
      <motion.div
        className="fixed left-0 top-0 z-[61] rounded-full border border-accent/60"
        style={{ x: ringX, y: ringY, marginLeft: -16, marginTop: -16, width: 32, height: 32 }}
        animate={{ opacity: visible ? 1 : 0, scale: active ? 1.6 : 1 }}
        transition={{ opacity: { duration: 0.2 }, scale: { duration: 0.2, ease: easeOutExpo } }}
      />
      {/* Dot — tracks the pointer exactly (no spring) */}
      <motion.div
        className="fixed left-0 top-0 z-[62] rounded-full bg-accent"
        style={{ x, y, marginLeft: -3, marginTop: -3, width: 6, height: 6 }}
        animate={{ opacity: visible ? 1 : 0 }}
        transition={{ duration: 0.15 }}
      />
    </div>
  )
}

export default function HeroSection() {
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const { isAuthed, href } = useAppEntry()
  const reduceMotion = useReducedMotion()
  const coarse = useCoarsePointer()
  // Entrance reveals stay ON for coarse (cheap, one-shot); only scroll-linked
  // parallax springs + transforms are short-circuited on touch/mobile.
  const motionOff = reduceMotion || coarse
  // Custom hero cursor: fine pointer + motion only (never touch / reduced-motion).
  const enableCursor = !motionOff

  // Only mount the heavy 3D Canvas on a wide viewport with motion enabled.
  // Mobile (<1024px) and reduced-motion users get the static aurora only;
  // the three.js chunk is never fetched for them.
  const [enableParticles, setEnableParticles] = useState(false)
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const wide = window.matchMedia('(min-width: 1024px)')
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    const evaluate = () => setEnableParticles(wide.matches && !reduced.matches)
    evaluate()
    wide.addEventListener('change', evaluate)
    reduced.addEventListener('change', evaluate)
    return () => {
      wide.removeEventListener('change', evaluate)
      reduced.removeEventListener('change', evaluate)
    }
  }, [])

  // Scroll parallax: one useScroll subscription (hero's share of the page budget).
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] })

  // Plain ref bridged to the WebGL camera (0..1), driven off the scroll value
  // without re-rendering React. ParticleBackground reads scrollRef.current each frame.
  const scrollProgress = useRef(0)
  useMotionValueEvent(scrollYProgress, 'change', (v) => {
    scrollProgress.current = v
  })

  // Headline group: springed y + scale, crisp (un-springed) opacity for a clean fade.
  const headlineYRaw = useTransform(scrollYProgress, [0, 1], [0, -80])
  const headlineScaleRaw = useTransform(scrollYProgress, [0, 1], [1, 0.96])
  const headlineY = useSpring(headlineYRaw, { stiffness: 80, damping: 20 })
  const headlineScale = useSpring(headlineScaleRaw, { stiffness: 80, damping: 20 })
  const headlineOpacity = useTransform(scrollYProgress, [0, 0.6], [1, 0])

  // Floating decorative micro-elements (near / mid / far), plain transforms.
  const floatNearY = useTransform(scrollYProgress, [0, 1], [0, -160])
  const floatMidY = useTransform(scrollYProgress, [0, 1], [0, -90])
  const floatFarY = useTransform(scrollYProgress, [0, 1], [0, -40])

  // Scroll indicator fades out early.
  const indicatorOpacity = useTransform(scrollYProgress, [0, 0.15], [1, 0])

  const scrollToDemo = () => {
    document.getElementById('demo')?.scrollIntoView({ behavior: 'smooth' })
  }

  const pills = [
    t('hero.pills.privacy'),
    t('hero.pills.local'),
    t('hero.pills.safety'),
    t('hero.pills.access'),
  ]

  return (
    <section
      ref={ref}
      className={`landing-dark relative min-h-screen flex items-center overflow-hidden bg-background py-[clamp(6rem,14vh,10rem)] ${
        enableCursor ? 'cursor-none' : ''
      }`}
    >
      {/* Single aurora layer for every viewport; the transparent WebGL canvas
          (wide + motion-enabled only) paints the particle field on top of it. */}
      <StaticHeroBackground />
      {enableParticles && (
        <Suspense fallback={null}>
          <ParticleBackground scrollRef={scrollProgress} />
        </Suspense>
      )}

      {/* Interactive cursor (ring + dot + spotlight) — desktop, motion-on only */}
      {enableCursor && <HeroCursor containerRef={ref} />}

      {/* Bottom fade into the next section. */}
      <div className="absolute bottom-0 start-0 end-0 h-40 bg-gradient-to-t from-background to-transparent pointer-events-none" />

      {/* Decorative floating surfaces, weighted toward inline-end. Abstract,
          no copy, aria-hidden: pure depth cues over the particle field. */}
      <div className="absolute inset-0 hidden lg:block pointer-events-none" aria-hidden="true">
        {/* near: faux message chip */}
        <motion.div
          className={`absolute top-[24%] end-[8%] w-56 px-4 py-3 ${LANDING_SURFACE}`}
          style={motionOff ? undefined : { y: floatNearY }}
        >
          <div className="h-2.5 w-10 rounded-full bg-accent/50" />
          <div className="mt-2.5 h-2 w-full rounded-full bg-white/10" />
          <div className="mt-1.5 h-2 w-3/4 rounded-full bg-white/10" />
        </motion.div>

        {/* mid: glowing ring */}
        <motion.div
          className="absolute top-[58%] end-[20%]"
          style={motionOff ? undefined : { y: floatMidY }}
        >
          <div className="size-14 rounded-full border border-[hsl(var(--landing-warm)/0.35)] shadow-[0_0_40px_-8px_hsl(var(--landing-warm)/0.4)]" />
        </motion.div>

        {/* far: small teal dot cluster */}
        <motion.div
          className={`absolute top-[40%] end-[38%] flex items-center gap-1.5 px-3 py-2 ${LANDING_SURFACE}`}
          style={motionOff ? undefined : { y: floatFarY }}
        >
          <span className="size-1.5 rounded-full bg-[hsl(var(--teal))]" />
          <span className="size-1.5 rounded-full bg-[hsl(var(--teal)/0.6)]" />
          <span className="size-1.5 rounded-full bg-[hsl(var(--teal)/0.3)]" />
        </motion.div>
      </div>

      {/* Content: start-aligned asymmetric, NOT a centered stack. */}
      <div className="relative z-10 w-full max-w-7xl mx-auto px-6 lg:px-8 pointer-events-none">
        <motion.div
          className="max-w-5xl space-y-8"
          style={
            motionOff
              ? undefined
              : { y: headlineY, opacity: headlineOpacity, scale: headlineScale }
          }
        >
          <motion.div
            initial={reduceMotion ? false : 'hidden'}
            animate="visible"
            variants={{ visible: { transition: { staggerChildren: 0.08 } } }}
            className="space-y-8"
          >
            {/* Eyebrow */}
            <motion.p
              variants={wordVariants}
              className="text-sm font-medium text-foreground-tertiary"
            >
              {t('hero.badge')}
            </motion.p>

            {/* Display headline: solid colors only, blurred amber orb behind. */}
            <div className="relative">
              <div
                className="absolute -top-16 -start-10 w-[30rem] h-[30rem] max-md:w-[20rem] max-md:h-[20rem] bg-[hsl(var(--landing-warm)/0.14)] blur-[100px] max-md:blur-[45px] rounded-full pointer-events-none"
                aria-hidden="true"
              />
              <h1
                className={`relative font-display font-black text-[clamp(2.75rem,7vw,6.5rem)] leading-[0.95] text-foreground ${
                  isRTL ? '' : 'tracking-[-0.03em]'
                }`}
              >
                <HeadlineWords text={t('hero.headline_1')} />{' '}
                <HeadlineWords text={t('hero.headline_accent')} className="text-accent" />
              </h1>
            </div>

            {/* Subheadline */}
            <motion.p
              variants={wordVariants}
              className={`max-w-2xl text-lg text-foreground-secondary leading-relaxed ${
                isRTL ? 'font-normal' : 'font-light'
              }`}
            >
              {t('hero.subheadline')}
            </motion.p>

            {/* CTA pair */}
            <motion.div
              variants={wordVariants}
              className="flex flex-col sm:flex-row gap-3 pt-2 pointer-events-auto"
            >
              <Button asChild size="lg" className="group">
                <Link to={href}>
                  {isAuthed ? t('navbar.enter_app') : t('hero.cta_primary')}
                  <ArrowRight className="w-4 h-4 ms-1 rtl:-scale-x-100 group-hover:translate-x-0.5 rtl:group-hover:-translate-x-0.5 transition-transform" />
                </Link>
              </Button>
              <Button variant="outline" size="lg" onClick={scrollToDemo}>
                {t('hero.cta_secondary')}
              </Button>
            </motion.div>

            {/* Minimal dot-separated text chips, no boxes. */}
            <motion.div
              variants={wordVariants}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 pt-2 text-sm text-foreground-tertiary"
            >
              {pills.map((feature, i) => (
                <span key={feature} className="inline-flex items-center gap-x-3">
                  {i > 0 && (
                    <span className="size-1 rounded-full bg-foreground-tertiary/50" aria-hidden="true" />
                  )}
                  {feature}
                </span>
              ))}
            </motion.div>
          </motion.div>
        </motion.div>
      </div>

      {/* Scroll indicator: fades on scroll, no infinite bounce. */}
      <motion.div
        className="absolute bottom-8 start-1/2 -translate-x-1/2 hidden lg:block pointer-events-none"
        style={motionOff ? undefined : { opacity: indicatorOpacity }}
        initial={reduceMotion ? false : { opacity: 0 }}
        animate={reduceMotion ? undefined : { opacity: 1 }}
        transition={{ delay: 1, duration: 0.6 }}
        aria-hidden="true"
      >
        <div className="w-5 h-8 rounded-full border-2 border-foreground-tertiary/60 flex justify-center pt-2">
          <div className="w-1 h-1.5 bg-foreground-tertiary/80 rounded-full" />
        </div>
      </motion.div>
    </section>
  )
}

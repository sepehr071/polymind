import { useEffect } from 'react'
import { motion } from 'motion/react'
import { useLanguage } from '@/context/LanguageContext'
import Navbar from './components/Navbar'
import HeroSection from './components/HeroSection'
import ProductShowcase from './components/ProductShowcase'
import FeaturesSection from './components/FeaturesSection'
import PrivacySection from './components/PrivacySection'
import DemoSection from './components/DemoSection'
import HowItWorksSection from './components/HowItWorksSection'
import StatsSection from './components/StatsSection'
import CTASection from './components/CTASection'

/**
 * Landing page — shown to non-authenticated users.
 * Warm dark luxury: LOCKED dark regardless of app theme via the scoped
 * `dark landing-dark` wrapper plus an html-level dark class (portalled UI,
 * scrollbar and overscroll all read from <html>).
 */
const META_DESCRIPTION =
  'نُویس؛ بستر هوش مصنوعی سازمانی: چت، گردش کار، پایگاه دانش و مدیریت هزینه در یک فضای کاری امن.'

export default function LandingPage() {
  const { setLanguage } = useLanguage()

  // Default visitors to Persian, but RESPECT an explicitly-stored preference —
  // never overwrite the visitor's chosen language (was persisting 'fa' on mount).
  useEffect(() => {
    let stored = null
    try { stored = localStorage.getItem('unichat-language') } catch { /* private mode */ }
    if (!stored) setLanguage('fa')
  }, [setLanguage])

  // Smooth-scroll for in-page hash anchors — but ONLY when the click targets a
  // landing section that actually exists on this page. A bare href="#..." that
  // resolves to no element (or any other in-app anchor) must fall through to the
  // default behavior instead of being swallowed here.
  useEffect(() => {
    const handleSmoothScroll = (e) => {
      const target = e.target.closest('a[href^="#"]')
      if (!target) return

      const id = target.getAttribute('href')?.slice(1)
      if (!id) return

      const element = document.getElementById(id)
      if (!element) return // not a landing section — let the click behave normally

      e.preventDefault()
      element.scrollIntoView({ behavior: 'smooth' })
    }

    document.addEventListener('click', handleSmoothScroll)
    return () => document.removeEventListener('click', handleSmoothScroll)
  }, [])

  // Dark-lock + document meta. The wrapper class darkens the in-flow tree, but
  // the scrollbar, rubber-band overscroll and body-portalled UI (MUI Drawer in
  // the mobile navbar, Toaster) read tokens from <html> — so force the html
  // dark class for the landing's lifetime and restore EXACTLY what was there
  // on unmount. Safe vs ThemeContext: it only re-asserts the class on theme
  // *change*, and the landing has no theme toggle.
  useEffect(() => {
    const root = document.documentElement
    const wasDark = root.classList.contains('dark')
    root.classList.remove('light')
    root.classList.add('dark')

    const prevTitle = document.title
    document.title = 'Polymind AI · هوش مصنوعی سازمانی'

    let meta = document.querySelector('meta[name="description"]')
    const created = !meta
    const prevDescription = meta?.getAttribute('content') ?? null
    if (!meta) {
      meta = document.createElement('meta')
      meta.setAttribute('name', 'description')
      document.head.appendChild(meta)
    }
    meta.setAttribute('content', META_DESCRIPTION)

    return () => {
      if (!wasDark) {
        root.classList.remove('dark')
        root.classList.add('light')
      }
      document.title = prevTitle
      if (created) meta.remove()
      else if (prevDescription !== null) meta.setAttribute('content', prevDescription)
    }
  }, [])

  // Check for reduced motion preference
  const prefersReducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  return (
    <motion.div
      className="dark landing-dark min-h-screen bg-background text-foreground overflow-x-hidden"
      initial={prefersReducedMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
    >
      {/* Fixed Navbar */}
      <Navbar />

      {/* Main Content — narrative: see it → explore it → how → proof → act */}
      <main>
        <HeroSection />
        <ProductShowcase />
        <FeaturesSection />
        <PrivacySection />
        <DemoSection />
        <HowItWorksSection />
        <StatsSection />
        <CTASection />
      </main>
    </motion.div>
  )
}

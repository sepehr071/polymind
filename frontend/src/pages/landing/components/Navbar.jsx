import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { motion, useReducedMotion } from 'motion/react'
import { Menu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { useTranslation } from 'react-i18next'
import { useLanguage } from '@/context/LanguageContext'
import { useCoarsePointer } from '@/hooks/useMediaQuery'
import PolymindLogo from '@/components/brand/PolymindLogo'
import { easeOutExpo } from '../lib/landingStyles'
import { useAppEntry } from '../lib/useAppEntry'

/* Brand mark: static; hover does a single subtle tilt (no infinite spin). */
function LogoMark({ reduceMotion }) {
  return (
    <motion.span
      whileHover={reduceMotion ? undefined : { rotate: -6, scale: 1.06 }}
      transition={{ duration: 0.35, ease: easeOutExpo }}
      className="grid size-8 place-items-center"
    >
      <PolymindLogo size={32} alt="" />
    </motion.span>
  )
}

export default function Navbar() {
  const [isOpen, setIsOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const reduceMotion = useReducedMotion()
  const coarse = useCoarsePointer()
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const { isAuthed, href } = useAppEntry()

  const navLinks = [
    { name: t('navbar.features'), href: '#features' },
    { name: t('navbar.demo'), href: '#demo' },
  ]

  // Track scroll position for the glass transition (GLASS MOMENT 1).
  // rAF-coalesced so the backdrop re-raster runs at most once per frame.
  useEffect(() => {
    let ticking = false
    const update = () => {
      setScrolled(window.scrollY > 50)
      ticking = false
    }
    const onScroll = () => {
      if (!ticking) {
        ticking = true
        requestAnimationFrame(update)
      }
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const handleNavClick = (e, href) => {
    e.preventDefault()
    document.querySelector(href)?.scrollIntoView({ behavior: 'smooth' })
    setIsOpen(false)
  }

  return (
    <motion.nav
      initial={reduceMotion ? false : { y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5, ease: easeOutExpo }}
      className={`fixed top-0 start-0 end-0 z-50 transition-[background-color,border-color,backdrop-filter] duration-300 ${
        scrolled
          ? coarse
            ? 'border-b border-white/[0.08] bg-background/90'
            : 'border-b border-white/[0.08] bg-background/70 backdrop-blur-xl'
          : 'border-b border-transparent bg-transparent'
      }`}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        {/* Logo */}
        <Link to="/" className="group flex items-center gap-2.5">
          <LogoMark reduceMotion={reduceMotion} />
          <span
            className="text-lg font-semibold text-foreground transition-colors group-hover:text-accent"
            dir="ltr"
          >
            Polymind AI
          </span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden items-center gap-8 md:flex">
          <div className="flex items-center gap-6">
            {navLinks.map((link, i) => (
              <motion.a
                key={link.name}
                href={link.href}
                onClick={(e) => handleNavClick(e, link.href)}
                initial={reduceMotion ? false : { opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.15 + i * 0.08, ease: easeOutExpo }}
                className="group relative py-1 text-sm text-foreground-secondary transition-colors hover:text-foreground"
              >
                {link.name}
                {/* scale-x underline: GPU transform, no layout animation. Grows
                    from the inline-start edge (origin-left, mirrored for RTL). */}
                <span className="absolute -bottom-0.5 start-0 h-px w-full origin-left scale-x-0 bg-accent transition-transform duration-300 ease-out group-hover:scale-x-100 rtl:origin-right" />
              </motion.a>
            ))}
          </div>

          <motion.div
            initial={reduceMotion ? false : { opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, ease: easeOutExpo }}
            className="flex items-center gap-3"
          >
            {!isAuthed && (
              <Button variant="ghost" asChild className="group">
                <Link to="/login">
                  <span className="transition-colors group-hover:text-accent">
                    {t('navbar.login')}
                  </span>
                </Link>
              </Button>
            )}
            <Button asChild className="group relative overflow-hidden">
              <Link to={href}>
                {/* Hover-driven sheen: one-shot composited translate, no infinite
                    loop, no layout animation. RTL mirrors the sweep direction. */}
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-y-0 -inset-x-2 -translate-x-[200%] -skew-x-12 bg-white/15 transition-transform duration-700 ease-out group-hover:translate-x-[200%] rtl:translate-x-[200%] rtl:group-hover:-translate-x-[200%]"
                />
                <span className="relative">
                  {isAuthed ? t('navbar.enter_app') : t('navbar.get_started')}
                </span>
              </Link>
            </Button>
          </motion.div>
        </div>

        {/* Mobile menu */}
        <Sheet open={isOpen} onOpenChange={setIsOpen}>
          <SheetTrigger asChild className="md:hidden">
            <Button variant="ghost" size="icon" className="h-11 w-11" aria-label={t('navbar.features')}>
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="end" className="w-72">
            <motion.div
              initial={reduceMotion ? false : { opacity: 0, x: isRTL ? -20 : 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.1, ease: easeOutExpo }}
              className="flex flex-col gap-6 pt-8"
            >
              <div className="flex items-center gap-2.5">
                <LogoMark reduceMotion={reduceMotion} />
                <span className="text-lg font-semibold text-foreground" dir="ltr">
                  Polymind AI
                </span>
              </div>

              <div className="flex flex-col gap-4">
                {navLinks.map((link, i) => (
                  <motion.a
                    key={link.name}
                    href={link.href}
                    onClick={(e) => handleNavClick(e, link.href)}
                    initial={reduceMotion ? false : { opacity: 0, x: isRTL ? -20 : 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.2 + i * 0.08, ease: easeOutExpo }}
                    className="text-foreground-secondary transition-all hover:translate-x-2 hover:text-foreground rtl:hover:-translate-x-2 py-2 -mx-2 px-2 rounded-lg"
                  >
                    {link.name}
                  </motion.a>
                ))}
              </div>

              <motion.div
                initial={reduceMotion ? false : { opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4, ease: easeOutExpo }}
                className="flex flex-col gap-3 pt-4"
              >
                {isAuthed ? (
                  <Button asChild className="w-full">
                    <Link to={href}>{t('navbar.enter_app')}</Link>
                  </Button>
                ) : (
                  <>
                    <Button variant="outline" asChild className="w-full">
                      <Link to="/login">{t('navbar.login')}</Link>
                    </Button>
                    <Button asChild className="w-full">
                      <Link to="/login">{t('navbar.get_started')}</Link>
                    </Button>
                  </>
                )}
              </motion.div>
            </motion.div>
          </SheetContent>
        </Sheet>
      </div>
    </motion.nav>
  )
}

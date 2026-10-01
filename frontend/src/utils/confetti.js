// Tasteful, one-shot celebration confetti. Sky/cyan glass palette + white,
// hardcoded as hex because canvas can't read CSS vars (mirrors the primary
// sky-500 hue from index.css :root / theme/tokens.js). canvas-confetti is
// dynamically imported so its ~4KB stays out of the main bundle, and the whole
// thing is fire-and-forget: gated on reduced-motion and never throws.
const CONFETTI_COLORS = [
  '#0ea5e9', // sky-500 (mirrors --accent)
  '#38bdf8', // sky-400
  '#7dd3fc', // sky-300
  '#0284c7', // sky-600 (--primary-dark)
  '#ffffff', // neutral white
]

export async function celebrate(options = {}) {
  if (
    typeof window === 'undefined' ||
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ) {
    return
  }

  try {
    const confetti = (await import('canvas-confetti')).default
    confetti({
      particleCount: 80,
      spread: 70,
      origin: { y: 0.7 },
      colors: CONFETTI_COLORS,
      disableForReducedMotion: true,
      ...options,
    })
  } catch {
    // Fire-and-forget — a missing/blocked confetti module must never break flows.
  }
}

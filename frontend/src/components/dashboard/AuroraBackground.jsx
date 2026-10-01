import { useEffect, useRef } from 'react'

/**
 * AuroraBackground — the dashboard hub's ambient backdrop.
 *
 * Three softly-drifting aurora blobs (royal / violet / teal) under a faint
 * accent wash, with a lightweight 2D-canvas "constellation": glowing dots that
 * drift, link to nearby neighbours, and lean toward the cursor. Ported from the
 * Claude-Design handoff mockup (its `initStars`), rebuilt as a self-cleaning
 * React effect — no three.js (that heavy field is the landing page's only).
 *
 * Absolutely positioned to fill its (relative) parent, behind content, and
 * `pointer-events:none` so it never eats clicks. Honors reduced-motion: paints
 * one static frame, starts no rAF loop. Re-inits the particle field on resize.
 *
 * Theme-safe: the blob/dot hues read on both light and dark; the base wash uses
 * the accent token so it blends with whichever app background sits beneath.
 */

// Royal / violet / teal — the POLYMIND brand trio (matches the aurora blobs).
const COLS = [
  [30, 71, 209],
  [109, 94, 247],
  [20, 184, 166],
]
const N = 92 // particle count
const LINK = 124 // px: max neighbour-link distance
const MOUSE = 172 // px: cursor influence radius

export default function AuroraBackground() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const host = canvas.parentElement
    const reduce =
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let raf = 0
    let ps = []
    const mouse = { x: -9999, y: -9999, on: false }
    let w = 0
    let h = 0

    const seed = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = canvas.clientWidth || 1
      h = canvas.clientHeight || 1
      canvas.width = w * dpr
      canvas.height = h * dpr
      const ctx = canvas.getContext('2d')
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ps = []
      for (let i = 0; i < N; i++) {
        const big = Math.random() < 0.15
        ps.push({
          x: Math.random() * w,
          y: Math.random() * h,
          r: big ? Math.random() * 2.2 + 2.2 : Math.random() * 1.3 + 0.6,
          vx: (Math.random() - 0.5) * 0.28,
          vy: (Math.random() - 0.5) * 0.28,
          a: Math.random() * 0.4 + 0.28,
          tw: Math.random() * 6.2832,
          ts: Math.random() * 0.018 + 0.008,
          col: COLS[i % 3],
          big,
        })
      }
      return ctx
    }

    let ctx = seed()

    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      // drift + gentle cursor attraction
      for (const p of ps) {
        p.x += p.vx
        p.y += p.vy
        p.tw += p.ts
        if (p.x < -12) p.x = w + 12
        if (p.x > w + 12) p.x = -12
        if (p.y < -12) p.y = h + 12
        if (p.y > h + 12) p.y = -12
        if (mouse.on) {
          const dx = mouse.x - p.x
          const dy = mouse.y - p.y
          const d = Math.sqrt(dx * dx + dy * dy)
          if (d < MOUSE && d > 1) {
            const f = (1 - d / MOUSE) * 0.5
            p.x += (dx / d) * f
            p.y += (dy / d) * f
          }
        }
      }
      // constellation links
      for (let i = 0; i < ps.length; i++) {
        for (let j = i + 1; j < ps.length; j++) {
          const dx = ps[i].x - ps[j].x
          const dy = ps[i].y - ps[j].y
          const d = Math.sqrt(dx * dx + dy * dy)
          if (d < LINK) {
            ctx.strokeStyle = 'rgba(30,71,209,' + (1 - d / LINK) * 0.13 + ')'
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(ps[i].x, ps[i].y)
            ctx.lineTo(ps[j].x, ps[j].y)
            ctx.stroke()
          }
        }
      }
      // cursor beams
      if (mouse.on) {
        for (const p of ps) {
          const dx = mouse.x - p.x
          const dy = mouse.y - p.y
          const d = Math.sqrt(dx * dx + dy * dy)
          if (d < MOUSE) {
            ctx.strokeStyle = 'rgba(109,94,247,' + (1 - d / MOUSE) * 0.42 + ')'
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(mouse.x, mouse.y)
            ctx.lineTo(p.x, p.y)
            ctx.stroke()
          }
        }
      }
      // glowing dots
      for (const p of ps) {
        const a = p.a * (0.55 + 0.45 * Math.sin(p.tw))
        const base = 'rgba(' + p.col[0] + ',' + p.col[1] + ',' + p.col[2] + ','
        if (p.big) {
          ctx.shadowBlur = 14
          ctx.shadowColor = base + '0.7)'
        }
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, 6.2832)
        ctx.fillStyle = base + a + ')'
        ctx.fill()
        ctx.shadowBlur = 0
      }
    }

    draw() // always paint at least one frame (rAF may be throttled on load)
    if (!reduce) {
      const tick = () => {
        draw()
        raf = requestAnimationFrame(tick)
      }
      raf = requestAnimationFrame(tick)
    }

    // cursor attraction — listen on window, map to canvas-local coords (the
    // backdrop is pointer-events:none, so it never receives events itself).
    const onMove = (e) => {
      const r = canvas.getBoundingClientRect()
      const x = e.clientX - r.left
      const y = e.clientY - r.top
      mouse.on = x >= 0 && y >= 0 && x <= r.width && y <= r.height
      mouse.x = x
      mouse.y = y
    }
    if (!reduce) window.addEventListener('mousemove', onMove, { passive: true })

    // re-seed on container resize (responsive page width)
    let ro
    if (typeof ResizeObserver !== 'undefined' && host) {
      ro = new ResizeObserver(() => {
        ctx = seed()
        if (reduce) draw() // static frame needs an explicit repaint
      })
      ro.observe(host)
    }

    return () => {
      if (raf) cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', onMove)
      if (ro) ro.disconnect()
    }
  }, [])

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
    >
      {/* faint accent wash so the field reads as a tinted glass plate on both
          themes (blends with the app background beneath) */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(120% 80% at 50% -8%, hsl(var(--accent) / 0.06), transparent 62%)',
        }}
      />
      {/* drifting aurora blobs (royal / violet / teal) */}
      <div
        className="absolute"
        style={{
          width: 540,
          height: 540,
          borderRadius: '50%',
          top: -180,
          insetInlineEnd: -120,
          background:
            'radial-gradient(circle, rgba(30,71,209,0.16), transparent 70%)',
          filter: 'blur(26px)',
          animation: 'driftA 26s ease-in-out infinite',
        }}
      />
      <div
        className="absolute"
        style={{
          width: 480,
          height: 480,
          borderRadius: '50%',
          top: 60,
          insetInlineStart: -160,
          background:
            'radial-gradient(circle, rgba(109,94,247,0.15), transparent 70%)',
          filter: 'blur(26px)',
          animation: 'driftB 31s ease-in-out infinite',
        }}
      />
      <div
        className="absolute"
        style={{
          width: 560,
          height: 560,
          borderRadius: '50%',
          bottom: -220,
          insetInlineEnd: '34%',
          background:
            'radial-gradient(circle, rgba(20,184,166,0.12), transparent 70%)',
          filter: 'blur(26px)',
          animation: 'driftC 35s ease-in-out infinite',
        }}
      />
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
    </div>
  )
}

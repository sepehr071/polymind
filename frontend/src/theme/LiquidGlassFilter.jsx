// One hidden SVG filter for refraction. Apply via filter:url(#liquid-glass)
// ONLY behind @supports + on a few hero elements (Chromium-only; solid
// frosted fallback elsewhere). Mounted once by MuiProvider.
export default function LiquidGlassFilter() {
  return (
    <svg aria-hidden="true" width="0" height="0" style={{ position: 'absolute', pointerEvents: 'none' }}>
      <filter id="liquid-glass" x="-20%" y="-20%" width="140%" height="140%">
        <feTurbulence type="fractalNoise" baseFrequency="0.008 0.012" numOctaves="2" seed="7" result="noise" />
        <feDisplacementMap in="SourceGraphic" in2="noise" scale="18" xChannelSelector="R" yChannelSelector="G" />
      </filter>
    </svg>
  )
}

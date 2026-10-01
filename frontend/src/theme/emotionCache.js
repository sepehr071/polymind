import createCache from '@emotion/cache'
// Default export (the named `rtlPlugin` is undefined in this package).
import rtlPlugin from '@mui/stylis-plugin-rtl'

// prepend:true → MUI styles inject FIRST so Tailwind utilities win specificity.
// rtlPlugin in the RTL cache flips logical properties for MUI components.
const caches = {}

export function getEmotionCache(dir) {
  const isRtl = dir === 'rtl'
  const key = isRtl ? 'mui-rtl' : 'mui-ltr'
  if (!caches[key]) {
    caches[key] = createCache({
      key,
      prepend: true,
      stylisPlugins: isRtl ? [rtlPlugin] : [],
    })
  }
  return caches[key]
}

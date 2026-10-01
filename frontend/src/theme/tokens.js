// Design tokens — Polymind ERP MUI palette (erp-mui-theme.md) + Minimal DNA.
// HAND-sync literals with index.css :root/.dark (comma-HSL for MUI decomposeColor).
// Font = Vazirmatn (FA+EN). Primary = Polymind royal blue.

export const hsl = (t) => `hsl(${t.trim().replace(/\s+/g, ', ')})`

/** Slate grey ramp (ERP). */
export const GREY = {
  50: '#F8FAFC',
  100: '#F1F5F9',
  200: '#EAEEF5',
  300: '#D5DCE6',
  400: '#94A3B8',
  500: '#64748B',
  600: '#475569',
  700: '#334155',
  800: '#1E293B',
  900: '#0F172A',
}

/** Grey 500 channel — action overlays / outlined borders. */
const GREY_500_A = (a) => `rgba(100, 116, 139, ${a})`

/** Polymind primary — light scheme (ERP themeConfig.palette). */
export const PRIMARY = {
  lighter: '#D6E0FA',
  light: '#5E80E8',
  main: '#1E47D1',
  dark: '#183AB0',
  darker: '#122E8E',
  contrastText: '#FFFFFF',
}

/** Primary — dark scheme (only primary/secondary override in dark). */
const PRIMARY_DARK = {
  lighter: '#C4D4FF',
  light: '#96B7FF',
  main: '#80A7FF',
  dark: '#6A97FA',
  darker: '#4A7AF0',
  contrastText: '#0F172A',
}

/** Secondary / accent (quiet violet). */
export const SECONDARY = {
  lighter: '#E4E0FE',
  light: '#A89EFB',
  main: '#6D5EF7',
  dark: '#4E40D9',
  darker: '#3A2FB0',
  contrastText: '#FFFFFF',
}

const SECONDARY_DARK = {
  lighter: '#DAD4FF',
  light: '#C4BCFF',
  main: '#B6ACFF',
  dark: '#A295FF',
  darker: '#8478F0',
  contrastText: '#0F172A',
}

/** Semantics stay on the light ramps in both schemes (ERP). */
export const INFO = {
  lighter: '#D1E9FF',
  light: '#53B1FD',
  main: '#2E90FA',
  dark: '#175CD3',
  darker: '#194185',
  contrastText: '#FFFFFF',
}

export const SUCCESS = {
  lighter: '#D1FADF',
  light: '#32D583',
  main: '#12B76A',
  dark: '#027A48',
  darker: '#054F31',
  contrastText: '#FFFFFF',
}

export const WARNING = {
  lighter: '#FEF0C7',
  light: '#FDB022',
  main: '#F79009',
  dark: '#B54708',
  darker: '#7A2E0E',
  contrastText: '#1C252E',
}

export const ERROR = {
  lighter: '#FEE4E2',
  light: '#F97066',
  main: '#F04438',
  dark: '#B42318',
  darker: '#7A271A',
  contrastText: '#FFFFFF',
}

export const tokens = {
  light: {
    primary: PRIMARY,
    secondary: SECONDARY,
    primaryMain: PRIMARY.main,
    primaryLight: PRIMARY.light,
    primaryDark: PRIMARY.dark,
    primaryContrast: PRIMARY.contrastText,
    secondaryMain: SECONDARY.main,
    secondaryContrast: SECONDARY.contrastText,
    errorMain: ERROR.main,
    errorContrast: ERROR.contrastText,
    successMain: SUCCESS.main,
    warningMain: WARNING.main,
    warningContrast: WARNING.contrastText,
    infoMain: INFO.main,
    bgDefault: '#F8FAFF',
    bgPaper: '#FFFFFF',
    bgNeutral: '#F2F5FA',
    textPrimary: '#111827',
    textSecondary: '#5B6475',
    textDisabled: '#8B95A7',
    divider: '#E8EDF5',
    actionHover: GREY_500_A(0.08),
    ring: PRIMARY.main,
  },
  dark: {
    primary: PRIMARY_DARK,
    secondary: SECONDARY_DARK,
    primaryMain: PRIMARY_DARK.main,
    primaryLight: PRIMARY_DARK.light,
    primaryDark: PRIMARY_DARK.dark,
    primaryContrast: PRIMARY_DARK.contrastText,
    secondaryMain: SECONDARY_DARK.main,
    secondaryContrast: SECONDARY_DARK.contrastText,
    // Semantics stay on the light ramps (do not lift greens/reds).
    errorMain: ERROR.main,
    errorContrast: ERROR.contrastText,
    successMain: SUCCESS.main,
    warningMain: WARNING.main,
    warningContrast: WARNING.contrastText,
    infoMain: INFO.main,
    bgDefault: '#0F172A',
    bgPaper: '#182235',
    bgNeutral: '#202C42',
    textPrimary: '#F8FAFC',
    textSecondary: '#CBD5E1',
    textDisabled: '#94A3B8',
    divider: '#283548',
    actionHover: GREY_500_A(0.08),
    ring: PRIMARY_DARK.main,
  },
  // Minimal shape.borderRadius = 8; cards use 2× = 16
  radius: 8,
  fontFamily: "'Vazirmatn', ui-sans-serif, system-ui, sans-serif",
}

/** control=8, surface/card=16 (2×), overlay/dialog=16 */
export const RADII = { control: 8, surface: 16, overlay: 16 }

export const FONT_FAMILY = tokens.fontFamily

// re-export hex greys for CSS comments / charts
export { GREY as minimalGrey }

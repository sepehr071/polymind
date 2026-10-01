/**
 * App theme — inspired by Minimal UI v7.6.1 (minimals.cc) component DNA:
 * solid paper, customShadows.card, shape 8 / cards 16, softTransform none,
 * transparent AppBar, soft grey action layers.
 * Brand: Polymind royal blue. Font: Vazirmatn. Not a copy of licensed Minimal sources.
 */
import { createTheme } from '@mui/material/styles'
import { tokens, RADII, PRIMARY, GREY } from './tokens'
import { customShadows, createMuiShadows } from './customShadows'

/** ERP grey 500 #64748B — action overlays / outlined borders. */
const grey500a = (a) => `rgba(100, 116, 139, ${a})`

const paletteFor = (mode) => {
  const t = tokens[mode]
  return {
    mode,
    primary: { ...t.primary },
    secondary: { ...t.secondary },
    error: { main: t.errorMain, contrastText: t.errorContrast },
    success: { main: t.successMain },
    warning: { main: t.warningMain, contrastText: t.warningContrast },
    info: { main: t.infoMain },
    background: {
      default: t.bgDefault,
      paper: t.bgPaper,
      neutral: t.bgNeutral,
    },
    text: { primary: t.textPrimary, secondary: t.textSecondary, disabled: t.textDisabled },
    divider: t.divider,
    action: {
      active: mode === 'dark' ? GREY[500] : GREY[600],
      hover: t.actionHover,
      hoverOpacity: 0.08,
      selectedOpacity: 0.16,
      focusOpacity: 0.24,
      disabledOpacity: 0.80,
      disabledBackground: grey500a(0.24),
    },
    grey: { ...GREY },
  }
}

export function createAppTheme(dir = 'ltr') {
  const cs = customShadows.light
  const shadowsLight = createMuiShadows('light')
  const shadowsDark = createMuiShadows('dark')

  return createTheme({
    direction: dir === 'rtl' ? 'rtl' : 'ltr',
    cssVariables: { colorSchemeSelector: 'class', cssVarPrefix: 'mui' },
    colorSchemes: {
      light: {
        palette: paletteFor('light'),
        shadows: shadowsLight,
      },
      dark: {
        palette: paletteFor('dark'),
        shadows: shadowsDark,
      },
    },
    // Minimal: base 8; cards/dialogs use 2×
    shape: { borderRadius: 8 },
    shadows: shadowsLight,
    typography: {
      fontFamily: tokens.fontFamily,
      fontWeightLight: 300,
      fontWeightRegular: 400,
      fontWeightMedium: 500,
      fontWeightSemiBold: 600,
      fontWeightBold: 700,
      fontWeightExtraBold: 800,
      // FA: no negative letter-spacing
      h1: { fontWeight: 800, letterSpacing: 0, lineHeight: 1.25, fontSize: '2.5rem' },
      h2: { fontWeight: 800, letterSpacing: 0, lineHeight: 1.33, fontSize: '2rem' },
      h3: { fontWeight: 700, letterSpacing: 0, lineHeight: 1.5, fontSize: '1.5rem' },
      h4: { fontWeight: 700, letterSpacing: 0, lineHeight: 1.5, fontSize: '1.25rem' },
      h5: { fontWeight: 700, letterSpacing: 0, lineHeight: 1.5, fontSize: '1.125rem' },
      h6: { fontWeight: 600, letterSpacing: 0, lineHeight: 1.55, fontSize: '1.0625rem' },
      subtitle1: { fontWeight: 600, letterSpacing: 0, lineHeight: 1.5, fontSize: '1rem' },
      subtitle2: { fontWeight: 600, letterSpacing: 0, lineHeight: 22 / 14, fontSize: '0.875rem' },
      body1: { fontWeight: 400, letterSpacing: 0, lineHeight: 1.5, fontSize: '1rem' },
      body2: { fontWeight: 400, letterSpacing: 0, lineHeight: 22 / 14, fontSize: '0.875rem' },
      caption: { fontWeight: 400, letterSpacing: 0, lineHeight: 1.5, fontSize: '0.75rem' },
      button: { textTransform: 'none', fontWeight: 700, letterSpacing: 0, fontSize: '0.875rem', lineHeight: 24 / 14 },
      overline: { fontWeight: 700, letterSpacing: 0, fontSize: '0.75rem', textTransform: 'uppercase' },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          // Minimal page feel — soft grey canvas
          body: {
            backgroundColor: 'var(--mui-palette-background-default)',
          },
        },
      },
      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            backgroundColor: 'var(--mui-palette-background-paper)',
          },
          outlined: {
            borderColor: grey500a(0.16),
          },
        },
      },

      MuiButtonBase: {
        defaultProps: { disableRipple: false },
        styleOverrides: {
          root: {
            '&:focus-visible': {
              outline: `2px solid ${PRIMARY.main}`,
              outlineOffset: 2,
            },
          },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: {
            borderRadius: RADII.control,
            fontWeight: 700,
            textTransform: 'none',
            gap: 8,
            '& svg': { width: '1.15em', height: '1.15em', flexShrink: 0 },
          },
          sizeSmall: { minHeight: 30, paddingInline: 8, paddingBlock: 4, fontSize: '0.8125rem' },
          sizeMedium: { minHeight: 36, paddingInline: 12, paddingBlock: 6 },
          sizeLarge: { minHeight: 48, paddingInline: 16, paddingBlock: 8 },
          containedPrimary: {
            boxShadow: 'none',
            '&:hover': { boxShadow: cs.primary },
          },
          containedInherit: {
            '&:hover': { boxShadow: cs.z8 },
          },
          outlined: {
            borderColor: grey500a(0.32),
            '&:hover': {
              borderColor: 'currentColor',
              boxShadow: '0 0 0 0.75px currentColor',
              backgroundColor: grey500a(0.08),
            },
          },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: { borderRadius: RADII.control },
        },
      },

      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: RADII.control,
            backgroundColor: 'transparent',
            '& .MuiOutlinedInput-notchedOutline': {
              borderColor: grey500a(0.2),
            },
            '&:hover .MuiOutlinedInput-notchedOutline': {
              borderColor: grey500a(0.4),
            },
            '&.Mui-focused': {
              boxShadow: `0 0 0 1px ${PRIMARY.main}`,
            },
            '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
              borderWidth: 1,
              borderColor: PRIMARY.main,
            },
          },
          input: {
            // Minimal-ish 15px base
            fontSize: '0.9375rem',
            paddingTop: 12,
            paddingBottom: 12,
          },
        },
      },
      MuiTextField: { defaultProps: { variant: 'outlined', size: 'small' } },
      MuiInputBase: {
        styleOverrides: {
          input: {
            '&::placeholder': { opacity: 1, color: 'var(--mui-palette-text-disabled)' },
          },
        },
      },

      MuiCheckbox: {
        defaultProps: { disableRipple: false },
        styleOverrides: {
          root: {
            color: 'var(--mui-palette-text-disabled)',
            '&.Mui-checked': { color: 'var(--mui-palette-primary-main)' },
          },
        },
      },
      MuiRadio: {
        defaultProps: { disableRipple: false },
        styleOverrides: {
          root: {
            color: 'var(--mui-palette-text-disabled)',
            '&.Mui-checked': { color: 'var(--mui-palette-primary-main)' },
          },
        },
      },
      MuiSwitch: {
        styleOverrides: {
          root: {
            '& .Mui-checked': { color: 'var(--mui-palette-primary-main)' },
            '& .Mui-checked + .MuiSwitch-track': {
              backgroundColor: 'var(--mui-palette-primary-main)',
              opacity: 1,
            },
          },
        },
      },
      MuiSlider: { styleOverrides: { root: { color: 'var(--mui-palette-primary-main)' } } },

      // Prototype card: hairline, radius 16, soft brand shadow. Dark drops the shadow.
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            position: 'relative',
            backgroundImage: 'none',
            backgroundColor: 'var(--mui-palette-background-paper)',
            boxShadow: '0 1px 2px rgb(17 24 39 / 0.04), 0 8px 24px -12px rgb(30 71 209 / 0.14)',
            borderRadius: `${RADII.surface}px`,
            border: '1px solid var(--mui-palette-divider)',
            zIndex: 0,
            transition: 'box-shadow .2s ease, transform .2s ease',
            '.dark &': { boxShadow: 'none' },
          },
        },
      },
      MuiCardHeader: {
        defaultProps: {
          titleTypographyProps: { variant: 'h6' },
          subheaderTypographyProps: { variant: 'body2', marginTop: '4px' },
        },
        styleOverrides: {
          root: { padding: '24px 24px 0' },
          title: { fontWeight: 600, fontSize: '1.0625rem' },
          subheader: { fontSize: '0.875rem' },
        },
      },
      MuiCardContent: {
        styleOverrides: {
          root: { padding: 24, '&:last-child': { paddingBottom: 24 } },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 8, fontWeight: 600 },
          filled: { backgroundColor: grey500a(0.16) },
        },
      },
      MuiDivider: {
        styleOverrides: {
          root: { borderColor: 'var(--mui-palette-divider)' },
        },
      },

      MuiTabs: {
        styleOverrides: {
          indicator: {
            height: 2,
            borderRadius: 1,
            backgroundColor: 'var(--mui-palette-primary-main)',
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: { textTransform: 'none', fontWeight: 600, minHeight: 48 },
        },
      },
      MuiToggleButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            borderRadius: RADII.control,
            borderColor: grey500a(0.32),
          },
        },
      },

      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: RADII.control,
            '&.Mui-selected': {
              backgroundColor: 'rgba(30, 71, 209, 0.08)',
              color: 'var(--mui-palette-primary-main)',
              '&:hover': { backgroundColor: 'rgba(30, 71, 209, 0.12)' },
              '& .MuiListItemIcon-root': { color: 'var(--mui-palette-primary-main)' },
            },
          },
        },
      },
      MuiListItemIcon: { styleOverrides: { root: { minWidth: 36, color: 'inherit' } } },

      // Minimal AppBar — transparent, no shadow (layout paints surface)
      MuiAppBar: {
        defaultProps: { elevation: 0, color: 'transparent' },
        styleOverrides: {
          root: {
            boxShadow: 'none',
            backgroundImage: 'none',
            color: 'var(--mui-palette-text-primary)',
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundImage: 'none',
            backgroundColor: 'var(--mui-palette-background-paper)',
            borderColor: 'var(--mui-palette-divider)',
          },
        },
      },
      MuiMenu: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          paper: {
            backgroundImage: 'none',
            backgroundColor: 'var(--mui-palette-background-paper)',
            boxShadow: cs.dropdown,
            borderRadius: `${RADII.control}px`,
            border: 'none',
          },
        },
      },
      MuiPopover: {
        styleOverrides: {
          paper: {
            backgroundImage: 'none',
            backgroundColor: 'var(--mui-palette-background-paper)',
            boxShadow: cs.dropdown,
            borderRadius: `${RADII.control}px`,
            border: 'none',
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            backgroundImage: 'none',
            backgroundColor: 'var(--mui-palette-background-paper)',
            boxShadow: cs.dialog,
            borderRadius: `${RADII.overlay}px`,
            border: 'none',
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            backgroundColor: GREY_TOOLTIP_BG,
            color: '#FFFFFF',
            fontSize: '0.75rem',
            fontWeight: 500,
            padding: '6px 10px',
            borderRadius: '8px',
            boxShadow: cs.z8,
          },
          arrow: { color: GREY_TOOLTIP_BG },
        },
      },
      MuiBackdrop: {
        styleOverrides: {
          root: {
            backgroundColor: 'rgba(22, 28, 36, 0.48)',
          },
          invisible: { background: 'transparent' },
        },
      },
    },
  })
}

// ERP grey 700 tooltip surface
const GREY_TOOLTIP_BG = GREY[700]

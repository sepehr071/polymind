/**
 * Minimal UI–style customShadows (inspired by Minimal v7 custom-shadows.ts).
 * Soft grey-tinted elevation — no liquid-glass blur.
 * z* ladder + card / dialog / dropdown + primary hover glow.
 */

const alpha = (hexOrRgb, a) => {
  // Accept #RRGGBB or prebuilt channel "r g b"
  if (hexOrRgb.startsWith('#')) {
    const h = hexOrRgb.slice(1)
    const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16)
    const r = (n >> 16) & 255
    const g = (n >> 8) & 255
    const b = n & 255
    return `rgba(${r},${g},${b},${a})`
  }
  return `rgba(${hexOrRgb},${a})`
}

function make(colorHex, blackHex = '#000000') {
  const c = colorHex
  const blk = blackHex
  return {
    z1: `0 1px 2px 0 ${alpha(c, 0.16)}`,
    z4: `0 4px 8px 0 ${alpha(c, 0.16)}`,
    z8: `0 8px 16px 0 ${alpha(c, 0.16)}`,
    z12: `0 12px 24px -4px ${alpha(c, 0.16)}`,
    z16: `0 16px 32px -4px ${alpha(c, 0.16)}`,
    z20: `0 20px 40px -4px ${alpha(c, 0.16)}`,
    z24: `0 24px 48px 0 ${alpha(c, 0.16)}`,
    // Minimal signature surfaces
    card: `0 0 2px 0 ${alpha(c, 0.2)}, 0 12px 24px -4px ${alpha(c, 0.12)}`,
    dialog: `-40px 40px 80px -8px ${alpha(blk, 0.24)}`,
    dropdown: `0 0 2px 0 ${alpha(c, 0.24)}, -20px 20px 40px -4px ${alpha(c, 0.24)}`,
    primary: `0 8px 16px 0 ${alpha('#1E47D1', 0.24)}`,
    secondary: `0 8px 16px 0 ${alpha('#6D5EF7', 0.24)}`,
    error: `0 8px 16px 0 ${alpha('#F04438', 0.24)}`,
    success: `0 8px 16px 0 ${alpha('#12B76A', 0.24)}`,
    warning: `0 8px 16px 0 ${alpha('#F79009', 0.24)}`,
    info: `0 8px 16px 0 ${alpha('#2E90FA', 0.24)}`,
  }
}

export const customShadows = {
  light: make('#64748B', '#000000'), // ERP grey[500]
  dark: make('#000000', '#000000'),
}

/** MUI shadows[0..24] — recolor default ladder with grey channel (Minimal shadows.ts). */
export function createMuiShadows(mode = 'light') {
  const channel = mode === 'light' ? '100,116,139' : '0,0,0'
  const a = (op) => `rgba(${channel},${op})`
  return [
    'none',
    `0px 2px 1px -1px ${a(0.2)},0px 1px 1px 0px ${a(0.14)},0px 1px 3px 0px ${a(0.12)}`,
    `0px 3px 1px -2px ${a(0.2)},0px 2px 2px 0px ${a(0.14)},0px 1px 5px 0px ${a(0.12)}`,
    `0px 3px 3px -2px ${a(0.2)},0px 3px 4px 0px ${a(0.14)},0px 1px 8px 0px ${a(0.12)}`,
    `0px 2px 4px -1px ${a(0.2)},0px 4px 5px 0px ${a(0.14)},0px 1px 10px 0px ${a(0.12)}`,
    `0px 3px 5px -1px ${a(0.2)},0px 5px 8px 0px ${a(0.14)},0px 1px 14px 0px ${a(0.12)}`,
    `0px 3px 5px -1px ${a(0.2)},0px 6px 10px 0px ${a(0.14)},0px 1px 18px 0px ${a(0.12)}`,
    `0px 4px 5px -2px ${a(0.2)},0px 7px 10px 1px ${a(0.14)},0px 2px 16px 1px ${a(0.12)}`,
    `0px 5px 5px -3px ${a(0.2)},0px 8px 10px 1px ${a(0.14)},0px 3px 14px 2px ${a(0.12)}`,
    `0px 5px 6px -3px ${a(0.2)},0px 9px 12px 1px ${a(0.14)},0px 3px 16px 2px ${a(0.12)}`,
    `0px 6px 6px -3px ${a(0.2)},0px 10px 14px 1px ${a(0.14)},0px 4px 18px 3px ${a(0.12)}`,
    `0px 6px 7px -4px ${a(0.2)},0px 11px 15px 1px ${a(0.14)},0px 4px 20px 3px ${a(0.12)}`,
    `0px 7px 8px -4px ${a(0.2)},0px 12px 17px 2px ${a(0.14)},0px 5px 22px 4px ${a(0.12)}`,
    `0px 7px 8px -4px ${a(0.2)},0px 13px 19px 2px ${a(0.14)},0px 5px 24px 4px ${a(0.12)}`,
    `0px 7px 9px -4px ${a(0.2)},0px 14px 21px 2px ${a(0.14)},0px 5px 26px 4px ${a(0.12)}`,
    `0px 8px 9px -5px ${a(0.2)},0px 15px 22px 2px ${a(0.14)},0px 6px 28px 5px ${a(0.12)}`,
    `0px 8px 10px -5px ${a(0.2)},0px 16px 24px 2px ${a(0.14)},0px 6px 30px 5px ${a(0.12)}`,
    `0px 8px 11px -5px ${a(0.2)},0px 17px 26px 2px ${a(0.14)},0px 6px 32px 5px ${a(0.12)}`,
    `0px 9px 11px -5px ${a(0.2)},0px 18px 28px 2px ${a(0.14)},0px 7px 34px 6px ${a(0.12)}`,
    `0px 9px 12px -6px ${a(0.2)},0px 19px 29px 2px ${a(0.14)},0px 7px 36px 6px ${a(0.12)}`,
    `0px 10px 13px -6px ${a(0.2)},0px 20px 31px 3px ${a(0.14)},0px 8px 38px 7px ${a(0.12)}`,
    `0px 10px 13px -6px ${a(0.2)},0px 21px 33px 3px ${a(0.14)},0px 8px 40px 7px ${a(0.12)}`,
    `0px 10px 14px -6px ${a(0.2)},0px 22px 35px 3px ${a(0.14)},0px 8px 42px 7px ${a(0.12)}`,
    `0px 11px 14px -7px ${a(0.2)},0px 23px 36px 3px ${a(0.14)},0px 9px 44px 8px ${a(0.12)}`,
    `0px 11px 15px -7px ${a(0.2)},0px 24px 38px 3px ${a(0.14)},0px 9px 46px 8px ${a(0.12)}`,
  ]
}

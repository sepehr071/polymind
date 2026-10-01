import { GLASS_CLASS } from '@/theme/glass';

// Single shared glass mixin for the floating canvas chrome overlays (zoom bar,
// command bar, right-click hint chip). The ReactFlow canvas is full-bleed, so
// these controls genuinely float OVER content — glass is the canonical surface
// for top-bar/overlay chrome. Consolidated here so the inline glass style block
// is defined ONCE instead of duplicated per-file.
export const CANVAS_OVERLAY_GLASS_STYLE = {
  backgroundColor: 'rgb(var(--glass-bg) / var(--glass-bg-strong-opacity))',
  backdropFilter: 'blur(var(--glass-blur)) saturate(var(--glass-saturate))',
  WebkitBackdropFilter: 'blur(var(--glass-blur)) saturate(var(--glass-saturate))',
  border: '1px solid rgb(var(--glass-border) / var(--glass-border-opacity))',
  boxShadow: 'var(--glass-shadow)',
};

export { GLASS_CLASS };

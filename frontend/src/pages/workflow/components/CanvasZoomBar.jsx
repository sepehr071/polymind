import { useTranslation } from 'react-i18next';
import { useReactFlow } from 'reactflow';
import { cn } from '../../../utils/cn';
import { GLASS_CLASS, CANVAS_OVERLAY_GLASS_STYLE } from './canvasOverlayGlass';

// Segmented zoom control floating over the full-bleed canvas. Uses the shared
// canvas-overlay glass mixin (chrome overlay) rather than a per-file inline
// glass block. Internal hairlines use the border token.
const ZOOM_BTN =
  'h-9 flex items-center justify-center text-sm text-foreground-secondary hover:bg-background-tertiary/60 hover:text-foreground transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';

export default function CanvasZoomBar() {
  const { t } = useTranslation('workflow');
  const { zoomIn, zoomOut, zoomTo } = useReactFlow();

  return (
    <div
      className={cn(GLASS_CLASS, 'absolute bottom-5 start-5 flex items-center rounded-[9px] z-10 overflow-hidden')}
      style={CANVAS_OVERLAY_GLASS_STYLE}
    >
      <button
        onClick={() => zoomOut()}
        className={cn(ZOOM_BTN, 'w-9 border-e border-border')}
        aria-label={t('zoomBar.zoomOut')}
      >
        −
      </button>
      <button
        onClick={() => zoomTo(1)}
        className={cn(ZOOM_BTN, 'px-2 text-xs border-e border-border')}
        aria-label={t('zoomBar.resetZoom')}
      >
        100%
      </button>
      <button
        onClick={() => zoomIn()}
        className={cn(ZOOM_BTN, 'w-9')}
        aria-label={t('zoomBar.zoomIn')}
      >
        +
      </button>
    </div>
  );
}

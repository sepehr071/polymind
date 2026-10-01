import { useTranslation } from 'react-i18next';
import { Plus, Copy, Trash2, Type, Upload, Bot, Sparkles, Volume2, Video } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { cn } from '../../../utils/cn';
import { GLASS_CLASS, CANVAS_OVERLAY_GLASS_STYLE } from './canvasOverlayGlass';

const BAR_ICON_BTN = 'h-8 w-8 rounded-[9px]';

const NODE_TYPE_KEYS = [
  { type: 'textInput',    icon: Type     },
  { type: 'imageUpload',  icon: Upload   },
  { type: 'aiAgent',      icon: Bot      },
  { type: 'imageGen',     icon: Sparkles },
  { type: 'ttsNode',      icon: Volume2  },
  { type: 'videoGenNode', icon: Video    },
];

function BarButton({ icon: Icon, label, hotkey, onClick, disabled }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClick}
          disabled={disabled}
          className={BAR_ICON_BTN}
          aria-label={label}
        >
          <Icon className="w-3.5 h-3.5" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {label}{hotkey ? ` · ${hotkey}` : ''}
      </TooltipContent>
    </Tooltip>
  );
}

export default function CanvasCommandBar({
  selectedNodeId,
  onAddNode,
  onDuplicate,
  onDelete,
}) {
  const { t } = useTranslation('workflow');

  return (
    <div
      className={cn(GLASS_CLASS, 'absolute bottom-5 start-1/2 -translate-x-1/2 flex items-center gap-1 rounded-xl p-1 z-10')}
      style={CANVAS_OVERLAY_GLASS_STYLE}
    >
      {/* Add popover */}
      <Popover>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={BAR_ICON_BTN}
                aria-label={t('commandBar.addNode')}
              >
                <Plus className="w-3.5 h-3.5" />
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent>{t('commandBar.addNodeHotkey')}</TooltipContent>
        </Tooltip>
        <PopoverContent side="top" align="center" className="w-44 p-1">
          {NODE_TYPE_KEYS.map(({ type, icon: Icon }) => (
            <button
              key={type}
              onClick={() => onAddNode(type)}
              className="w-full flex items-center gap-2 px-2 py-1.5 text-sm rounded-md hover:bg-background-tertiary text-foreground-secondary hover:text-foreground transition-colors"
            >
              <Icon className="w-3.5 h-3.5 shrink-0" />
              {t(`commandBar.nodeTypes.${type}`)}
            </button>
          ))}
        </PopoverContent>
      </Popover>

      <BarButton
        icon={Copy}
        label={t('commandBar.duplicate')}
        hotkey="⌘D"
        onClick={onDuplicate}
        disabled={!selectedNodeId}
      />

      <BarButton
        icon={Trash2}
        label={t('commandBar.delete')}
        hotkey="⌫"
        onClick={onDelete}
        disabled={!selectedNodeId}
      />
    </div>
  );
}

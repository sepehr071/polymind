import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Trash2, Play } from 'lucide-react';
import { cn } from '../../utils/cn';

export default function NodeContextMenu({
  x,
  y,
  nodeId,
  nodeType,
  onDuplicate,
  onDelete,
  onRunNode,
  onClose
}) {
  const { t } = useTranslation('workflow');
  const menuRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        onClose();
      }
    };

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  const adjustedPosition = { left: x, top: y };

  if (typeof window !== 'undefined') {
    const menuWidth = 180;
    const menuHeight = 140;

    if (x + menuWidth > window.innerWidth) {
      adjustedPosition.left = x - menuWidth;
    }
    if (y + menuHeight > window.innerHeight) {
      adjustedPosition.top = y - menuHeight;
    }
  }

  const menuItems = [
    {
      icon: Copy,
      label: t('contextMenu.duplicate'),
      shortcut: 'Ctrl+D',
      onClick: () => {
        onDuplicate(nodeId);
        onClose();
      }
    },
    {
      icon: Play,
      label: t('contextMenu.runThisNode'),
      shortcut: null,
      onClick: () => {
        onRunNode(nodeId);
        onClose();
      },
      hidden: nodeType === 'imageUpload'
    },
    {
      icon: Trash2,
      label: t('contextMenu.delete'),
      shortcut: 'Del',
      onClick: () => {
        onDelete(nodeId);
        onClose();
      },
      danger: true
    }
  ];

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[180px] bg-background border border-border rounded-lg shadow-lg py-1 overflow-hidden"
      style={{
        left: adjustedPosition.left,
        top: adjustedPosition.top
      }}
    >
      {menuItems
        .filter(item => !item.hidden)
        .map((item) => (
          <button
            key={item.label}
            onClick={item.onClick}
            className={cn(
              'w-full px-3 py-2 flex items-center gap-3 text-sm transition-colors',
              'hover:bg-accent/50',
              item.danger && 'text-error hover:bg-error/10'
            )}
          >
            <item.icon className="w-4 h-4" />
            <span className="flex-1 text-start">{item.label}</span>
            {item.shortcut && (
              <span className="text-xs text-muted-foreground">{item.shortcut}</span>
            )}
          </button>
        ))}
    </div>
  );
}

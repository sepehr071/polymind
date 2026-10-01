import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Play, Type, Upload, Bot, Sparkles, Volume2, Video } from 'lucide-react';
import { cn } from '../../../utils/cn';
import { Button } from '@/components/ui/button';

import AIAgentInspector from './inspectors/AIAgentInspector';
import ImageGenInspector from './inspectors/ImageGenInspector';
import ImageUploadInspector from './inspectors/ImageUploadInspector';
import TextInputInspector from './inspectors/TextInputInspector';
import TTSInspector from './inspectors/TTSInspector';
import VideoGenInspector from './inspectors/VideoGenInspector';

const NODE_META = {
  textInput:    { labelKey: 'inspector.nodeMeta.textInput',    icon: Type,     color: 'text-accent' },
  imageUpload:  { labelKey: 'inspector.nodeMeta.imageUpload',  icon: Upload,   color: 'text-accent' },
  aiAgent:      { labelKey: 'inspector.nodeMeta.aiAgent',      icon: Bot,      color: 'text-violet' },
  imageGen:     { labelKey: 'inspector.nodeMeta.imageGen',     icon: Sparkles, color: 'text-ok' },
  ttsNode:      { labelKey: 'inspector.nodeMeta.ttsNode',      icon: Volume2,  color: 'text-warn' },
  videoGenNode: { labelKey: 'inspector.nodeMeta.videoGenNode', icon: Video,    color: 'text-pink' },
};

const TABS = ['configure', 'output', 'history'];

function InspectorBody({ node, activeTab, updateNodeData, onRunNode, runHistory, workflowId }) {
  const props = { node, activeTab, updateNodeData, onRunNode, runHistory, workflowId };
  switch (node.type) {
    case 'aiAgent':      return <AIAgentInspector {...props} />;
    case 'imageGen':     return <ImageGenInspector {...props} />;
    case 'imageUpload':  return <ImageUploadInspector {...props} />;
    case 'textInput':    return <TextInputInspector {...props} />;
    case 'ttsNode':      return <TTSInspector {...props} />;
    case 'videoGenNode': return <VideoGenInspector {...props} />;
    default:             return null;
  }
}

function InspectorContent({ node, updateNodeData, onClose, onRunNode, runHistory, isExecuting, workflowId }) {
  const { t } = useTranslation('workflow');
  const [activeTab, setActiveTab] = useState('configure');
  const metaDef = NODE_META[node.type];
  const metaLabel = metaDef ? t(metaDef.labelKey) : node.type;
  const meta = {
    label: metaLabel,
    icon: metaDef?.icon ?? Bot,
    color: metaDef?.color ?? 'text-foreground',
  };
  const Icon = meta.icon;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="h-14 px-4 border-b border-border flex items-center gap-3 shrink-0">
        <Icon className={cn('w-5 h-5 shrink-0', meta.color)} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-foreground truncate">{node.data?.label || meta.label}</div>
          <div className="text-xs text-foreground-tertiary">{meta.label} · {t('inspector.selected')}</div>
        </div>
        {onRunNode && (
          <Button
            size="icon"
            variant="ghost"
            className="w-7 h-7 shrink-0"
            onClick={() => onRunNode(node.id)}
            disabled={isExecuting}
            title={t('inspector.runThisNode')}
            aria-label={t('inspector.runThisNode')}
          >
            <Play className="w-3.5 h-3.5" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="w-7 h-7 shrink-0"
          onClick={onClose}
          aria-label={t('inspector.closeInspector')}
          title={t('inspector.closeInspector')}
        >
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Tab strip — canonical underline tabs (active = accent text + 2px
          accent bottom-border; inactive = foreground-secondary). */}
      <div className="flex border-b border-border shrink-0">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'flex-1 text-xs py-2 font-medium transition-colors focus:outline-none -mb-px border-b-2',
              activeTab === tab
                ? 'text-accent-hover border-accent'
                : 'text-foreground-secondary border-transparent hover:text-foreground'
            )}
          >
            {t(`inspector.tabs.${tab}`)}
          </button>
        ))}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        <InspectorBody
          node={node}
          activeTab={activeTab}
          updateNodeData={updateNodeData}
          onRunNode={onRunNode}
          runHistory={runHistory}
          workflowId={workflowId}
        />
      </div>
    </div>
  );
}

export default function NodeInspector({
  node,
  updateNodeData,
  onClose,
  onRunNode,
  onDuplicate,
  onDelete,
  runHistory,
  isMobile,
  isExecuting = false,
  workflowId = null,
}) {
  if (!node) return null;

  if (isMobile) {
    return (
      <>
        {/* Backdrop — hidden on mobile (full-screen), shown on sm+ as sheet backdrop */}
        <div
          className="fixed inset-0 bg-black/50 z-40 hidden sm:block"
          onClick={onClose}
        />
        {/* Inspector panel: full-screen on mobile, bottom-sheet on sm+. Flat
            content surface (not chrome) — overlay scrim stays for the sm+ sheet. */}
        <div
          className={cn(
            'fixed z-50 flex flex-col animate-slide-in-bottom bg-background shadow-xl',
            'inset-0 h-full max-h-full w-full rounded-none',
            'sm:inset-x-0 sm:inset-y-auto sm:bottom-0 sm:h-auto sm:max-h-[80vh] sm:w-auto sm:rounded-t-2xl sm:border-t sm:border-border',
          )}
        >
          <InspectorContent
            node={node}
            updateNodeData={updateNodeData}
            onClose={onClose}
            onRunNode={onRunNode}
            runHistory={runHistory}
            isExecuting={isExecuting}
            workflowId={workflowId}
          />
        </div>
      </>
    );
  }

  return (
    <div className="w-80 xl:w-96 shrink-0 flex flex-col overflow-hidden bg-background border-s border-border">
      <InspectorContent
        node={node}
        updateNodeData={updateNodeData}
        onClose={onClose}
        onRunNode={onRunNode}
        runHistory={runHistory}
        isExecuting={isExecuting}
        workflowId={workflowId}
      />
    </div>
  );
}

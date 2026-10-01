import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Loader2, MoreHorizontal, History, Play, AlertTriangle, CheckCircle2, LayoutTemplate, Wand2, Workflow as WorkflowIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { IconTile } from '@/components/ui/icon-tile';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '../../../utils/cn';
import HeaderSlot from '@/components/layout/HeaderSlot';
import { PrivacyBadge } from '@/components/privacy/ModelPrivacyCallout';
import { fmtDistanceToNow } from '@/utils/dateLocale';

// Locale-aware relative time ("۳ دقیقه پیش" / "3 minutes ago") — replaces the
// previous hardcoded English strings. `ts` is an epoch-ms timestamp.
function relativeTime(ts) {
  return fmtDistanceToNow(new Date(ts), { addSuffix: true });
}

function SaveStatusBadge({ isSaving, hasUnsavedChanges, lastSavedAt }) {
  const { t } = useTranslation('workflow');
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  if (isSaving) {
    return (
      <span className="hidden sm:flex items-center gap-1 text-xs text-foreground-secondary bg-background-tertiary rounded-full px-2 py-0.5 whitespace-nowrap">
        <Loader2 className="w-3 h-3 animate-spin" />
        {t('breadcrumb.saving')}
      </span>
    );
  }

  if (hasUnsavedChanges) {
    return (
      <span className="hidden sm:flex items-center gap-1 text-xs text-warning bg-warning/10 rounded-full px-2 py-0.5 whitespace-nowrap">
        <AlertTriangle className="w-3 h-3" />
        {t('breadcrumb.unsaved')}
      </span>
    );
  }

  if (lastSavedAt) {
    return (
      <span className="hidden sm:flex items-center gap-1 text-xs text-success bg-success/10 rounded-full px-2 py-0.5 whitespace-nowrap">
        <CheckCircle2 className="w-3 h-3" />
        {t('breadcrumb.saved', { time: relativeTime(lastSavedAt) })}
      </span>
    );
  }

  return null;
}

export default function WorkflowBreadcrumb({
  workflowName,
  onWorkflowNameChange,
  selectedWorkflow,
  nodes,
  isExecuting,
  isSaving,
  hasUnsavedChanges,
  lastSavedAt,
  onRun,
  onToggleHistory,
  showRunHistory,
  onNew,
  onSave,
  onLoad,
  onDuplicate,
  onDelete,
  onImport,
  onExport,
  importFileRef,
  onOpenTemplates,
  onOpenAIGenerator,
}) {
  const { t } = useTranslation('workflow');
  const [editingName, setEditingName] = useState(false);

  const nodePill = nodes.length
    ? t('breadcrumb.nodes', { count: nodes.length })
    : t('breadcrumb.empty');

  return (
    <>
      {/* Inline-start cluster: breadcrumb trail + editable name + status pills.
          Portalled into the global AppTopBar (no second glass header band). */}
      <HeaderSlot side="start">
        <div className="flex items-center gap-2 min-w-0">
          {/* Amber studio-zone identity tile (matches the PageHeader pattern). */}
          <IconTile icon={WorkflowIcon} tone="amber" size="sm" />
          <PrivacyBadge mode="cloud" className="hidden sm:inline-flex" />
          <span className="hidden sm:inline text-xs text-foreground-tertiary whitespace-nowrap">{t('breadcrumb.workflows')}</span>
          <ChevronRight className="hidden sm:block w-3.5 h-3.5 text-foreground-tertiary shrink-0" />

          {/* Inline-editable name */}
          {editingName ? (
            <input
              autoFocus
              type="text"
              value={workflowName}
              onChange={(e) => onWorkflowNameChange(e.target.value)}
              onBlur={() => setEditingName(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === 'Escape') setEditingName(false);
              }}
              className="min-w-0 w-40 text-sm font-medium bg-transparent border border-accent rounded-[10px] px-2 py-1 focus:outline-none focus:ring-2 focus:ring-accent/40 text-foreground"
            />
          ) : (
            <button
              onClick={() => setEditingName(true)}
              className="text-sm font-medium text-foreground hover:text-accent truncate min-w-0 max-w-[180px] focus:outline-none"
              title={t('breadcrumb.clickToRename')}
            >
              {workflowName || t('breadcrumb.untitledWorkflow')}
            </button>
          )}

          {/* Node count pill */}
          <span className="hidden md:inline text-xs text-foreground-tertiary bg-background-tertiary rounded-full px-2 py-0.5 whitespace-nowrap">
            {nodePill}
          </span>

          {/* Save status badge */}
          <SaveStatusBadge
            isSaving={isSaving}
            hasUnsavedChanges={hasUnsavedChanges}
            lastSavedAt={lastSavedAt}
          />
        </div>
      </HeaderSlot>

      {/* Inline-end cluster: primary actions + overflow. */}
      <HeaderSlot side="end">
        <div className="flex items-center gap-1.5">
      {/* Templates button */}
      {onOpenTemplates && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={onOpenTemplates}
              className="h-7 px-2 text-xs hidden sm:flex"
            >
              <LayoutTemplate className="w-3.5 h-3.5 me-1" />
              {t('breadcrumb.templates')}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('breadcrumb.browseTemplates')}</TooltipContent>
        </Tooltip>
      )}

      {/* AI Generate button */}
      {onOpenAIGenerator && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={onOpenAIGenerator}
              className="h-7 px-2 text-xs hidden sm:flex text-accent hover:text-accent"
            >
              <Wand2 className="w-3.5 h-3.5 me-1" />
              {t('breadcrumb.generate')}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('breadcrumb.generateFromBrief')}</TooltipContent>
        </Tooltip>
      )}

      {/* Runs history button */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleHistory}
            className={cn(
              'h-7 px-2 text-xs',
              showRunHistory && 'bg-accent-muted text-accent'
            )}
          >
            <History className="w-3.5 h-3.5 me-1" />
            {t('breadcrumb.runs')}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t('breadcrumb.toggleRunHistory')}</TooltipContent>
      </Tooltip>

      {/* Run button — disabled while saving too */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="default"
            size="sm"
            onClick={onRun}
            disabled={isExecuting || isSaving || nodes.length === 0}
            className="h-7 px-3 text-xs gap-1"
          >
            {isExecuting || isSaving ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            {isSaving ? t('breadcrumb.saving') : t('breadcrumb.run')}
            {!isExecuting && !isSaving && (
              <kbd className="ms-1 hidden sm:inline text-[10px] opacity-60 font-mono bg-white/10 rounded px-1">⌘↵</kbd>
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t('breadcrumb.runWorkflow')}</TooltipContent>
      </Tooltip>

      {/* Overflow menu */}
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                <MoreHorizontal className="w-4 h-4" />
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>{t('breadcrumb.moreActions')}</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuItem onClick={onNew}>{t('breadcrumb.new')}</DropdownMenuItem>
          <DropdownMenuItem onClick={onSave}>{t('breadcrumb.save')}</DropdownMenuItem>
          <DropdownMenuItem onClick={onLoad}>{t('breadcrumb.load')}</DropdownMenuItem>
          <DropdownMenuItem onClick={onDuplicate} disabled={!selectedWorkflow}>
            {t('breadcrumb.duplicate')}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={onDelete}
            disabled={!selectedWorkflow}
            className="text-error focus:text-error focus:bg-error/10"
          >
            {t('breadcrumb.delete')}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => importFileRef.current?.click()}>{t('breadcrumb.import')}</DropdownMenuItem>
          <DropdownMenuItem onClick={onExport} disabled={nodes.length === 0}>
            {t('breadcrumb.export')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Hidden file input for import */}
      <input
        type="file"
        ref={importFileRef}
        accept=".json"
        onChange={onImport}
        className="hidden"
      />
        </div>
      </HeaderSlot>
    </>
  );
}

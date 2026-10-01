import { useState, useEffect, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle2, XCircle, Loader2, Image, MessageSquare, Mic, Video, Type,
  Search, RotateCcw,
} from 'lucide-react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '../../../utils/cn';
import { fmtDate, fmtDistanceToNow } from '@/utils/dateLocale';

// ─── Helpers ──────────────────────────────────────────────────────────────────

// Locale-aware relative time ("۳ دقیقه پیش" / "3 minutes ago") — replaces the
// previous hardcoded English strings. date-fns picks fa vs en via dateLocale.
function relativeTime(dateStr) {
  return fmtDistanceToNow(new Date(dateStr), { addSuffix: true });
}

function formatDuration(ms) {
  if (ms == null || isNaN(ms)) return '—';
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

function runDurationMs(run) {
  if (!run.started_at || !run.completed_at) return null;
  return new Date(run.completed_at).getTime() - new Date(run.started_at).getTime();
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusIcon({ status, className }) {
  if (status === 'completed') return <CheckCircle2 className={cn('w-4 h-4 text-success shrink-0', className)} />;
  if (status === 'failed') return <XCircle className={cn('w-4 h-4 text-error shrink-0', className)} />;
  return <Loader2 className={cn('w-4 h-4 text-accent animate-spin shrink-0', className)} />;
}

const NODE_TYPE_ICONS = {
  imageGen: Image,
  imageUpload: Image,
  textInput: Type,
  aiAgent: MessageSquare,
  ttsNode: Mic,
  videoGenNode: Video,
};

function NodeResultRow({ nodeId, result, nodes, onRunNode }) {
  const { t } = useTranslation('workflow');
  const node = nodes?.find(n => n.id === nodeId);
  const label = node?.data?.label || nodeId;
  const type = node?.type || 'unknown';
  const Icon = NODE_TYPE_ICONS[type] || MessageSquare;

  const hasError = Boolean(result?.error);
  const timingMs = result?.generation_time_ms ?? null;

  return (
    <div className="py-2 px-3 border-b border-border last:border-0">
      {/* Header row */}
      <div className="flex items-center gap-2 mb-1.5">
        <Icon className="w-3.5 h-3.5 text-foreground-tertiary shrink-0" />
        <span className="text-xs font-medium text-foreground truncate flex-1">{label}</span>
        <Badge
          variant="outline"
          className={cn(
            'text-[10px] px-1.5 py-0 h-4 shrink-0',
            hasError ? 'border-error/40 text-error bg-error/5' : 'border-success/40 text-success bg-success/5'
          )}
        >
          {hasError ? t('runHistory.failed') : t('runHistory.success')}
        </Badge>
        {timingMs != null && (
          <span className="text-[10px] text-foreground-tertiary shrink-0">{formatDuration(timingMs)}</span>
        )}
        {onRunNode && (
          <Button
            size="icon"
            variant="ghost"
            className="w-5 h-5 shrink-0"
            onClick={() => onRunNode(nodeId)}
            title={t('runHistory.rerunNode')}
            aria-label={t('runHistory.rerunNode')}
          >
            <RotateCcw className="w-3 h-3" />
          </Button>
        )}
      </div>

      {/* Output preview */}
      {hasError ? (
        <p className="text-xs text-error leading-relaxed">{result.error}</p>
      ) : result?.image_data ? (
        <img
          src={`data:image/png;base64,${result.image_data}`}
          alt="Node output"
          className="w-20 h-20 object-cover rounded border border-border"
        />
      ) : result?.audio_data_uri ? (
        <audio
          controls
          src={result.audio_data_uri}
          className="w-full h-8"
          style={{ height: '32px' }}
        />
      ) : result?.video_url ? (
        <span className="text-xs text-foreground-secondary italic">{t('runHistory.videoOutput')}</span>
      ) : result?.text ? (
        <code className="block bg-background-tertiary rounded p-2 text-xs whitespace-pre-wrap break-words text-foreground-secondary leading-relaxed">
          {result.text.length > 200 ? `${result.text.slice(0, 200)}…` : result.text}
        </code>
      ) : null}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function RunHistoryPanel({ runHistory = [], nodes = [], nodeId, onRunNode }) {
  const { t } = useTranslation('workflow');
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [isNarrow, setIsNarrow] = useState(false);
  const containerRef = useRef(null);

  // Responsive layout: watch panel's own rendered width
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(([entry]) => {
      setIsNarrow(entry.contentRect.width < 500);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Auto-select most recent run when history changes
  useEffect(() => {
    if (!runHistory.length) { setSelectedRunId(null); return; }
    setSelectedRunId(prev => {
      const stillExists = prev && runHistory.some(r => r._id === prev);
      return stillExists ? prev : runHistory[0]._id;
    });
  }, [runHistory]);

  // Filter + search pipeline
  const filteredRuns = useMemo(() => {
    return runHistory.filter(run => {
      if (nodeId && !(run.node_results && nodeId in run.node_results)) return false;
      if (filter === 'success' && run.status !== 'completed') return false;
      if (filter === 'failed' && run.status !== 'failed') return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        const matchesNodeLabel = run.node_results
          ? Object.keys(run.node_results).some(nid => {
              const nd = nodes.find(n => n.id === nid);
              return nd?.data?.label?.toLowerCase().includes(q);
            })
          : false;
        const matchesId = run._id?.toLowerCase().includes(q);
        if (!matchesNodeLabel && !matchesId) return false;
      }
      return true;
    });
  }, [runHistory, filter, search, nodeId, nodes]);

  const selectedRun = filteredRuns.find(r => r._id === selectedRunId) ?? filteredRuns[0] ?? null;

  // ── Run list item ──
  function RunListItem({ run }) {
    const isSelected = run._id === selectedRun?._id;
    const durationMs = runDurationMs(run);
    return (
      <button
        onClick={() => setSelectedRunId(run._id)}
        className={cn(
          'w-full text-start px-3 py-2 flex items-center gap-2 rounded border transition-colors',
          'border-transparent hover:bg-background-tertiary hover:border-border',
          isSelected && 'bg-accent/5 border-accent/30'
        )}
      >
        <StatusIcon status={run.status} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-foreground">{formatDuration(durationMs)}</div>
          <div className="text-[10px] text-foreground-tertiary">{relativeTime(run.started_at)}</div>
        </div>
      </button>
    );
  }

  // ── Selected run detail ──
  function RunDetail({ run }) {
    if (!run) {
      return (
        <div className="flex items-center justify-center h-full text-sm text-foreground-secondary">
          {t('runHistory.selectRun')}
        </div>
      );
    }
    const durationMs = runDurationMs(run);
    const nodeEntries = Object.entries(run.node_results || {});

    return (
      <div className="flex flex-col h-full min-h-0">
        {/* Detail header */}
        <div className="p-3 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <StatusIcon status={run.status} />
            <span className="text-sm font-semibold capitalize text-foreground">{run.status}</span>
            <span className="ms-auto text-xs text-foreground-tertiary">{formatDuration(durationMs)}</span>
          </div>
          <div className="text-xs text-foreground-tertiary mt-1">
            {fmtDate(new Date(run.started_at), 'PPpp')}
          </div>
          {run.error && (
            <p className="mt-1.5 text-xs text-error">{run.error}</p>
          )}
        </div>

        {/* Per-node results */}
        <ScrollArea className="flex-1">
          {nodeEntries.length === 0 ? (
            <div className="p-4 text-xs text-foreground-secondary text-center">{t('runHistory.noNodeResults')}</div>
          ) : (
            nodeEntries.map(([nid, result]) => (
              <NodeResultRow key={nid} nodeId={nid} result={result} nodes={nodes} onRunNode={onRunNode} />
            ))
          )}
        </ScrollArea>
      </div>
    );
  }

  const emptyMessage = nodeId ? t('runHistory.noRunsForNode') : t('runHistory.noRuns');

  const FILTER_OPTIONS = [
    { key: 'all', label: t('runHistory.filters.all') },
    { key: 'success', label: t('runHistory.filters.success') },
    { key: 'failed', label: t('runHistory.filters.failed') },
  ];

  return (
    <div
      ref={containerRef}
      className="min-w-[300px] flex flex-col h-full"
    >
      {/* Panel header */}
      <div className="px-3 pt-3 pb-2 shrink-0">
        <h3 className="text-sm font-semibold text-foreground mb-2">{t('runHistory.title')}</h3>

        {/* Filter + search row */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Canonical segmented control: hover-bg container + 1px line +
              radius11 pad4; active = surface + small shadow (not solid fill). */}
          <div className="flex items-center gap-1 rounded-[11px] border border-border bg-background-tertiary p-1 text-xs shrink-0">
            {FILTER_OPTIONS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={cn(
                  'px-2.5 py-1 rounded-md transition-colors',
                  filter === key
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-foreground-secondary hover:text-foreground'
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="relative flex-1 min-w-[100px]">
            <Search className="absolute start-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-foreground-tertiary pointer-events-none z-10" />
            <Input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={t('runHistory.searchPlaceholder')}
              size="sm"
              className="ps-8"
            />
          </div>
        </div>
      </div>

      {/* Body */}
      {runHistory.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-sm text-foreground-secondary px-4 text-center">
          {emptyMessage}
        </div>
      ) : isNarrow ? (
        /* ── Narrow: stacked vertical ── */
        <div className="flex flex-col flex-1 min-h-0">
          {/* Run list — fixed height when stacked */}
          <div className="border-b border-border shrink-0 max-h-40 overflow-y-auto">
            <div className="p-2 space-y-1">
              {filteredRuns.length === 0 ? (
                <div className="text-xs text-foreground-secondary text-center py-2">{t('runHistory.noRunsMatch')}</div>
              ) : (
                filteredRuns.slice(0, 20).map(run => <RunListItem key={run._id} run={run} />)
              )}
            </div>
          </div>
          {/* Detail below */}
          <div className="flex-1 min-h-0">
            <RunDetail run={selectedRun} />
          </div>
        </div>
      ) : (
        /* ── Wide: 2-column ── */
        <div className="flex flex-1 min-h-0">
          {/* Left: run list */}
          <div className="w-44 shrink-0 border-e border-border flex flex-col min-h-0">
            <ScrollArea className="flex-1">
              <div className="p-2 space-y-1">
                {filteredRuns.length === 0 ? (
                  <div className="text-xs text-foreground-secondary text-center py-4">{t('runHistory.noRunsMatch')}</div>
                ) : (
                  filteredRuns.slice(0, 20).map(run => <RunListItem key={run._id} run={run} />)
                )}
              </div>
            </ScrollArea>
          </div>

          {/* Right: detail */}
          <div className="flex-1 min-w-0 flex flex-col min-h-0">
            <RunDetail run={selectedRun} />
          </div>
        </div>
      )}
    </div>
  );
}

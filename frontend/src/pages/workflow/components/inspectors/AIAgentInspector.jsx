import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Bot, Copy, Check, Maximize2, ChevronDown, ChevronUp } from 'lucide-react';
import { AI_AGENT_MODELS } from '@/constants/workflowModels';
import { PLATFORM_PRESETS } from '@/constants/platformPresets';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { getTextDirection, containsRTL } from '@/utils/rtl';
import { ConfigSection, Field } from './NodeConfigForm';
import OutputActionBar from '../OutputActionBar';
import { knowledgeFolderService } from '@/services/knowledgeFolderService';
import { useProject } from '@/context/ProjectContext';

const VARIANT_OPTIONS = [1, 3, 5, 10];

export default function AIAgentInspector({ node, activeTab, updateNodeData, runHistory = [], workflowId = null }) {
  const { t } = useTranslation('workflow');
  const { data } = node;
  const { currentProject } = useProject();

  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [modalVariantIndex, setModalVariantIndex] = useState(null);

  const [variantCopied, setVariantCopied] = useState({});
  const [variantExpanded, setVariantExpanded] = useState({});

  const [folders, setFolders] = useState([]);
  const [foldersLoading, setFoldersLoading] = useState(false);

  useEffect(() => {
    if (activeTab !== 'configure') return;
    let cancelled = false;
    setFoldersLoading(true);
    const params = currentProject?._id
      ? { project_id: currentProject._id }
      : {};
    knowledgeFolderService
      .list(params)
      .then((result) => {
        if (!cancelled) {
          const list = Array.isArray(result) ? result : result?.folders ?? [];
          setFolders(list);
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setFoldersLoading(false); });
    return () => { cancelled = true; };
  }, [activeTab, currentProject?._id]);

  const handleCopy = useCallback(() => {
    if (data.output) {
      navigator.clipboard.writeText(data.output);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [data.output]);

  const handleVariantCopy = useCallback((index, text) => {
    navigator.clipboard.writeText(text);
    setVariantCopied((prev) => ({ ...prev, [index]: true }));
    setTimeout(() => setVariantCopied((prev) => ({ ...prev, [index]: false })), 2000);
  }, []);

  const handleVariantToggleExpand = useCallback((index) => {
    setVariantExpanded((prev) => ({ ...prev, [index]: !prev[index] }));
  }, []);

  const vars = data.userPromptTemplate
    ? [...new Set([...data.userPromptTemplate.matchAll(/\{\{([a-zA-Z_]+)\}\}/g)].map((m) => m[1]))]
    : [];

  const nodeHistory = runHistory.filter((r) => r.nodeId === node.id);

  const handlePresetSelect = useCallback((presetKey) => {
    const preset = PLATFORM_PRESETS[presetKey];
    if (!preset) return;
    const currentPrompt = data.systemPrompt || '';
    const isOwnedByPreset =
      !currentPrompt ||
      Object.values(PLATFORM_PRESETS).some((p) => p.systemPrompt === currentPrompt);
    updateNodeData(node.id, {
      platformPreset: presetKey,
      maxChars: preset.maxChars,
      ...(isOwnedByPreset ? { systemPrompt: preset.systemPrompt } : {}),
    });
  }, [data.systemPrompt, node.id, updateNodeData]);

  const textVariants = Array.isArray(data.textVariants) && data.textVariants.length > 0
    ? data.textVariants
    : null;

  // ---------- OUTPUT TAB ----------
  if (activeTab === 'output') {
    if (textVariants) {
      const totalVariants = textVariants.length;
      const modalText = modalVariantIndex != null ? textVariants[modalVariantIndex] : null;

      return (
        <div className="p-4 space-y-4 overflow-y-auto h-full">
          {(data.lastRunDuration != null || data.lastRunTokens != null) && (
            <div className="bg-success/10 text-success rounded-lg px-3 py-2 text-xs">
              {t('aiAgentInspector.lastRun')}
              {data.lastRunDuration != null && <span> · {data.lastRunDuration}s</span>}
              {data.lastRunTokens != null && <span> · {data.lastRunTokens} {t('aiAgentInspector.tokens')}</span>}
            </div>
          )}

          {textVariants.map((variant, i) => {
            const isExp = !!variantExpanded[i];
            const isCop = !!variantCopied[i];
            const isRTL = containsRTL(variant);
            return (
              <div key={i} className="bg-success/10 border border-success/20 rounded-lg overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-success/20 bg-success/5">
                  <span className="text-xs font-medium text-success">
                    {t('aiAgentInspector.variantOf', { index: i + 1, total: totalVariants })}
                  </span>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost" size="icon" className="h-6 w-6"
                      onClick={() => handleVariantCopy(i, variant)}
                      title={t('aiAgentInspector.copyVariant')}
                    >
                      {isCop ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
                    </Button>
                    <Button
                      variant="ghost" size="icon" className="h-6 w-6"
                      onClick={() => { setModalVariantIndex(i); setShowModal(true); }}
                      title={t('aiAgentInspector.viewFullscreen')}
                    >
                      <Maximize2 className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost" size="icon" className="h-6 w-6"
                      onClick={() => handleVariantToggleExpand(i)}
                      title={isExp ? t('aiAgentInspector.collapse') : t('aiAgentInspector.expand')}
                    >
                      {isExp ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </Button>
                  </div>
                </div>
                <div className={`p-3 text-xs text-foreground overflow-y-auto ${isExp ? 'max-h-96' : 'max-h-32'}`}>
                  <pre
                    className={`whitespace-pre-wrap font-sans ${isRTL ? 'font-persian' : ''}`}
                    dir={getTextDirection(variant)}
                  >
                    {isExp ? variant : variant.length > 300 ? `${variant.slice(0, 300)}…` : variant}
                  </pre>
                </div>
                <div className="px-3 pb-3">
                  <OutputActionBar outputType="text" text={variant} knowledgeTitle={t('aiAgentInspector.variantKnowledgeTitle', { index: i + 1 })} workflowId={workflowId} nodeId={node.id} />
                </div>
              </div>
            );
          })}

          <Dialog open={showModal && modalText != null} onOpenChange={setShowModal}>
            <DialogContent showClose={false} className="max-w-2xl max-h-[80vh] flex flex-col p-0 gap-0">
              {modalText != null && (
                <>
                  <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <div className="flex items-center gap-2">
                      <Bot className="h-5 w-5 text-accent" />
                      <span className="font-medium text-foreground">{t('aiAgentInspector.variantOf', { index: modalVariantIndex + 1, total: totalVariants })}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => handleVariantCopy(modalVariantIndex, modalText)}>
                        {variantCopied[modalVariantIndex] ? (
                          <><Check className="h-4 w-4 text-success me-1" />{t('aiAgentInspector.copied')}</>
                        ) : (
                          <><Copy className="h-4 w-4 me-1" />{t('aiAgentInspector.copy')}</>
                        )}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => setShowModal(false)}>{t('aiAgentInspector.close')}</Button>
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto p-4">
                    <pre
                      className={`whitespace-pre-wrap text-sm font-sans text-foreground ${containsRTL(modalText) ? 'font-persian' : ''}`}
                      dir={getTextDirection(modalText)}
                    >
                      {modalText}
                    </pre>
                  </div>
                </>
              )}
            </DialogContent>
          </Dialog>
        </div>
      );
    }

    return (
      <div className="p-4 space-y-4 overflow-y-auto h-full">
        {data.output ? (
          <>
            {(data.lastRunDuration != null || data.lastRunTokens != null) && (
              <div className="bg-success/10 text-success rounded-lg px-3 py-2 text-xs">
                {t('aiAgentInspector.lastRun')}
                {data.lastRunDuration != null && <span> · {data.lastRunDuration}s</span>}
                {data.lastRunTokens != null && <span> · {data.lastRunTokens} {t('aiAgentInspector.tokens')}</span>}
              </div>
            )}
            <div className="bg-success/10 border border-success/20 rounded-lg overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-success/20 bg-success/5">
                <span className="text-xs font-medium text-success">{t('aiAgentInspector.output')}</span>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopy} title={t('aiAgentInspector.copyOutput')}>
                    {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
                  </Button>
                  <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setShowModal(true)} title={t('aiAgentInspector.viewFullscreen')}>
                    <Maximize2 className="h-3 w-3" />
                  </Button>
                  <Button
                    variant="ghost" size="icon" className="h-6 w-6"
                    onClick={() => setExpanded((v) => !v)}
                    title={expanded ? t('aiAgentInspector.collapse') : t('aiAgentInspector.expand')}
                  >
                    {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  </Button>
                </div>
              </div>
              <div className={`p-3 text-xs text-foreground overflow-y-auto ${expanded ? 'max-h-96' : 'max-h-32'}`}>
                <pre
                  className={`whitespace-pre-wrap font-sans ${containsRTL(data.output) ? 'font-persian' : ''}`}
                  dir={getTextDirection(data.output)}
                >
                  {expanded
                    ? data.output
                    : data.output.length > 300
                    ? `${data.output.slice(0, 300)}…`
                    : data.output}
                </pre>
              </div>
            </div>
            <OutputActionBar outputType="text" text={data.output} knowledgeTitle={t('aiAgentInspector.outputKnowledgeTitle')} workflowId={workflowId} nodeId={node.id} />
          </>
        ) : (
          <p className="text-sm text-foreground-secondary italic">{t('aiAgentInspector.noOutput')}</p>
        )}

        <Dialog open={showModal && !!data.output} onOpenChange={setShowModal}>
          <DialogContent showClose={false} className="max-w-2xl max-h-[80vh] flex flex-col p-0 gap-0">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <Bot className="h-5 w-5 text-accent" />
                <span className="font-medium text-foreground">{t('aiAgentInspector.modalTitle')}</span>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={handleCopy}>
                  {copied ? (
                    <><Check className="h-4 w-4 text-success me-1" />{t('aiAgentInspector.copied')}</>
                  ) : (
                    <><Copy className="h-4 w-4 me-1" />{t('aiAgentInspector.copy')}</>
                  )}
                </Button>
                <Button variant="outline" size="sm" onClick={() => setShowModal(false)}>{t('aiAgentInspector.close')}</Button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <pre
                className={`whitespace-pre-wrap text-sm font-sans text-foreground ${containsRTL(data.output || '') ? 'font-persian' : ''}`}
                dir={getTextDirection(data.output || '')}
              >
                {data.output}
              </pre>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  // ---------- HISTORY TAB ----------
  if (activeTab === 'history') {
    return (
      <div className="p-4 space-y-3 overflow-y-auto h-full">
        {nodeHistory.length === 0 ? (
          <p className="text-sm text-foreground-secondary italic">{t('inspector.noRunsNode')}</p>
        ) : (
          nodeHistory.map((run, i) => (
            <div key={i} className="border border-border rounded-lg p-3 text-xs space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-medium text-foreground">{run.status ?? 'completed'}</span>
                <span className="text-foreground-tertiary">{run.createdAt ?? ''}</span>
              </div>
              {run.output && (
                <p className="text-foreground-secondary truncate">{run.output.slice(0, 120)}</p>
              )}
            </div>
          ))
        )}
      </div>
    );
  }

  // ---------- CONFIGURE TAB ----------
  const selectedModel = AI_AGENT_MODELS.find((m) => m.id === (data.model || AI_AGENT_MODELS[0].id));
  const costPills = selectedModel && (selectedModel.costIn != null || selectedModel.ctx != null) ? (
    <div className="flex gap-1.5 flex-wrap mt-1.5">
      {selectedModel.costIn != null && (
        <span className="text-[11px] bg-accent/10 text-accent rounded px-1.5 py-0.5">
          ${selectedModel.costIn}/1k in
        </span>
      )}
      {selectedModel.ctx != null && (
        <span className="text-[11px] bg-accent/10 text-accent rounded px-1.5 py-0.5">
          {selectedModel.ctx} ctx
        </span>
      )}
    </div>
  ) : null;

  const activePreset = data.platformPreset && PLATFORM_PRESETS[data.platformPreset]
    ? PLATFORM_PRESETS[data.platformPreset]
    : null;

  return (
    <ConfigSection>
      <Field label={t('aiAgentInspector.fields.model')}>
        <Select
          value={data.model || AI_AGENT_MODELS[0].id}
          onValueChange={(val) => updateNodeData(node.id, { model: val })}
        >
          <SelectTrigger className="text-sm" dir="ltr">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AI_AGENT_MODELS.map((m) => (
              <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {costPills}
      </Field>

      <Field label={t('aiAgentInspector.fields.platform')}>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(PLATFORM_PRESETS).map(([key, preset]) => {
            const isActive = data.platformPreset === key;
            return (
              <Button
                key={key}
                size="sm"
                variant={isActive ? 'default' : 'outline'}
                className="h-7 px-2.5 text-xs"
                onClick={() => handlePresetSelect(key)}
              >
                {preset.label}
              </Button>
            );
          })}
        </div>
        {activePreset && (
          <p className="text-[11px] text-foreground-tertiary mt-1">
            {t('aiAgentInspector.maxChars', { count: activePreset.maxChars.toLocaleString() })}
          </p>
        )}
      </Field>

      <Field label={t('aiAgentInspector.fields.systemPrompt')}>
        <Textarea
          rows={4}
          placeholder={t('aiAgentInspector.placeholders.systemPrompt')}
          value={data.systemPrompt || ''}
          onChange={(e) => updateNodeData(node.id, { systemPrompt: e.target.value })}
          className="text-sm resize-none"
          dir="ltr"
        />
      </Field>

      <Field label={t('aiAgentInspector.fields.brandBrief')}>
        <Select
          value={data.knowledgeFolderId || '__none__'}
          onValueChange={(val) =>
            updateNodeData(node.id, { knowledgeFolderId: val === '__none__' ? null : val })
          }
          disabled={foldersLoading}
        >
          <SelectTrigger className="text-sm">
            <SelectValue placeholder={foldersLoading ? t('aiAgentInspector.loadingFolders') : t('aiAgentInspector.noFolder')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">{t('aiAgentInspector.noFolder')}</SelectItem>
            {folders.map((f) => (
              <SelectItem key={f._id} value={f._id}>{f.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label={t('aiAgentInspector.fields.variants')}>
        <Select
          value={String(data.variants ?? 1)}
          onValueChange={(val) => updateNodeData(node.id, { variants: Number(val) })}
        >
          <SelectTrigger className="text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {VARIANT_OPTIONS.map((n) => (
              <SelectItem key={n} value={String(n)}>
                {n === 1 ? t('aiAgentInspector.variantSingle') : t('aiAgentInspector.variantCount', { count: n })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field
        label={t('aiAgentInspector.fields.userPrompt')}
        help={vars.length > 0 ? t('aiAgentInspector.inputVars', { count: vars.length }) : undefined}
      >
        <Textarea
          rows={3}
          placeholder={t('aiAgentInspector.placeholders.userPrompt')}
          value={data.userPromptTemplate || '{{input}}'}
          onChange={(e) => updateNodeData(node.id, { userPromptTemplate: e.target.value })}
          className="text-sm resize-none"
          dir="ltr"
        />
        {vars.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {vars.map((v) => (
              <span key={v} className="bg-accent/10 text-accent rounded px-1.5 py-0.5 text-[11px]">
                {`{{${v}}}`}
              </span>
            ))}
          </div>
        )}
      </Field>

      {data.output && (data.lastRunDuration != null || data.lastRunTokens != null) && (
        <div className="bg-success/10 text-success rounded-lg px-3 py-2 text-xs">
          {t('aiAgentInspector.lastRun')}
          {data.lastRunDuration != null && <span> · {data.lastRunDuration}s</span>}
          {data.lastRunTokens != null && <span> · {data.lastRunTokens} {t('aiAgentInspector.tokens')}</span>}
        </div>
      )}
    </ConfigSection>
  );
}

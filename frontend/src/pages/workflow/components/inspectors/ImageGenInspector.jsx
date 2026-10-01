import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useModelCatalog } from '@/hooks/useModelCatalog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { ConfigSection, Field } from './NodeConfigForm';
import OutputActionBar from '../OutputActionBar';

const ASPECT_RATIO_OPTIONS = [
  { value: '1:1',  label: '1:1 — Feed' },
  { value: '9:16', label: '9:16 — Reel / Story / TikTok' },
  { value: '16:9', label: '16:9 — LinkedIn / YouTube thumb' },
  { value: '4:5',  label: '4:5 — Portrait Feed' },
];

const STYLE_PRESET_IDS = ['photorealistic', 'illustration', 'minimalist', 'bold-brand'];

export default function ImageGenInspector({ node, activeTab, updateNodeData, runHistory = [], workflowId = null }) {
  const { t } = useTranslation('workflow');
  const { data } = node;
  const { imageGenModels: catalogModels } = useModelCatalog();

  const IMAGE_GEN_MODELS = catalogModels.map(m => ({
    id: m._id || m.id,
    name: m.label || m.name,
    maxInputs: m.maxInputs ?? 16,
  }));

  const handleDownload = useCallback(() => {
    if (!data.generatedImage) return;
    const a = document.createElement('a');
    a.href = data.generatedImage;
    a.download = 'generated-image.png';
    a.click();
  }, [data.generatedImage]);

  const nodeHistory = runHistory.filter((r) => r.nodeId === node.id);
  const selectedModel = IMAGE_GEN_MODELS.find((m) => m.id === data.model) || IMAGE_GEN_MODELS[0];

  if (activeTab === 'output') {
    return (
      <div className="p-4 space-y-4 overflow-y-auto h-full">
        {data.generatedImage ? (
          <>
            <img
              src={data.generatedImage}
              alt={t('imageGenInspector.generatedAlt')}
              className="w-full rounded-lg border border-border object-contain max-h-72"
            />
            <OutputActionBar
              outputType="image"
              url={data.generatedImage}
              filename="generated-image.png"
              knowledgeTitle={t('imageGenInspector.knowledgeTitle')}
              workflowId={workflowId}
              nodeId={node.id}
            />
          </>
        ) : (
          <p className="text-sm text-foreground-secondary italic">{t('imageGenInspector.noOutput')}</p>
        )}
      </div>
    );
  }

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
                <img src={run.output} alt="" className="w-full rounded object-cover h-24" />
              )}
            </div>
          ))
        )}
      </div>
    );
  }

  // Configure tab
  return (
    <ConfigSection>
      <Field
        label={t('imageGenInspector.fields.model')}
        help={t('imageGenInspector.maxRefImages', { count: selectedModel?.maxInputs ?? 16 })}
      >
        <Select
          value={data.model || IMAGE_GEN_MODELS[0]?.id}
          onValueChange={(val) => updateNodeData(node.id, { model: val })}
        >
          <SelectTrigger className="text-sm" dir="ltr">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {IMAGE_GEN_MODELS.map((m) => (
              <SelectItem key={m.id} value={m.id}>
                {m.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label={t('imageGenInspector.fields.aspectRatio')}>
        <Select
          value={data.aspect_ratio || '1:1'}
          onValueChange={(val) => updateNodeData(node.id, { aspect_ratio: val })}
        >
          <SelectTrigger className="text-sm" dir="ltr">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ASPECT_RATIO_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label={t('imageGenInspector.fields.style')}>
        <div className="flex flex-wrap gap-1.5">
          {STYLE_PRESET_IDS.map((id) => {
            const isActive = data.style_preset === id;
            return (
              <Button
                key={id}
                variant={isActive ? 'default' : 'outline'}
                size="sm"
                className="h-7 px-2.5 text-xs"
                onClick={() =>
                  updateNodeData(node.id, {
                    style_preset: isActive ? null : id,
                  })
                }
              >
                {t(`imageGenInspector.stylePresets.${id}`)}
              </Button>
            );
          })}
        </div>
      </Field>

      <Field label={t('imageGenInspector.fields.prompt')}>
        <Textarea
          rows={4}
          placeholder={t('imageGenInspector.placeholders.prompt')}
          value={data.prompt || ''}
          onChange={(e) => updateNodeData(node.id, { prompt: e.target.value })}
          className="text-sm resize-none"
          dir="ltr"
        />
      </Field>

      <Field label={t('imageGenInspector.fields.negativePrompt')}>
        <Textarea
          rows={2}
          placeholder={t('imageGenInspector.placeholders.negativePrompt')}
          value={data.negativePrompt || ''}
          onChange={(e) => updateNodeData(node.id, { negativePrompt: e.target.value })}
          className="text-sm resize-none"
          dir="ltr"
        />
      </Field>

      <Field
        label={t('imageGenInspector.fields.referenceImages')}
        help={t('imageGenInspector.referenceHelp', { count: selectedModel?.maxInputs ?? 16 })}
      />
    </ConfigSection>
  );
}

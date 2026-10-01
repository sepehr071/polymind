import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check } from 'lucide-react';
import { TTS_MODELS, TTS_VOICES, TTS_SPEED } from '@/constants/workflowModels';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { ConfigSection, Field } from './NodeConfigForm';
import OutputActionBar from '../OutputActionBar';

export default function TTSInspector({ node, activeTab, updateNodeData, runHistory = [], workflowId = null }) {
  const { t } = useTranslation('workflow');
  const { data } = node;
  const [copied, setCopied] = useState(false);

  const speed = typeof data.speed === 'number' ? data.speed : TTS_SPEED.default;
  const durationSec = data.durationMs ? (data.durationMs / 1000).toFixed(1) : null;
  const nodeHistory = runHistory.filter((r) => r.nodeId === node.id);

  const handleCopyUrl = useCallback(() => {
    if (data.audioDataUri) {
      navigator.clipboard.writeText(data.audioDataUri);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [data.audioDataUri]);

  if (activeTab === 'output') {
    return (
      <div className="p-4 space-y-4 overflow-y-auto h-full">
        {data.audioDataUri ? (
          <>
            <div className="bg-success/10 border border-success/20 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-success">
                  {durationSec
                    ? t('ttsInspector.audioDuration', { duration: durationSec })
                    : t('ttsInspector.audio')}
                </span>
                <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopyUrl} title={t('ttsInspector.copyDataUrl')}>
                  {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
                </Button>
              </div>
              <audio controls src={data.audioDataUri} className="w-full" />
            </div>
            <OutputActionBar
              outputType="audio"
              audioDataUri={data.audioDataUri}
              filename="generated-audio.mp3"
              knowledgeTitle={t('ttsInspector.knowledgeTitle')}
              workflowId={workflowId}
              nodeId={node.id}
            />
          </>
        ) : (
          <p className="text-sm text-foreground-secondary italic">{t('ttsInspector.noOutput')}</p>
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
            </div>
          ))
        )}
      </div>
    );
  }

  // Configure tab
  return (
    <ConfigSection>
      <Field label={t('ttsInspector.fields.text')}>
        <Textarea
          rows={4}
          placeholder={t('ttsInspector.placeholders.text')}
          value={data.text || ''}
          onChange={(e) => updateNodeData(node.id, { text: e.target.value })}
          className="text-sm resize-none"
        />
      </Field>

      <Field label={t('ttsInspector.fields.model')}>
        <Select
          value={data.model || TTS_MODELS[0].id}
          onValueChange={(val) => updateNodeData(node.id, { model: val })}
        >
          <SelectTrigger className="text-sm" dir="ltr">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TTS_MODELS.map((m) => (
              <SelectItem key={m.id} value={m.id}>
                {m.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label={t('ttsInspector.fields.voice')}>
        <Select
          value={data.voice || TTS_VOICES[0]}
          onValueChange={(val) => updateNodeData(node.id, { voice: val })}
        >
          <SelectTrigger className="text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TTS_VOICES.map((v) => (
              <SelectItem key={v} value={v}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-xs font-semibold uppercase tracking-wide text-foreground-secondary">
            {t('ttsInspector.fields.speed')}
          </Label>
          <span className="text-xs font-mono text-foreground-secondary">{speed.toFixed(1)}x</span>
        </div>
        <Slider
          min={TTS_SPEED.min}
          max={TTS_SPEED.max}
          step={TTS_SPEED.step}
          value={[speed]}
          onValueChange={([val]) => updateNodeData(node.id, { speed: val })}
          className="w-full"
        />
      </div>
    </ConfigSection>
  );
}

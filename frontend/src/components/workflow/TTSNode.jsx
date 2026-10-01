import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Volume2 } from 'lucide-react';
import { TTS_VOICES } from '../../constants/workflowModels';
import CompactNodeShell from './CompactNodeShell';

function TTSNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const voice = data.voice && TTS_VOICES.includes(data.voice) ? data.voice : null;
  const speed = typeof data.speed === 'number' ? data.speed : 1.0;
  const summary = voice ? `${voice} · ${speed.toFixed(1)}x` : t('nodeDefaults.chooseVoice');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={!!data.isRunning}
      hasError={!!data.hasError}
      errorMessage={data.errorMessage || null}
      icon={Volume2}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeDefaults.voiceover')}
      statusDot={data.audioDataUri ? 'ok' : null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.scriptText') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.audioOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(TTSNode);

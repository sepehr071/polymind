import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Video } from 'lucide-react';
import { VIDEO_GEN_MODELS, VIDEO_MODEL_SPECS } from '../../constants/workflowModels';
import CompactNodeShell from './CompactNodeShell';

function VideoGenNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const modelId = VIDEO_GEN_MODELS.find((m) => m.id === data.model)
    ? data.model
    : VIDEO_GEN_MODELS[0].id;
  const spec = VIDEO_MODEL_SPECS[modelId] || {};

  const duration = spec.durations?.includes(data.duration)
    ? data.duration
    : (VIDEO_GEN_MODELS.find((m) => m.id === modelId)?.defaultDuration ?? 8);
  const resolution = spec.resolutions?.includes(data.resolution)
    ? data.resolution
    : (VIDEO_GEN_MODELS.find((m) => m.id === modelId)?.defaultResolution ?? '1080p');
  const aspectRatio = spec.aspectRatios?.includes(data.aspectRatio)
    ? data.aspectRatio
    : (VIDEO_GEN_MODELS.find((m) => m.id === modelId)?.defaultAspectRatio ?? '16:9');

  const isRendering = data.isRunning || data.status === 'in_progress' || data.status === 'pending';

  const summaryText = `${resolution} · ${duration}s · ${aspectRatio}`;
  const summary = isRendering ? (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-accent/20 text-accent font-medium">
        {data.progress != null
          ? t('nodeDefaults.renderingProgress', { progress: data.progress })
          : t('nodeDefaults.rendering')}
      </span>
    </span>
  ) : (
    summaryText
  );

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={isRendering}
      hasError={data.status === 'failed' || !!data.hasError}
      errorMessage={data.errorMessage || null}
      icon={Video}
      iconColor="bg-warning/10"
      iconTextColor="text-warning"
      title={data.label || t('nodeDefaults.video')}
      statusDot={data.videoUrl ? 'ok' : data.status === 'failed' ? 'error' : null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[
        { id: 'frame_image', top: '30%', label: t('nodeHandles.keyframeImage') },
        { id: 'prompt_text', top: '70%', label: t('nodeHandles.promptText') },
      ]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.videoOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(VideoGenNode);

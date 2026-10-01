import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload } from 'lucide-react';
import CompactNodeShell from './CompactNodeShell';

function ImageUploadNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');

  const summary = data.imageUrl ? (
    <span className="flex items-center gap-1 truncate">
      <img
        src={data.imageUrl}
        alt=""
        className="h-3 w-3 rounded object-cover flex-shrink-0"
      />
      <span className="truncate">{data.imageName || t('nodeDefaults.imageLoaded')}</span>
    </span>
  ) : (
    data.imageName || t('nodeDefaults.noImage')
  );

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Upload}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeDefaults.referenceImage')}
      statusDot={data.imageUrl ? 'ok' : null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.imageOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(ImageUploadNode);

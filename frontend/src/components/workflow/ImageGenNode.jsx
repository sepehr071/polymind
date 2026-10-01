import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import { useModelCatalog } from '@/hooks/useModelCatalog';
import CompactNodeShell from './CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function ImageGenNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const promptSnippet = truncate(data.prompt, 40);

  const summary = (
    <span className="flex items-center gap-1 truncate">
      {data.generatedImage && (
        <img
          src={data.generatedImage}
          alt=""
          className="h-3 w-3 rounded object-cover flex-shrink-0"
        />
      )}
      <span className="truncate">{promptSnippet || t('nodeDefaults.noImage')}</span>
    </span>
  );

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={!!data.isRunning}
      hasError={!!data.hasError}
      errorMessage={data.errorMessage || null}
      icon={Sparkles}
      iconColor="bg-success/10"
      iconTextColor="text-success"
      title={data.label || t('nodeDefaults.image')}
      statusDot={data.generatedImage ? 'ok' : null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[
        { id: 'input-0', top: '30%', label: t('nodeHandles.reference1') },
        { id: 'input-1', top: '50%', label: t('nodeHandles.reference2') },
        { id: 'input-2', top: '70%', label: t('nodeHandles.reference3') },
      ]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.imageOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(ImageGenNode);

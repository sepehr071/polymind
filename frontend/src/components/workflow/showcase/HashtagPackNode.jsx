import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Hash } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

function HashtagPackNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const count = Number(data.count) || 0;
  const platform = data.platform || t('nodeRail.nodes.hashtagPackNode.description');
  const summary = count > 0 ? `${platform} · ${count}` : platform;

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Hash}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeRail.nodes.hashtagPackNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(HashtagPackNode);

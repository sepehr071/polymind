import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Target } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function AudienceMatchNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const summary = data.audience
    ? truncate(data.audience, 36)
    : t('nodeRail.nodes.audienceMatchNode.description');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Target}
      iconColor="bg-warning/10"
      iconTextColor="text-warning"
      title={data.label || t('nodeRail.nodes.audienceMatchNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(AudienceMatchNode);

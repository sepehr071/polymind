import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Brackets } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function JSONTransformNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const summary = data.expression
    ? truncate(data.expression, 36)
    : t('nodeRail.nodes.jsonTransformNode.description');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Brackets}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeRail.nodes.jsonTransformNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(JSONTransformNode);

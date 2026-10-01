import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Boxes } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function APICallNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const method = (data.method || 'GET').toUpperCase();
  const url = data.url ? truncate(data.url, 28) : t('nodeRail.nodes.apiCallNode.description');
  const summary = data.url ? `${method} · ${url}` : url;

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Boxes}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeRail.nodes.apiCallNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(APICallNode);

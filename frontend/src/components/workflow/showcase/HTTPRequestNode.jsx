import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function HTTPRequestNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const method = (data.method || 'GET').toUpperCase();
  const url = data.url ? truncate(data.url, 28) : t('nodeRail.nodes.httpRequestNode.description');
  const summary = data.url ? `${method} · ${url}` : url;

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Globe}
      iconColor="bg-success/10"
      iconTextColor="text-success"
      title={data.label || t('nodeRail.nodes.httpRequestNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(HTTPRequestNode);

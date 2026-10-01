import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Webhook } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function WebhookTriggerNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const summary = data.path
    ? truncate(data.path, 36)
    : t('nodeRail.nodes.webhookTriggerNode.description');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Webhook}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeRail.nodes.webhookTriggerNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(WebhookTriggerNode);

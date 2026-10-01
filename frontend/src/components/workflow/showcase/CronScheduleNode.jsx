import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Clock } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

function CronScheduleNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const summary = data.cron
    ? data.cron
    : t('nodeRail.nodes.cronScheduleNode.description');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Clock}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeRail.nodes.cronScheduleNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(CronScheduleNode);

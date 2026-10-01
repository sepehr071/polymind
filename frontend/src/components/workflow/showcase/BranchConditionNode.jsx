import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function BranchConditionNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const summary = data.condition
    ? truncate(data.condition, 36)
    : t('nodeRail.nodes.branchConditionNode.description');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Activity}
      iconColor="bg-warning/10"
      iconTextColor="text-warning"
      title={data.label || t('nodeRail.nodes.branchConditionNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[
        { id: 'true', top: '35%', label: 'true' },
        { id: 'false', top: '70%', label: 'false' },
      ]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(BranchConditionNode);

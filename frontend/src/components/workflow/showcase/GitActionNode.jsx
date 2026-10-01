import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { GitBranch } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function GitActionNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const action = data.action || 'commit';
  const target = data.target ? truncate(data.target, 24) : t('nodeRail.nodes.gitActionNode.description');
  const summary = data.target ? `${action} · ${target}` : target;

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={GitBranch}
      iconColor="bg-warning/10"
      iconTextColor="text-warning"
      title={data.label || t('nodeRail.nodes.gitActionNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(GitActionNode);

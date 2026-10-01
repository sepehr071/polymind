import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Code2 } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function CodeRunnerNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const lang = data.language || 'js';
  const snippet = data.code ? truncate(data.code, 28) : t('nodeRail.nodes.codeRunnerNode.description');
  const summary = data.code ? `${lang} · ${snippet}` : snippet;

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Code2}
      iconColor="bg-success/10"
      iconTextColor="text-success"
      title={data.label || t('nodeRail.nodes.codeRunnerNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(CodeRunnerNode);

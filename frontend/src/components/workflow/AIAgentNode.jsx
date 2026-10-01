import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Bot } from 'lucide-react';
import { AI_AGENT_MODELS } from '../../constants/workflowModels';
import CompactNodeShell from './CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function AIAgentNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const modelEntry = AI_AGENT_MODELS.find((m) => m.id === data.model);
  const shortModelName = modelEntry?.name ?? t('nodeDefaults.noModel');
  const promptSnippet = truncate(data.systemPrompt, 30);
  const summary = promptSnippet
    ? `${shortModelName} · ${promptSnippet}`
    : shortModelName;

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={!!data.isRunning}
      hasError={!!data.hasError}
      errorMessage={data.errorMessage || null}
      icon={Bot}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeDefaults.copywriter')}
      statusDot={data.output ? 'ok' : null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[
        { id: 'input-0', top: '50%', label: t('nodeHandles.textInput') },
      ]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(AIAgentNode);

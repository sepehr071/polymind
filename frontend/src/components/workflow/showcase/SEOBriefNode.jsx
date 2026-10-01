import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSearch } from 'lucide-react';
import CompactNodeShell from '../CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function SEOBriefNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');
  const keywords = Array.isArray(data.keywords) ? data.keywords.join(', ') : data.keywords;
  const summary = keywords
    ? truncate(keywords, 36)
    : t('nodeRail.nodes.seoBriefNode.description');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={FileSearch}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeRail.nodes.seoBriefNode.label')}
      statusDot={null}
      summary={summary}
      lastRunAt={data.lastRunAt}
      leftHandles={[{ id: 'input-0', top: '50%', label: t('nodeHandles.textInput') }]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(SEOBriefNode);

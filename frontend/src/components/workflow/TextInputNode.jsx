import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Type } from 'lucide-react';
import CompactNodeShell from './CompactNodeShell';

const truncate = (str, max) =>
  str && str.length > max ? str.slice(0, max) + '…' : str || '';

function TextInputNode({ data, selected, isConnectable }) {
  const { t } = useTranslation('workflow');

  return (
    <CompactNodeShell
      selected={selected}
      isRunning={false}
      hasError={false}
      icon={Type}
      iconColor="bg-accent/10"
      iconTextColor="text-accent"
      title={data.label || t('nodeDefaults.briefContent')}
      statusDot={null}
      summary={data.text ? truncate(data.text, 40) : t('nodeDefaults.noText')}
      lastRunAt={data.lastRunAt}
      leftHandles={[]}
      rightHandles={[{ id: 'output', top: '50%', label: t('nodeHandles.textOut') }]}
      isConnectable={isConnectable}
    />
  );
}

export default memo(TextInputNode);

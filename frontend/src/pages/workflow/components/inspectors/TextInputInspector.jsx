import { useTranslation } from 'react-i18next';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { ConfigSection, Field } from './NodeConfigForm';
import OutputActionBar from '../OutputActionBar';

export default function TextInputInspector({ node, activeTab, updateNodeData, runHistory = [], workflowId = null }) {
  const { t } = useTranslation('workflow');
  const { data } = node;
  const nodeHistory = runHistory.filter((r) => r.nodeId === node.id);

  if (activeTab === 'output') {
    return (
      <div className="p-4 overflow-y-auto h-full space-y-4">
        {data.text ? (
          <>
            <pre className="text-sm text-foreground whitespace-pre-wrap font-sans">{data.text}</pre>
            <OutputActionBar
              outputType="text"
              text={data.text}
              knowledgeTitle={t('textInputInspector.knowledgeTitle')}
              workflowId={workflowId}
              nodeId={node.id}
            />
          </>
        ) : (
          <p className="text-sm text-foreground-secondary italic">{t('textInputInspector.noOutput')}</p>
        )}
      </div>
    );
  }

  if (activeTab === 'history') {
    return (
      <div className="p-4 space-y-3 overflow-y-auto h-full">
        {nodeHistory.length === 0 ? (
          <p className="text-sm text-foreground-secondary italic">{t('inspector.noRunsNode')}</p>
        ) : (
          nodeHistory.map((run, i) => (
            <div key={i} className="border border-border rounded-lg p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-foreground">{run.status ?? 'completed'}</span>
                <span className="text-foreground-tertiary">{run.createdAt ?? ''}</span>
              </div>
            </div>
          ))
        )}
      </div>
    );
  }

  // Configure tab
  return (
    <ConfigSection>
      <Field label={t('textInputInspector.fields.text')}>
        <Textarea
          rows={6}
          placeholder={data.placeholder || t('textInputInspector.placeholders.text')}
          value={data.text || ''}
          onChange={(e) => updateNodeData(node.id, { text: e.target.value })}
          className="text-sm resize-none"
        />
      </Field>

      <Field label={t('textInputInspector.fields.placeholder')}>
        <Input
          placeholder={t('textInputInspector.placeholders.placeholder')}
          value={data.placeholder || ''}
          onChange={(e) => updateNodeData(node.id, { placeholder: e.target.value })}
          className="text-sm"
        />
      </Field>
    </ConfigSection>
  );
}

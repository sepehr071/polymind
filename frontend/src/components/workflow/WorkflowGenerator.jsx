import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles, Loader2, Wand2, X } from 'lucide-react';
import { solidPanelSx } from '@/theme/glass';
import { RADII } from '@/theme/tokens';
import { cn } from '@/lib/utils';
import api from '../../services/api';

export default function WorkflowGenerator({ onGenerate, onClose }) {
  const { t } = useTranslation('workflow');
  const [description, setDescription] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState(null);

  const handleGenerate = async () => {
    if (!description.trim()) return;

    setIsGenerating(true);
    setError(null);

    try {
      const response = await api.post('/workflow-ai/generate', {
        description: description.trim()
      });

      if (response.data.success) {
        onGenerate(response.data.workflow);
        setDescription('');
      } else {
        setError(response.data.error || t('workflowGenerator.errorGenerate'));
      }
    } catch (err) {
      console.error('Workflow generation error:', err);
      setError(err.response?.data?.error || t('workflowGenerator.errorGenerate'));
    } finally {
      setIsGenerating(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && e.ctrlKey && !isGenerating) {
      handleGenerate();
    }
  };

  const examplePrompts = [
    "Product photo with studio lighting and white background",
    "Create 3 social media variations: Instagram square, Twitter banner, Stories vertical",
    "Style transfer: apply artistic style from one image to another",
    "Two-pass enhancement: first clean up, then add professional lighting"
  ];

  return (
    <div className={cn('rounded-xl p-4')} style={solidPanelSx({ radius: RADII.surface })}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Wand2 className="w-5 h-5 text-accent" />
          <h3 className="font-medium text-foreground">{t('workflowGenerator.title')}</h3>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 hover:bg-background-tertiary rounded"
          >
            <X className="w-4 h-4 text-foreground-secondary" />
          </button>
        )}
      </div>

      <p className="text-sm text-foreground-secondary mb-3">
        {t('workflowGenerator.description')}
      </p>

      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('workflowGenerator.placeholder')}
        className="w-full h-28 px-3 py-2 bg-background border border-border rounded-lg resize-none text-sm text-foreground placeholder:text-foreground-secondary/50 focus:outline-none focus:ring-2 focus:ring-accent/50"
        disabled={isGenerating}
        dir="ltr"
      />

      <div className="mt-2 mb-3">
        <p className="text-xs text-foreground-secondary mb-1">{t('workflowGenerator.tryAnExample')}</p>
        <div className="flex flex-wrap gap-1">
          {examplePrompts.map((prompt, idx) => (
            <button
              key={idx}
              onClick={() => setDescription(prompt)}
              disabled={isGenerating}
              className="text-xs px-2 py-1 bg-background hover:bg-accent/10 border border-border rounded text-foreground-secondary hover:text-accent transition-colors disabled:opacity-50"
            >
              {prompt.length > 40 ? prompt.slice(0, 40) + '...' : prompt}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-3 p-2 bg-error/10 border border-error/30 rounded text-error text-sm">
          {error}
        </div>
      )}

      <button
        onClick={handleGenerate}
        disabled={isGenerating || !description.trim()}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent text-accent-foreground rounded-lg hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
      >
        {isGenerating ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            {t('workflowGenerator.generating')}
          </>
        ) : (
          <>
            <Sparkles className="w-4 h-4" />
            {t('workflowGenerator.generate')}
          </>
        )}
      </button>

      <p className="text-xs text-foreground-secondary mt-2 text-center">
        {t('workflowGenerator.ctrlEnterHint')}
      </p>
    </div>
  );
}

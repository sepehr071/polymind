import { useTranslation } from 'react-i18next'
import { HelpCircle } from 'lucide-react'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'

/**
 * On-demand "Why am I seeing this?" disclosure for the DLP violation modal.
 *
 * Calibrated transparency: rather than hide the scanner (which makes people
 * assume the worst), we let users open a plain-language explanation on demand —
 * what we check for, that their message text is never stored, and who set it
 * up. Honesty reduces the "I'm being watched" feeling more than silence does.
 */
export default function DLPExplainer() {
  const { t } = useTranslation('dlp')

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 self-start text-[12px] text-foreground-secondary transition-colors hover:text-foreground"
        >
          <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" />
          {t('explainer.trigger')}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 text-start">
        <div className="space-y-2 text-[12px] leading-relaxed text-foreground-secondary">
          <p>{t('explainer.line1')}</p>
          <p>{t('explainer.line2')}</p>
          <p>{t('explainer.line3')}</p>
        </div>
      </PopoverContent>
    </Popover>
  )
}

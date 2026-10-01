import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Loader2 } from 'lucide-react'

const ACTIVE_STATUSES = new Set(['pending', 'running'])

export default function LiveBrowserFrame({ liveUrl, status }) {
  const { t } = useTranslation('automate')
  const [iframeLoaded, setIframeLoaded] = useState(false)

  if (!liveUrl) {
    if (ACTIVE_STATUSES.has(status)) {
      return (
        <Card className="p-4 flex items-center gap-3">
          <Loader2 className="h-4 w-4 animate-spin text-foreground-secondary shrink-0" />
          <span className="text-sm text-foreground-secondary">{t('browser.spinningUp')}</span>
        </Card>
      )
    }
    return null
  }

  return (
    <Card className="overflow-hidden relative w-full h-[55vh] sm:h-[65vh] lg:h-[calc(100vh-260px)] lg:min-h-[540px]">
      {!iframeLoaded && (
        <div className="absolute inset-0 z-10 p-4 flex flex-col gap-3">
          <Skeleton className="w-full h-6 rounded" />
          <Skeleton className="w-full flex-1 rounded" />
        </div>
      )}
      {/* allow-same-origin required so browser-use stream UI can render */}
      <iframe
        src={liveUrl}
        sandbox="allow-scripts allow-same-origin"
        className="w-full h-full border-0 rounded-xl"
        onLoad={() => setIframeLoaded(true)}
        title={t('browser.iframeTitle')}
      />
    </Card>
  )
}

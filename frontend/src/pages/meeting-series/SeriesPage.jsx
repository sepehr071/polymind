import { useTranslation } from 'react-i18next'
import { Layers } from 'lucide-react'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import SeriesManager from './components/SeriesManager'

export default function SeriesPage() {
  const { t } = useTranslation('meetings_series')
  return (
    <PageShell width="standard">
      <PageHeader
        title={t('page.title')}
        subtitle={t('page.subtitle')}
        icon={Layers}
        tone="amber"
      />
      <SeriesManager />
    </PageShell>
  )
}

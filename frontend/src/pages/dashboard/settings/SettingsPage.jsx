import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { Settings } from 'lucide-react'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { SECTIONS, DEFAULT_SECTION } from './sections/registry'
import SettingsBreadcrumb from '@/components/settings/SettingsBreadcrumb'
import SettingsNav from '@/components/settings/SettingsNav'

export default function SettingsPage() {
  const { t } = useTranslation('settings')
  const location = useLocation()
  const navigate = useNavigate()

  const hashId = location.hash?.replace('#', '')
  const active =
    SECTIONS.find((s) => s.id === hashId) ||
    SECTIONS.find((s) => s.id === DEFAULT_SECTION) ||
    SECTIONS[0]
  const ActiveComponent = active.Component

  const setActive = (id) => {
    navigate({ hash: id }, { replace: true })
  }

  return (
    <PageShell width="form">
      <PageHeader
        icon={Settings}
        tone="neutral"
        title={t('title')}
        subtitle={t('subtitle')}
      >
        <div className="mt-3">
          <SettingsBreadcrumb level="personal" />
        </div>
      </PageHeader>

      {/* Canonical underline tabs in-flow above the section body — no side
          column, no Card frame; the active section's form renders directly in
          the PageShell flow (P2-04). */}
      <SettingsNav active={active.id} onSelect={setActive} />

      <main className="min-w-0">
        <ActiveComponent />
      </main>
    </PageShell>
  )
}

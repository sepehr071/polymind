import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AudioWaveform, Sparkles, ArrowRight } from 'lucide-react'
import Icon3D from '../../components/ui/icon-3d'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Skeleton } from '../../components/ui/skeleton'
import { IconTile } from '../../components/ui/icon-tile'
import { useAuth } from '../../context/AuthContext'
import { hasFeature } from '../../utils/featureFlags'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import { hubIconFor } from '@/constants/hubIcons'

/**
 * Assistants hub — landing page listing ready-made assistants as cards.
 *
 * These are curated, purpose-built assistants (e.g. Meeting Assistant) that
 * link straight to their feature route. This is distinct from the "Custom
 * Assistants" page (`/configs`), where users build their own personas — the
 * footer cross-links there so the two surfaces don't read as duplicates.
 */
// Catalog of curated assistants. Each entry is gated by its backing feature
// flag — when the flag is OFF the card is hidden (the route/feature itself is
// unreachable). Adding a new assistant = append here + tag its `feature`.
const ASSISTANT_CATALOG = [
  {
    id: 'meetings',
    feature: 'meetings',
    icon: AudioWaveform,
    titleKey: 'meetingAssistant.title',
    descriptionKey: 'meetingAssistant.description',
    to: '/meetings',
    ctaKey: 'meetingAssistant.cta',
  },
]

export default function AssistantsHubPage() {
  const { t } = useTranslation(['assistants', 'common'])
  const { user, isLoading } = useAuth()

  const assistants = useMemo(
    () => ASSISTANT_CATALOG.filter((a) => !a.feature || hasFeature(user, a.feature)),
    [user]
  )

  // Sparse catalog: skeleton count tracks the real item count so the loading
  // state doesn't promise more cards than will render (only read while loading).
  const skeletonCount = Math.max(ASSISTANT_CATALOG.length, 1)

  return (
    <PageShell width="standard">
      <PageHeader
        title={t('pageTitle')}
        subtitle={t('pageHint')}
        icon={AudioWaveform}
        backTo="/dashboard"
        backLabel={t('common:actions.back')}
      />

      {isLoading ? (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: skeletonCount }, (_, i) => (
            <Card key={i} className="flex flex-col">
              <CardHeader>
                <Skeleton className="h-9 w-9 rounded-xl mb-2" />
                <Skeleton className="h-5 w-2/3 mb-2" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
              </CardHeader>
              <CardContent className="mt-auto">
                <Skeleton className="h-9 w-full rounded-md" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : assistants.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Icon3D src="/icons/3d/bot.png" size={64} alt="" className="mb-3" />
            <h2 className="text-lg font-medium text-foreground mb-1">
              {t('empty.title')}
            </h2>
            <p className="text-sm text-foreground-secondary">
              {t('empty.description')}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {assistants.map((a) => {
            const Icon = a.icon
            const art = hubIconFor(a.to)
            return (
              <Card
                key={a.id}
                hover
                className="flex flex-col"
              >
                <CardHeader>
                  {art?.src ? (
                    <img src={art.src} alt="" className="mb-2 h-11 w-11 rounded-2xl object-cover" />
                  ) : (
                    <IconTile icon={Icon} tone="amber" size="lg" className="mb-2" />
                  )}
                  <CardTitle>{t(a.titleKey)}</CardTitle>
                  <CardDescription>{t(a.descriptionKey)}</CardDescription>
                </CardHeader>
                <CardContent className="mt-auto">
                  <Button asChild className="w-full">
                    <Link to={a.to}>{t(a.ctaKey)}</Link>
                  </Button>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {!isLoading && assistants.length > 0 && (
        <p className="text-center text-xs text-foreground-tertiary">
          {t('moreSoon')}
        </p>
      )}

      <Card>
        <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <IconTile icon={Sparkles} tone="emerald" size="lg" />
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                {t('customCrossLink.title')}
              </h2>
              <p className="mt-1 text-sm text-foreground-secondary">
                {t('customCrossLink.description')}
              </p>
            </div>
          </div>
          <Button asChild variant="outline" className="shrink-0">
            <Link to="/configs" className="gap-1.5">
              {t('customCrossLink.cta')}
              <ArrowRight className="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
            </Link>
          </Button>
        </CardContent>
      </Card>
    </PageShell>
  )
}

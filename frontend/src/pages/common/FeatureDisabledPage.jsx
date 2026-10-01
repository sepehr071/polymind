import { Link } from 'react-router-dom'
import { Lock, ArrowLeft } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

// Friendly stand-in when a platform feature flag is off for the current company.
// Rendered INSIDE FeatureGate (so it stays within MainLayout — nav persists)
// instead of a silent <Navigate to="/chat">.
export default function FeatureDisabledPage() {
  const { t } = useTranslation('errors')

  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <Card className="max-w-md w-full">
        <CardHeader className="flex flex-col items-center gap-3 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-warning/10 text-warning">
            <Lock className="h-6 w-6" />
          </span>
          <CardTitle>{t('featureDisabled.title')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-5 text-center">
          <p className="text-sm text-foreground-secondary">
            {t('featureDisabled.message')}
          </p>
          <Button asChild variant="secondary">
            <Link to="/chat">
              <ArrowLeft className="h-4 w-4" />
              {t('featureDisabled.goHome')}
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

import { Link } from 'react-router-dom'
import { Compass, ArrowLeft } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

// Real catch-all for unknown paths — replaces the blind <Navigate to="/chat">
// so users get a clear 404 (and the URL they typed is preserved) instead of a
// silent bounce that hides typos / dead links.
export default function NotFoundPage() {
  const { t } = useTranslation('errors')

  return (
    <div className="flex min-h-screen flex-1 items-center justify-center bg-background p-8">
      <Card className="max-w-md w-full">
        <CardHeader className="flex flex-col items-center gap-3 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-background-tertiary text-foreground-secondary">
            <Compass className="h-6 w-6" />
          </span>
          <span className="text-4xl font-bold text-foreground">404</span>
          <CardTitle>{t('notFound.title')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-5 text-center">
          <p className="text-sm text-foreground-secondary">
            {t('notFound.message')}
          </p>
          <Button asChild variant="secondary">
            <Link to="/chat">
              <ArrowLeft className="h-4 w-4" />
              {t('notFound.goHome')}
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

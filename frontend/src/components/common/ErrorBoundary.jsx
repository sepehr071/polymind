import { Component } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

// Class component cannot use hooks — translate via i18n directly
import i18n from '@/i18n'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  reset() {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      const t = (key) => i18n.t(key, { ns: 'layout' })
      return (
        <div className="flex flex-1 items-center justify-center p-8">
          <Card className="max-w-md w-full">
            <CardHeader>
              <CardTitle className="text-error">{t('errorBoundary.title')}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <p className="text-sm text-foreground-secondary">
                {t('errorBoundary.message')}
              </p>
              <Button onClick={() => this.reset()} variant="secondary" className="self-start">
                {t('errorBoundary.retry')}
              </Button>
            </CardContent>
          </Card>
        </div>
      )
    }

    return this.props.children
  }
}

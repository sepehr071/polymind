import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Box from '@mui/material/Box'
import { Loader2, KeyRound, ShieldAlert, AlertCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuth } from '../../context/AuthContext'
import { Button } from '../../components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import { cn } from '@/lib/utils'
import { useTranslation } from 'react-i18next'

// Module-level so React StrictMode remount doesn't fire PKCE twice.
let autoSsoStarted = false

export default function LoginPage() {
  const { loginKeycloak } = useAuth()
  const { t } = useTranslation('auth')

  // KC enablement: lazy-init, undefined while checking, true/false once known.
  const [kcEnabled, setKcEnabled] = useState(undefined)
  const [ssoLoading, setSsoLoading] = useState(false)
  // When enablement resolves false, distinguish a transient fetch failure
  // ('network') from a genuine "not configured" (null) so we can offer Retry.
  const [configError, setConfigError] = useState(null)
  const [retrying, setRetrying] = useState(false)

  // Lifted so the Retry button can re-run the exact same enablement check.
  const checkEnablement = useCallback(async () => {
    const keycloakClient = (await import('../../services/keycloakClient')).default
    await keycloakClient.init()
    setKcEnabled(keycloakClient.isEnabled())
    setConfigError(keycloakClient.getConfigError())
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const keycloakClient = (await import('../../services/keycloakClient')).default
        await keycloakClient.init()
        if (cancelled) return
        setKcEnabled(keycloakClient.isEnabled())
        setConfigError(keycloakClient.getConfigError())
      } catch {
        if (cancelled) return
        setKcEnabled(false)
        setConfigError('network')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Surface a one-time "session expired" toast when AuthContext (401/403 or
  // the auth:cleared path) bounced the user here. Guard against StrictMode's
  // double-mount so it fires exactly once.
  const expiryToasted = useRef(false)
  useEffect(() => {
    if (expiryToasted.current) return
    if (sessionStorage.getItem('session_expired')) {
      expiryToasted.current = true
      sessionStorage.removeItem('session_expired')
      toast.error(t('toast.sessionExpired'))
    }
  }, [t])

  const handleRetryConfig = async () => {
    setRetrying(true)
    try {
      const keycloakClient = (await import('../../services/keycloakClient')).default
      await keycloakClient.retryConfig()
      await checkEnablement()
    } catch {
      setKcEnabled(false)
      setConfigError('network')
    } finally {
      setRetrying(false)
    }
  }

  const handleSso = async () => {
    setSsoLoading(true)
    try {
      await loginKeycloak()
      // loginKeycloak triggers a full navigation; if we end up here, it returned without redirect.
    } catch {
      // toast surfaced inside loginKeycloak
    } finally {
      setSsoLoading(false)
    }
  }

  // Public login is IdP-only: bounce straight to the IdP so logout lands on
  // the Keycloak form, not this card. Button stays as fallback if redirect throws.
  useEffect(() => {
    if (kcEnabled !== true) return
    if (autoSsoStarted) return
    autoSsoStarted = true
    handleSso()
  }, [kcEnabled]) // eslint-disable-line react-hooks/exhaustive-deps — once per JS session

  return (
    // Mount-reveal animations are CSS keyframes (was framer-motion) so this
    // eager auth route keeps `motion/react` out of the entry chunk. The global
    // reduce-motion rule in index.css freezes them automatically.
    <div className="animate-slide-up">
      <Box
        component="div"
        className={cn('relative isolate overflow-hidden rounded-xl p-7 sm:p-8')}
        sx={solidPanelSx({ radius: RADII.surface })}
      >
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-foreground animate-slide-up">
          {t('login.title')}
        </h2>
        <p
          className="text-foreground-secondary mt-2 animate-fade-in"
          style={{ animationDelay: '0.1s', animationFillMode: 'backwards' }}
        >
          {t('login.subtitle')}
        </p>
      </div>

      {/* Skeleton while KC enablement is unknown */}
      {kcEnabled === undefined && (
        <div className="space-y-3" aria-hidden="true">
          <div className="h-11 w-full rounded-md bg-background-elevated animate-pulse" />
          <Skeleton className="h-4 w-32 mx-auto" />
        </div>
      )}

      {/* SSO primary CTA */}
      {kcEnabled === true && (
        <div className="animate-slide-up" style={{ animationDelay: '0.15s', animationFillMode: 'backwards' }}>
          <Button
            type="button"
            onClick={handleSso}
            disabled={ssoLoading}
            className="w-full h-11 text-base shadow-lg shadow-accent/25"
          >
            {ssoLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin me-2" />
                {t('sso.redirecting')}
              </>
            ) : (
              <>
                <KeyRound className="h-4 w-4 me-2" />
                {t('sso.signInWithKeycloak')}
              </>
            )}
          </Button>
        </div>
      )}

      {/* Couldn't reach the sign-in service — transient, offer a Retry. */}
      {kcEnabled === false && configError === 'network' && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-border bg-background-elevated p-6 text-center animate-fade-in"
          style={{ animationDelay: '0.15s', animationFillMode: 'backwards' }}
        >
          <AlertCircle className="h-8 w-8 text-error" />
          <p className="text-sm text-foreground-secondary">
            {t('sso.fetchError')}
          </p>
          <Button
            type="button"
            onClick={handleRetryConfig}
            disabled={retrying}
            className="w-full h-11 text-base"
          >
            {retrying ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin me-2" />
                {t('sso.tryAgain')}
              </>
            ) : (
              t('sso.tryAgain')
            )}
          </Button>
        </div>
      )}

      {/* SSO genuinely not configured — no form fallback (operator login is unlinked) */}
      {kcEnabled === false && configError === null && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-border bg-background-elevated p-6 text-center animate-fade-in"
          style={{ animationDelay: '0.15s', animationFillMode: 'backwards' }}
        >
          <ShieldAlert className="h-8 w-8 text-warning" />
          <p className="text-sm text-foreground-secondary">
            {t('sso.notConfigured')}
          </p>
          {/* Discreet escape hatch: when SSO is absent, platform operators /
              break-glass admins still need a way in via /login/operator. */}
          <Link
            to="/login/operator"
            className="text-xs text-fg-3 hover:text-foreground hover:underline"
          >
            {t('operator.link')}
          </Link>
        </div>
      )}
      </Box>
    </div>
  )
}

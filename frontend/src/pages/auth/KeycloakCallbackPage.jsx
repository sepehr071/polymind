import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, AlertCircle } from 'lucide-react'
import toast from 'react-hot-toast'

import keycloakClient from '@/services/keycloakClient'
import { authService } from '@/services/authService'
import { Button } from '@/components/ui/button'
import { useLanguage } from '@/context/LanguageContext'

export default function KeycloakCallbackPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { t } = useTranslation('auth')
  const { setLanguage } = useLanguage()
  const ran = useRef(false)
  const [error, setError] = useState(null)
  const [retrying, setRetrying] = useState(false)

  // Re-initiate the PKCE round-trip from scratch. The previous OIDC `code`
  // and sessionStorage state are already consumed, so a clean redirect is the
  // only way out — a bare "Back to login" would just loop.
  const handleRetry = async () => {
    setRetrying(true)
    try {
      await keycloakClient.init()
      // Navigates away — never resolves on success.
      await keycloakClient.loginRedirect()
    } catch (e) {
      console.error('Keycloak retry failed', e)
      setRetrying(false)
      navigate('/login', { replace: true })
    }
  }

  useEffect(() => {
    // StrictMode double-mounts effects in dev; the OIDC `code` is single-use
    // so re-running handleCallback would hit invalid_grant on the second pass.
    if (ran.current) return
    ran.current = true

    ;(async () => {
      try {
        await keycloakClient.init()
        const tokens = await keycloakClient.handleCallback()

        // httpOnly-cookie auth: do NOT persist KC access/refresh tokens. We
        // hand the KC access token to /keycloak/sync (below), which verifies it
        // and sets OUR app's httpOnly auth cookies. Only the non-sensitive
        // auth_kind + the federated-logout id_token hint stay in localStorage.
        if (tokens.id_token) {
          localStorage.setItem('kc_id_token', tokens.id_token)
        }
        localStorage.setItem('auth_kind', 'keycloak')

        const data = await authService.syncKeycloak(
          tokens.access_token,
          tokens.refresh_token,
          tokens.id_token,
        )

        // Backend set our auth cookies as a side effect of the sync; mark
        // presence so the /auth/me query is enabled on the next paint.
        localStorage.setItem('auth_present', '1')

        queryClient.setQueryData(['authMe'], {
          ...data.user,
          features: data.features,
        })

        const locale = data.user?.settings?.locale
        if (locale === 'fa' || locale === 'en') {
          setLanguage(locale)
        }

        toast.success(t('signedIn'))

        // If the user arrived here from an invite link, resume that flow
        // instead of dropping them into an empty /chat. The token is stashed
        // by AcceptInvitePage before it bounces an unauthenticated visitor to
        // /login (mirrors the /invite/:token route).
        const pendingInvite = localStorage.getItem('pending_invite_token')
        if (pendingInvite) {
          localStorage.removeItem('pending_invite_token')
          navigate(`/invite/${pendingInvite}`, { replace: true })
          return
        }

        // Restore the deep link the user was headed to before SSO. ProtectedRoute
        // stashes it in sessionStorage because the KC redirect URI is a fixed
        // /login/callback and drops the original ?redirect= query. Same-origin
        // guard mirrors PublicRoute (no protocol-relative // open redirects).
        const stashed = sessionStorage.getItem('auth_redirect')
        if (stashed) {
          sessionStorage.removeItem('auth_redirect')
          if (stashed.startsWith('/') && !stashed.startsWith('//')) {
            navigate(stashed, { replace: true })
            return
          }
        }

        navigate('/dashboard', { replace: true })
      } catch (e) {
        console.error('Keycloak callback failed', e)
        const serverMsg = e?.response?.data?.error
        const message = typeof serverMsg === 'string' && serverMsg
          ? serverMsg
          : t('sso.failed')
        setError(message)
        toast.error(message)
        // Stay on this page — the OIDC state in sessionStorage is already
        // consumed, so bouncing the user straight to /login would just send
        // them back through a fresh round-trip with no explanation. The
        // "Try again" button below re-initiates SSO cleanly.
      }
    })()
  }, [navigate, queryClient, t, setLanguage])

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-8">
      {error ? (
        <div className="flex items-center gap-2 text-error text-sm">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-fg-3 text-sm">
          <Loader2 className="h-5 w-5 animate-spin shrink-0" />
          <span>{t('ssoRedirecting')}</span>
        </div>
      )}
      {error && (
        <div className="flex flex-col items-center gap-2">
          <Button onClick={handleRetry} disabled={retrying}>
            {retrying ? t('sso.redirecting') : t('sso.tryAgain')}
          </Button>
          <Button
            variant="link"
            onClick={() => navigate('/login', { replace: true })}
          >
            {t('sso.backToLogin')}
          </Button>
        </div>
      )}
    </div>
  )
}

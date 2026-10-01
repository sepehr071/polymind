import { useAuth } from '@/context/AuthContext'

/**
 * Landing CTA destination. The landing is now reachable while logged in, so
 * every sign-in CTA flips to an "enter app" link for authed users. Guests keep
 * the /login target.
 *
 * Returns { isAuthed, href } — copy lives in the caller (i18n key choice).
 */
export function useAppEntry() {
  const { user } = useAuth()
  if (!user) return { isAuthed: false, href: '/login' }
  return {
    isAuthed: true,
    href: '/dashboard',
  }
}

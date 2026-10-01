/**
 * Money visibility + Polymind Credits formatting (profit redesign 2026-06-29).
 *
 * Three viewer tiers — NEVER leak a $ figure to a normal user:
 *   - admin (CEO)         → sees true cost + price + margin
 *   - owner of a TEAM ws  → sees PRICE only (marked-up USD)
 *   - everyone else       → Polymind Credits + token counts only
 *
 * CRITICAL: every user owns a PERSONAL workspace as 'owner', so an
 * owns-ANY-workspace check leaks price to all users. Gate on `type === 'team'`.
 * This file is the single source of truth for that predicate — replaces the
 * buggy inline `canSeeCost` that lived in UsageTab / UsageSnapshot.
 *
 * Pure (no React / no i18n import) so it tree-shakes into charts + tests, the
 * same discipline as persianLocale.js.
 */
import { fmtNumber } from './persianLocale'

/** True iff the user owns at least one TEAM (non-personal) workspace. */
export function ownsTeamWorkspace(workspaces) {
  return (Array.isArray(workspaces) ? workspaces : []).some(
    (w) => w?.type === 'team' && w?.member_role === 'owner',
  )
}

/** Department-owner / CEO tier — may see PRICE ($). */
export function canSeePrice(user, workspaces) {
  return user?.role === 'admin' || ownsTeamWorkspace(workspaces)
}

/** Price visibility for the CURRENT org: admin, or owner of that team org. */
export function canSeePriceInOrg(user, workspaces, workspaceId) {
  if (user?.role === 'admin') return true
  if (!workspaceId) return false
  return (Array.isArray(workspaces) ? workspaces : []).some(
    (w) => w?._id === workspaceId && w?.type === 'team' && w?.member_role === 'owner',
  )
}

/** CEO tier ONLY — may see true upstream cost + margin. */
export function canSeeMargin(user) {
  return user?.role === 'admin'
}

/**
 * Short Polymind-credit count for chart axes / on-bar labels (1.2K / 3.4M),
 * digit-script aware via fmtNumber. Mirrors fmtTokensShort.
 *  - null / NaN → '' (so a gated value renders blank, never "0")
 */
export function fmtCreditsShort(value) {
  if (value == null) return ''
  const n = Number(value)
  if (Number.isNaN(n)) return ''
  if (n >= 1_000_000) return `${fmtNumber(n / 1_000_000, { decimals: 1 })}M`
  if (n >= 1_000) return `${fmtNumber(n / 1_000, { decimals: 1 })}K`
  return fmtNumber(n, { decimals: 0 })
}

/**
 * Full localized credit label, e.g. "1,240 credits" / "۱٬۲۴۰ اعتبار".
 * Needs a `t` bound to the `billing` namespace (charts can't call hooks, so the
 * caller threads it). Returns '' for null/NaN.
 */
export function fmtCreditsLabel(value, t) {
  if (value == null) return ''
  const n = Number(value)
  if (Number.isNaN(n)) return ''
  return t('credits.suffix', { ns: 'billing', value: fmtNumber(n, { decimals: 0 }) })
}

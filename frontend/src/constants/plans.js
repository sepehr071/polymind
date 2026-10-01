/**
 * Plan tiers (profit redesign 2026-06-29) — single source of truth for the
 * subscription tier dropdown + its labels + the default monthly allowance each
 * tier ships with.
 *
 * `allowanceUsd` is the preset monthly spend allowance for the tier (the $ a
 * department owner's plan grants per month). `enterprise` is bespoke, so its
 * allowance is `null` (= negotiated / unlimited, no preset).
 *
 * The backend `plan_tier` column accepts these four keys plus the legacy
 * `free | team` values — `BillingTab.planTierLabelKey` maps the legacy keys for
 * display, but new selections only ever write a key from this list.
 *
 * i18n: `labelKey` resolves under the workspace/project billing namespace
 * (`projects` ns, `workspaceSettings.billing.*`). Pure data, no React/i18n
 * import, so it tree-shakes into both the dialog and any tests.
 */
export const PLAN_TIERS = [
  {
    key: 'starter',
    labelKey: 'workspaceSettings.billing.planDialog.tierStarter',
    allowanceUsd: 50,
  },
  {
    key: 'growth',
    labelKey: 'workspaceSettings.billing.planDialog.tierGrowth',
    allowanceUsd: 250,
  },
  {
    key: 'scale',
    labelKey: 'workspaceSettings.billing.planDialog.tierScale',
    allowanceUsd: 1000,
  },
  {
    key: 'enterprise',
    labelKey: 'workspaceSettings.billing.planDialog.tierEnterprise',
    allowanceUsd: null,
  },
]

/** Lookup a tier definition by key (case-insensitive). */
export function getPlanTier(key) {
  if (!key) return undefined
  const k = String(key).toLowerCase()
  return PLAN_TIERS.find((tier) => tier.key === k)
}

export default PLAN_TIERS

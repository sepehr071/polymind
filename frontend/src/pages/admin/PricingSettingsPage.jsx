import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Loader2, ArrowRight } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { adminService } from '@/services/adminService'
import { fmtCurrency, fmtNumber } from '@/utils/persianLocale'
import { fmtDate } from '@/utils/dateLocale'
import PageShell from '@/components/layout/PageShell'

function formatWhen(iso) {
  if (!iso) return null
  try {
    return fmtDate(new Date(iso), 'PPpp')
  } catch {
    return iso
  }
}

/** Backend stores markup as a FRACTION (0.30 = 30%); this form shows PERCENT.
 *  Convert at the network boundary so the operator types/reads "30", not "0.3".
 *  Rounded to 4dp to kill float noise (0.3 * 100 = 30.000000000000004). */
const toPct = (frac) => (frac == null ? null : Math.round(Number(frac) * 1e6) / 1e4)

/** Backend ceiling: markup_pct fraction max 5.0 == 500%. */
const MARKUP_PCT_MAX = 500

/** Parse a string field to a finite, non-negative number — or null if invalid. */
function parseNonNeg(value) {
  if (value === '' || value == null) return null
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/**
 * /admin/pricing — the two pricing knobs that drive billing: the markup % applied
 * over upstream OpenRouter cost (what determines margin on the profit dashboard)
 * and the credit conversion rate (how many credits one USD buys). Both load from
 * and save to `GET|PUT /admin/billing/config`.
 *
 * A linear settings form (PageShell width="form"): two labelled numeric inputs,
 * each with a live worked example so the operator sees the effect before saving
 * ("$1.00 → $1.30 price", "$1 = 100 credits"). Client-validates finite +
 * non-negative before enabling save; the backend is the bound authority (400 on
 * out-of-range) and its error surfaces in the toast.
 */
export default function PricingSettingsPage() {
  const { t } = useTranslation('admin')
  const queryClient = useQueryClient()

  const [markup, setMarkup] = useState('')
  const [credits, setCredits] = useState('')
  // Last-saved values, to detect a dirty form + revert on a failed save.
  const [saved, setSaved] = useState({ markup_pct: null, credits_per_usd: null })
  const [meta, setMeta] = useState({ updated_at: null, updated_by: null })

  const query = useQuery({
    queryKey: ['admin-pricing'],
    queryFn: () => adminService.getPricing(),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  })

  // Hydrate the form from the loaded config once it lands (and on any refetch
  // that isn't mid-edit — keyed on the query data identity).
  useEffect(() => {
    const d = query.data
    if (!d) return
    setMarkup(d.markup_pct != null ? String(toPct(d.markup_pct)) : '')
    setCredits(d.credits_per_usd != null ? String(d.credits_per_usd) : '')
    setSaved({
      markup_pct: d.markup_pct != null ? toPct(d.markup_pct) : null,
      credits_per_usd: d.credits_per_usd ?? null,
    })
    setMeta({ updated_at: d.updated_at || null, updated_by: d.updated_by || null })
  }, [query.data])

  const mutation = useMutation({
    mutationFn: (body) => adminService.updatePricing(body),
    onSuccess: (data) => {
      // Optimistic-toast model (FeatureFlagsPage): trust the server echo for the
      // canonical values + meta, then confirm.
      const next = {
        markup_pct: data?.markup_pct != null ? toPct(data.markup_pct) : null,
        credits_per_usd: data?.credits_per_usd ?? null,
      }
      setSaved(next)
      if (next.markup_pct != null) setMarkup(String(next.markup_pct))
      if (next.credits_per_usd != null) setCredits(String(next.credits_per_usd))
      setMeta({ updated_at: data?.updated_at || null, updated_by: data?.updated_by || null })
      queryClient.setQueryData(['admin-pricing'], (prev) => ({ ...(prev || {}), ...data }))
      toast.success(t('pricing.saved'))
    },
    onError: (err) => {
      toast.error(err?.response?.data?.error || t('pricing.saveError'))
    },
  })

  const markupNum = parseNonNeg(markup)
  const creditsNum = parseNonNeg(credits)
  // markupNum is a PERCENT here; the backend ceiling is 500% (fraction 5.0).
  const markupInvalid =
    markup !== '' && (markupNum == null || markupNum > MARKUP_PCT_MAX)
  // Zero credits-per-USD is nonsensical (division by zero downstream); require > 0.
  const creditsInvalid = credits !== '' && (creditsNum == null || creditsNum <= 0)

  const valid =
    markupNum != null &&
    markupNum <= MARKUP_PCT_MAX &&
    creditsNum != null &&
    creditsNum > 0
  const dirty =
    markupNum !== saved.markup_pct || creditsNum !== saved.credits_per_usd

  // Live previews. Markup: $1.00 base → priced. Credits: $1 → N credits.
  const pricedExample = useMemo(() => {
    if (markupNum == null) return null
    return fmtCurrency(1 * (1 + markupNum / 100))
  }, [markupNum])

  const creditsExample = useMemo(() => {
    if (creditsNum == null) return null
    return fmtNumber(creditsNum)
  }, [creditsNum])

  const whoLabel = (() => {
    const u = meta.updated_by
    if (!u) return null
    return u.display_name || u.email || u._id || null
  })()

  const onSubmit = (e) => {
    e.preventDefault()
    if (!valid || !dirty || mutation.isPending) return
    // Convert PERCENT (form) → FRACTION (backend): 30 → 0.30.
    mutation.mutate({ markup_pct: markupNum / 100, credits_per_usd: creditsNum })
  }

  return (
    <PageShell width="form">
      <p className="text-center text-xs text-foreground-tertiary">
        {meta.updated_at && whoLabel
          ? t('pricing.lastUpdated', { when: formatWhen(meta.updated_at), who: whoLabel })
          : t('pricing.neverUpdated')}
      </p>

      {query.isLoading && !query.data ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-accent" />
        </div>
      ) : query.error && !query.data ? (
        <Card>
          <CardContent className="pt-6">
            <p className="text-error">
              {query.error?.response?.data?.error || t('pricing.loadError')}
            </p>
          </CardContent>
        </Card>
      ) : (
        <form onSubmit={onSubmit} noValidate>
          <Card>
            <CardContent className="space-y-7 p-6">
              {/* Markup % */}
              <div className="space-y-2">
                <Label htmlFor="pricing-markup">{t('pricing.markupLabel')}</Label>
                <div className="relative max-w-[220px]">
                  <Input
                    id="pricing-markup"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.1"
                    dir="ltr"
                    value={markup}
                    onChange={(e) => setMarkup(e.target.value)}
                    aria-invalid={markupInvalid || undefined}
                    aria-describedby="pricing-markup-hint pricing-markup-preview"
                    className="pe-9 text-end tabular-nums"
                  />
                  <span
                    className="pointer-events-none absolute inset-y-0 end-3 flex items-center text-sm text-foreground-tertiary"
                    aria-hidden
                  >
                    %
                  </span>
                </div>
                <p id="pricing-markup-hint" className="text-xs text-foreground-secondary">
                  {t('pricing.markupHint')}
                </p>
                {/* Live preview: $1.00 → priced */}
                <div
                  id="pricing-markup-preview"
                  className="inline-flex items-center gap-2 rounded-xl border border-line bg-bg-2/50 px-3 py-2 text-sm"
                >
                  <span className="tabular-nums text-foreground-secondary" dir="ltr">
                    {fmtCurrency(1)}
                  </span>
                  <ArrowRight className="h-3.5 w-3.5 flex-shrink-0 text-foreground-tertiary rtl:rotate-180" aria-hidden />
                  <span className="font-semibold tabular-nums text-foreground" dir="ltr">
                    {pricedExample ?? '—'}
                  </span>
                  <span className="text-xs text-foreground-tertiary">
                    {t('pricing.previewPrice')}
                  </span>
                </div>
              </div>

              <div className="h-px w-full bg-line" role="presentation" />

              {/* Credits per USD */}
              <div className="space-y-2">
                <Label htmlFor="pricing-credits">{t('pricing.creditsLabel')}</Label>
                <Input
                  id="pricing-credits"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="1"
                  dir="ltr"
                  value={credits}
                  onChange={(e) => setCredits(e.target.value)}
                  aria-invalid={creditsInvalid || undefined}
                  aria-describedby="pricing-credits-hint pricing-credits-preview"
                  className="max-w-[220px] text-end tabular-nums"
                />
                <p id="pricing-credits-hint" className="text-xs text-foreground-secondary">
                  {t('pricing.creditsHint')}
                </p>
                {/* Live preview: $1 = N credits */}
                <div
                  id="pricing-credits-preview"
                  className="inline-flex items-center gap-2 rounded-xl border border-line bg-bg-2/50 px-3 py-2 text-sm"
                >
                  <span className="tabular-nums text-foreground-secondary" dir="ltr">
                    {fmtCurrency(1)}
                  </span>
                  <span className="text-foreground-tertiary">=</span>
                  <span className="font-semibold tabular-nums text-foreground">
                    {creditsExample ?? '—'}
                  </span>
                  <span className="text-xs text-foreground-tertiary">
                    {t('pricing.previewCredits')}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="mt-4 flex items-center justify-end gap-3">
            {dirty && valid && !mutation.isPending && (
              <span className="text-xs text-foreground-tertiary">{t('pricing.unsaved')}</span>
            )}
            <Button type="submit" disabled={!valid || !dirty || mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('pricing.save')}
            </Button>
          </div>
        </form>
      )}
    </PageShell>
  )
}

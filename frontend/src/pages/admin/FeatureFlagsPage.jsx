import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Loader2 } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Card, CardContent } from '@/components/ui/card'
import { adminService } from '@/services/adminService'
import { FEATURE_FLAG_KEYS } from '@/utils/featureFlags'
import { fmtDate } from '@/utils/dateLocale'
import { cn } from '@/lib/utils'
import PageShell from '@/components/layout/PageShell'

function formatWhen(iso) {
  if (!iso) return null
  try {
    return fmtDate(new Date(iso), 'PPpp')
  } catch {
    return iso
  }
}

export default function FeatureFlagsPage() {
  const { t } = useTranslation('admin')
  const [features, setFeatures] = useState({})
  const [meta, setMeta] = useState({ updated_at: null, updated_by: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState({}) // { [feature]: boolean }

  useEffect(() => {
    let alive = true
    setLoading(true)
    adminService
      .getFeatures()
      .then((data) => {
        if (!alive) return
        setFeatures(data?.features || {})
        setMeta({
          updated_at: data?.updated_at || null,
          updated_by: data?.updated_by || null,
        })
        setError(null)
      })
      .catch((err) => {
        if (!alive) return
        setError(err?.response?.data?.error || t('features.loadError'))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [t])

  const handleToggle = useCallback(
    async (flag, next) => {
      // Optimistic UI: flip local state, revert on error.
      const previous = features[flag] ?? false
      setFeatures((prev) => ({ ...prev, [flag]: next }))
      setPending((prev) => ({ ...prev, [flag]: true }))
      const name = t(`features.flag.${flag}.name`, flag)
      try {
        const data = await adminService.updateFeatures({ feature: flag, enabled: next })
        if (data?.features) setFeatures(data.features)
        if (data?.updated_at || data?.updated_by) {
          setMeta({
            updated_at: data.updated_at || null,
            updated_by: data.updated_by || null,
          })
        }
        const stateLabel = next ? t('features.states.on') : t('features.states.off')
        toast.success(t('features.toggleSuccess', { name, state: stateLabel }))
      } catch (err) {
        setFeatures((prev) => ({ ...prev, [flag]: previous }))
        const msg = err?.response?.data?.error || t('features.toggleError', { name })
        toast.error(msg)
      } finally {
        setPending((prev) => {
          const { [flag]: _, ...rest } = prev
          return rest
        })
      }
    },
    [features, t],
  )

  const whoLabel = (() => {
    const u = meta.updated_by
    if (!u) return null
    return u.display_name || u.email || u._id || null
  })()

  return (
    <PageShell width="form">
        <div>
          <p className="text-sm text-foreground-secondary">{t('features.subtitle')}</p>
          <p className="mt-1 text-xs text-foreground-tertiary">
            {meta.updated_at && whoLabel
              ? t('features.lastUpdated', {
                  when: formatWhen(meta.updated_at),
                  who: whoLabel,
                })
              : t('features.neverUpdated')}
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-accent" />
          </div>
        ) : error ? (
          <Card>
            <CardContent className="pt-6">
              <p className="text-error">{error}</p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {FEATURE_FLAG_KEYS.map((flag) => {
              const enabled = !!features[flag]
              const isPending = !!pending[flag]
              return (
                <Card
                  key={flag}
                  className={cn(
                    'transition-shadow',
                    // Enabled flags get an accent ring (keeps the glass hairline
                    // intact rather than overriding the border colour).
                    enabled && 'ring-1 ring-accent/40',
                  )}
                >
                  <CardContent className="pt-5 pb-5 flex items-center justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-foreground">
                          {t(`features.flag.${flag}.name`, flag)}
                        </h3>
                        <code className="text-[10px] px-1.5 py-0.5 rounded bg-background-tertiary text-foreground-tertiary font-mono" dir="ltr">
                          {flag}
                        </code>
                      </div>
                      <p className="text-sm text-foreground-secondary mt-1">
                        {t(`features.flag.${flag}.description`, '')}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {isPending && <Loader2 className="h-4 w-4 animate-spin text-foreground-tertiary" />}
                      <Switch
                        size="lg"
                        checked={enabled}
                        disabled={isPending}
                        onCheckedChange={(next) => handleToggle(flag, next)}
                        aria-label={t(`features.flag.${flag}.name`, flag)}
                      />
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
    </PageShell>
  )
}

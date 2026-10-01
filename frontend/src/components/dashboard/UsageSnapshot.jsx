import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Coins, Hash } from 'lucide-react'
import { usageService } from '@/services/usageService'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import { CostValue } from '@/components/ui/CostValue'
import { CreditValue } from '@/components/ui/CreditValue'
import { canSeePriceInOrg } from '@/utils/money'
import { calendarMonthRange, toApiWindow, sumUsageRequests } from '@/utils/usageWindow'
import { IconTile } from '@/components/ui/icon-tile'
import { fmtNumber } from '@/utils/persianLocale'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'

/**
 * Calendar-month usage snapshot on the hub. Same `/usage/me` query as the
 * settings Usage tab default (`usageWindow.calendarMonthRange`) so the
 * ژتون + request tiles cannot drift. Granularity picker on that tab does
 * not feed this view.
 */

function UsageCard({ label, children }) {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      onClick={() => navigate('/settings#usage')}
      aria-label={label}
      className="flex w-full cursor-pointer items-center gap-3 rounded-xl p-4 text-start outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={solidPanelSx({ radius: RADII.surface })}
    >
      {children}
    </button>
  )
}

export default function UsageSnapshot() {
  const { t } = useTranslation('dashboard')
  const { user } = useAuth()
  const { workspaces, currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const priceVisible = canSeePriceInOrg(user, workspaces, workspaceId)

  const apiWindow = useMemo(() => toApiWindow(calendarMonthRange()), [])

  const { data } = useQuery({
    queryKey: ['usage', 'me', 'breakdown', workspaceId, apiWindow.from, apiWindow.to, 'feature'],
    queryFn: () =>
      usageService.getMyUsage({
        from: apiWindow.from,
        to: apiWindow.to,
        group_by: 'feature',
        workspace_id: workspaceId,
      }),
    enabled: !!workspaceId,
    staleTime: 60_000,
  })

  const totalCost = data?.total_cost
  const totalCredits = data?.total_credits ?? 0
  const totalRequests = useMemo(() => sumUsageRequests(data?.data), [data])

  // Render nothing (not an error/empty placeholder) until the query has data.
  if (!data) return null

  return (
    <section>
      <div className="mb-3">
        <h2 className="text-[17px] font-bold text-foreground">
          {t('hub.usageSnapshot.title')}
        </h2>
      </div>

      <div className="mx-auto grid grid-cols-1 gap-4 sm:grid-cols-2 lg:max-w-xl">
        <UsageCard label={priceVisible ? t('hub.usageSnapshot.spend') : t('hub.usageSnapshot.title')}>
          <div className="min-w-0 flex-1 text-start">
            {priceVisible && (
              <p className="text-[12px] font-medium text-fg-3">
                {t('hub.usageSnapshot.spend')}
              </p>
            )}
            {priceVisible ? (
              <p
                className="mt-1 truncate font-extrabold text-fg-0"
                style={{ fontSize: 24, letterSpacing: '-0.01em', lineHeight: 1.1 }}
              >
                <CostValue usd={totalCost} />
              </p>
            ) : (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <p
                      className="mt-1 truncate font-extrabold text-fg-0"
                      style={{ fontSize: 24, letterSpacing: '-0.01em', lineHeight: 1.1 }}
                    >
                      <CreditValue credits={totalCredits} suffixKey="credits.jetonSuffix" />
                    </p>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs text-start">
                    {t('hub.usageSnapshot.creditsHint')}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
          <IconTile icon={Coins} tone="emerald" size="xl" />
        </UsageCard>

        <UsageCard label={t('hub.usageSnapshot.requests')}>
          <div className="min-w-0 flex-1 text-start">
            <p className="text-[12px] font-medium text-fg-3">{t('hub.usageSnapshot.requests')}</p>
            <p
              className="mt-1 truncate font-extrabold tabular-nums text-fg-0"
              style={{ fontSize: 24, letterSpacing: '-0.01em', lineHeight: 1.1 }}
            >
              {fmtNumber(totalRequests)}
            </p>
          </div>
          <IconTile icon={Hash} tone="sky" size="xl" />
        </UsageCard>
      </div>
    </section>
  )
}

import { memo, useMemo } from 'react'
import { EChart } from './EChart'
import { useEchartTheme } from './useEchartTheme'
import { echarts } from './echartsCore'

// ECharts tooltip formatter returns are injected as innerHTML — slice labels are
// user-settable server aggregates (model id, company/project name), so escape.
const enc = echarts.format.encodeHTML

/**
 * Donut share chart (generalises the AdminDashboard PieChart) on ECharts. Shows
 * the top-N slices of a metric across breakdown rows (models, companies) with a
 * centred total. Slices use the resolved `--chart-N` ramp; the donut hole leaves
 * room for a centred summary the caller passes via `centerLabel`/`centerValue`
 * (rendered as a DOM overlay so it keeps the app's exact typography).
 *
 * @param {Array<object>} data       breakdown rows
 * @param {string} dataKey           numeric metric (default 'cost')
 * @param {string} labelKey          slice label field (default 'label')
 * @param {number} [topN]            keep the largest N slices (default 6)
 * @param {(v) => string} [valueFormatter]   tooltip value formatter
 * @param {React.ReactNode} [centerLabel]
 * @param {React.ReactNode} [centerValue]
 */
function SharePieBase({
  data,
  dataKey = 'cost',
  labelKey = 'label',
  topN = 6,
  valueFormatter,
  centerLabel,
  centerValue,
  height = '100%',
}) {
  const theme = useEchartTheme()
  const { isRTL } = theme

  const slices = useMemo(() => {
    const arr = Array.isArray(data) ? data : []
    return [...arr]
      .filter((r) => Number(r?.[dataKey]) > 0)
      .sort((a, b) => Number(b[dataKey]) - Number(a[dataKey]))
      .slice(0, topN)
  }, [data, dataKey, topN])

  const option = useMemo(() => {
    const palette = theme.palette
    const fmt = valueFormatter || ((v) => v)

    const pieData = slices.map((s, i) => ({
      name: String(s?.[labelKey] ?? ''),
      value: Number(s?.[dataKey]) || 0,
      itemStyle: { color: palette[i % palette.length] },
    }))

    return {
      textStyle: { fontFamily: theme.fontFamily },
      tooltip: {
        trigger: 'item',
        backgroundColor: theme.tooltipBg,
        borderColor: theme.gridColor,
        borderWidth: 1,
        textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
        extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
        formatter: (p) =>
          `<div style="display:flex;align-items:center;gap:8px">` +
          `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span>` +
          `<span style="color:${theme.fgSecondary}">${enc(String(p.name))}</span>` +
          `<span style="margin-inline-start:auto;font-variant-numeric:tabular-nums;color:${theme.fgColor}">` +
          `${fmt(p.value)}</span></div>` +
          `<div style="margin-top:2px;color:${theme.fgSecondary};font-size:11px">${p.percent}%</div>`,
      },
      legend: {
        type: 'scroll',
        bottom: 0,
        left: 'center',
        icon: 'circle',
        itemWidth: 8,
        itemHeight: 8,
        itemGap: 12,
        textStyle: { color: theme.fgSecondary, fontFamily: theme.fontFamily, fontSize: 11 },
        // RTL: lay legend items right-to-left so they read naturally.
        rtl: isRTL,
      },
      series: [
        {
          type: 'pie',
          radius: ['55%', '80%'],
          center: ['50%', '46%'],
          avoidLabelOverlap: false,
          padAngle: slices.length > 1 ? 2 : 0,
          itemStyle: { borderColor: theme.tooltipBg, borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scale: true, scaleSize: 4 },
          data: pieData,
        },
      ],
    }
  }, [slices, dataKey, labelKey, valueFormatter, theme, isRTL])

  return (
    <div className="relative h-full w-full">
      <EChart option={option} height={height} />

      {(centerLabel != null || centerValue != null) && (
        <div
          className="pointer-events-none absolute inset-x-0 top-0 flex flex-col items-center justify-center text-center"
          style={{ height: '92%' }}
        >
          {centerValue != null && (
            <div className="text-xl font-semibold tabular-nums text-foreground">{centerValue}</div>
          )}
          {centerLabel != null && (
            <div className="mt-0.5 text-[11px] uppercase tracking-wide text-foreground-tertiary">
              {centerLabel}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export const SharePie = memo(SharePieBase)
export default SharePie

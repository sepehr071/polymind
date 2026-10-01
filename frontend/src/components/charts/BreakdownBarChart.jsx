import { memo, useMemo } from 'react'
import { EChart } from './EChart'
import { useEchartTheme } from './useEchartTheme'
import { echarts } from './echartsCore'

// ECharts tooltip formatter returns are injected as innerHTML — server-aggregate
// labels (workspace display_name, project name, user email, model id) are all
// user-settable, so escape before interpolation.
const enc = echarts.format.encodeHTML

/**
 * Horizontal top-N comparison bars for the envelope `breakdown.by_model` /
 * `breakdown.children` rows (companies, teams, users, models), on ECharts.
 *
 * The value sits as a LABEL ON each bar (not on an axis), so readability never
 * depends on the value axis — which we HIDE, killing the degenerate "$0/$1"
 * tick strip that plagued the recharts version in Persian. Long category names
 * truncate on the Y axis (full name in the tooltip). Each bar takes a distinct
 * `--chart-N` ramp color for a ranked look without a legend.
 *
 * RTL: the category axis order + value axis + bar corner radius + on-bar label
 * position all mirror so bars grow from the correct edge.
 *
 * @param {Array<object>} data        breakdown rows
 * @param {string} dataKey            numeric metric to compare (default 'cost')
 * @param {string} labelKey           category label field (default 'label')
 * @param {number} [topN]             keep the largest N rows (default 8)
 * @param {(v) => string} [valueFormatter]   on-bar + tooltip value formatter
 * @param {string} [metricLabel]      localized name of the metric (tooltip)
 */
function BreakdownBarChartBase({
  data,
  dataKey = 'cost',
  labelKey = 'label',
  topN = 8,
  valueFormatter,
  metricLabel,
  height = '100%',
}) {
  const theme = useEchartTheme()
  const { isRTL } = theme

  const rows = useMemo(() => {
    const arr = Array.isArray(data) ? data : []
    return [...arr]
      .filter((r) => Number(r?.[dataKey]) > 0)
      .sort((a, b) => Number(b[dataKey]) - Number(a[dataKey]))
      .slice(0, topN)
  }, [data, dataKey, topN])

  const option = useMemo(() => {
    const palette = theme.palette
    const fmt = valueFormatter || ((v) => v)

    // ECharts category axis renders bottom→top; reverse so the largest is on top.
    const ordered = [...rows].reverse()
    const labels = ordered.map((r) => String(r?.[labelKey] ?? ''))
    const barData = ordered.map((r, i) => ({
      value: Number(r?.[dataKey]) || 0,
      itemStyle: {
        // top bars = first palette colors; ordered is reversed, so index from end.
        color: palette[(ordered.length - 1 - i) % palette.length],
        borderRadius: isRTL ? [6, 0, 0, 6] : [0, 6, 6, 0],
      },
    }))

    return {
      textStyle: { fontFamily: theme.fontFamily },
      grid: { top: 4, right: 16, bottom: 4, left: 8, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: theme.tooltipBg,
        borderColor: theme.gridColor,
        borderWidth: 1,
        textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
        extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
        formatter: (p) => {
          const name = enc(String(p.name || ''))
          const metric = metricLabel ? `${enc(String(metricLabel))}: ` : ''
          return (
            `<div style="font-weight:600;margin-bottom:2px">${name}</div>` +
            `<div style="color:${theme.fgSecondary}">${metric}` +
            `<span style="font-variant-numeric:tabular-nums;color:${theme.fgColor}">${fmt(p.value)}</span></div>`
          )
        },
      },
      xAxis: {
        type: 'value',
        inverse: isRTL,
        axisLine: { show: false },
        axisTick: { show: false },
        // HIDE the value tick labels — readability comes from the on-bar labels.
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'category',
        data: labels,
        inverse: false,
        position: isRTL ? 'right' : 'left',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: theme.fgSecondary,
          fontSize: 11,
          fontFamily: theme.fontFamily,
          width: 130,
          overflow: 'truncate',
        },
      },
      series: [
        {
          type: 'bar',
          data: barData,
          barMaxWidth: 28,
          label: {
            show: true,
            position: isRTL ? 'left' : 'right',
            color: theme.fgSecondary,
            fontFamily: theme.fontFamily,
            fontSize: 11,
            formatter: (p) => fmt(p.value),
          },
          emphasis: { disabled: true },
        },
      ],
    }
  }, [rows, dataKey, labelKey, valueFormatter, metricLabel, theme, isRTL])

  return <EChart option={option} height={height} />
}

export const BreakdownBarChart = memo(BreakdownBarChartBase)
export default BreakdownBarChart

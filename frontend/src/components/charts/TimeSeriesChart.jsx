import { memo, useMemo } from 'react'
import { echarts } from './echartsCore'
import { EChart } from './EChart'
import { useEchartTheme } from './useEchartTheme'
import { buildTooltipFormatter } from './ChartTooltip'

/**
 * Multi-series time-series chart for the analytics envelope's `series[]`, on
 * ECharts (canvas) for crisp Persian/RTL text + gradients.
 *
 * RTL-aware: the X (category) axis is `inverse` and the Y axis flips to the
 * right under `dir="rtl"` (the established AdminDashboard / HoldingOverview
 * pattern). Colors come from the resolved `--chart-N` ramp; `area` fills use a
 * per-series vertical gradient. Renders nothing meaningful (an empty canvas)
 * when `data` is empty — wrap in <ChartCard empty> to show a placeholder.
 *
 * @param {Array<object>} data       envelope `series` rows
 * @param {string} xKey              bucket field on each row (default 'bucket')
 * @param {Array<{
 *   key: string,           // dataKey on each row (cost|calls|tokens|active_users)
 *   label?: string,        // localized series label for tooltip + legend
 *   colorIndex?: number,   // 1-based --chart-N slot (defaults to position)
 *   formatter?: (v) => string, // tooltip value formatter
 *   yAxisId?: string,      // optional secondary axis id
 * }>} metrics              series to plot (≥1)
 * @param {'area'|'line'} [variant]  area (filled) or line
 * @param {(label) => string} [xTickFormatter]   localize bucket on the axis
 * @param {(v) => string} [yTickFormatter]       localize the primary Y axis
 * @param {(label) => string} [tooltipLabelFormatter]
 */

/** rgba(...) for a resolved `hsl(h s% l%)` color at a given alpha. */
function hslWithAlpha(hslColor, alpha) {
  // hsl(199 89% 48%) → hsla(199 89% 48% / 0.35)
  const inner = hslColor.replace(/^hsl\(/, '').replace(/\)$/, '')
  return `hsla(${inner} / ${alpha})`
}

function TimeSeriesChartBase({
  data,
  xKey = 'bucket',
  metrics,
  variant = 'area',
  xTickFormatter,
  yTickFormatter,
  tooltipLabelFormatter,
  height = '100%',
}) {
  const theme = useEchartTheme()
  const { isRTL } = theme

  const option = useMemo(() => {
    const rows = Array.isArray(data) ? data : []
    const series = Array.isArray(metrics) ? metrics : []
    const palette = theme.palette

    const formatters = {}
    const labelKeys = {}
    for (const m of series) {
      if (m.formatter) formatters[m.key] = m.formatter
      if (m.label) labelKeys[m.key] = m.label
    }

    const categories = rows.map((r) => r?.[xKey])

    const echSeries = series.map((m, i) => {
      const color = palette[((m.colorIndex ?? i + 1) - 1) % palette.length]
      const base = {
        id: m.key,
        name: m.label || m.key,
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color },
        itemStyle: { color },
        data: rows.map((r) => r?.[m.key] ?? 0),
        // No emphasis.focus: the hover state-transition interpolates the
        // gradient areaStyle and crashes zrender (interpolate1DArray /
        // addColorStop 'undefined') — and focus only dims OTHER series anyway.
        emphasis: { disabled: true },
      }
      if (variant === 'area') {
        base.areaStyle = {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: hslWithAlpha(color, 0.35) },
            { offset: 1, color: hslWithAlpha(color, 0) },
          ]),
        }
      }
      return base
    })

    return {
      color: palette,
      textStyle: { fontFamily: theme.fontFamily },
      grid: { top: 12, right: 12, bottom: 4, left: 8, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'transparent',
        borderWidth: 0,
        padding: 0,
        axisPointer: { type: 'line', lineStyle: { color: theme.gridColor, width: 1 } },
        formatter: buildTooltipFormatter({
          formatters,
          labelKeys,
          labelFormatter: tooltipLabelFormatter,
          theme,
        }),
      },
      xAxis: {
        type: 'category',
        boundaryGap: variant !== 'area',
        inverse: isRTL,
        data: categories,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: theme.axisColor,
          fontSize: 11,
          fontFamily: theme.fontFamily,
          hideOverlap: true,
          formatter: xTickFormatter ? (v) => xTickFormatter(v) : undefined,
        },
        // No vertical split lines (mirror old CartesianGrid vertical={false}).
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        position: isRTL ? 'right' : 'left',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: theme.axisColor,
          fontSize: 11,
          fontFamily: theme.fontFamily,
          formatter: yTickFormatter ? (v) => yTickFormatter(v) : undefined,
        },
        splitLine: { show: true, lineStyle: { color: theme.gridColor, type: 'dashed' } },
      },
      series: echSeries,
    }
  }, [data, metrics, variant, xKey, xTickFormatter, yTickFormatter, tooltipLabelFormatter, theme, isRTL])

  return <EChart option={option} height={height} />
}

export const TimeSeriesChart = memo(TimeSeriesChartBase)
export default TimeSeriesChart

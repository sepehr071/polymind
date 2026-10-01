import { memo, useMemo } from 'react'
import { echarts } from './echartsCore'
import { EChart } from './EChart'
import { useEchartTheme } from './useEchartTheme'

/**
 * Tiny inline trend series for StatTile + table rows, on ECharts. No axes, no
 * grid, no tooltip, no legend — pure shape. Accepts a flat array of numbers
 * (`[1,2,3]`) or of objects keyed by `dataKey`.
 *
 * Renders nothing (an empty spacer of `height`) when there are < 2 points, so
 * a single-bucket or empty window degrades gracefully instead of throwing.
 *
 * `colorIndex` selects the `--chart-N` ramp slot; `tone` overrides to a
 * semantic up/down color independent of the series identity.
 */
function SparklineBase({
  data,
  dataKey = 'value',
  colorIndex = 1,
  tone,
  width = '100%',
  height = 28,
  strokeWidth = 1.5,
}) {
  const theme = useEchartTheme()

  const points = Array.isArray(data) ? data : []
  const values = points.map((p) => (typeof p === 'number' ? p : Number(p?.[dataKey]) || 0))

  // tone overrides the ramp color with a semantic up/down RGB token (resolved to
  // a literal for the canvas); otherwise pick the `--chart-N` ramp slot.
  const stroke = useMemo(() => {
    if (tone === 'positive' || tone === 'negative') {
      const fallback = tone === 'positive' ? '#22c55e' : '#ef4444'
      if (typeof document === 'undefined') return fallback
      const token = tone === 'positive' ? '--success' : '--error'
      const raw = getComputedStyle(document.documentElement).getPropertyValue(token).trim()
      return raw ? `rgb(${raw})` : fallback
    }
    return theme.palette[(colorIndex - 1) % theme.palette.length]
  }, [tone, colorIndex, theme])

  const option = useMemo(() => {
    const inner = stroke.replace(/^hsl\(/, '').replace(/\)$/, '')
    const isHsl = stroke.startsWith('hsl')
    const fade = (a) => (isHsl ? `hsla(${inner} / ${a})` : stroke)
    return {
      grid: { top: 2, right: 0, bottom: 2, left: 0 },
      xAxis: { type: 'category', show: false, boundaryGap: false },
      yAxis: { type: 'value', show: false, scale: true },
      tooltip: { show: false },
      legend: { show: false },
      series: [
        {
          type: 'line',
          data: values,
          smooth: true,
          showSymbol: false,
          silent: true,
          lineStyle: { width: strokeWidth, color: stroke },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: fade(0.28) },
              { offset: 1, color: fade(0) },
            ]),
          },
        },
      ],
    }
    // values length is the meaningful dep; stringify to avoid array identity churn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values.join(','), stroke, strokeWidth])

  if (values.length < 2) {
    return <div style={{ height }} aria-hidden />
  }

  return (
    <div style={{ width, height }} aria-hidden>
      <EChart option={option} height={height} />
    </div>
  )
}

export const Sparkline = memo(SparklineBase)
export default Sparkline

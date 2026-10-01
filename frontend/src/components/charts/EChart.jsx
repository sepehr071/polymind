import { memo, useEffect, useRef } from 'react'
import { echarts } from './echartsCore'

/**
 * Thin imperative wrapper around an ECharts canvas instance for the analytics
 * chart kit. Owns the lifecycle so the chart components stay declarative —
 * they just compute an `option` and hand it over.
 *
 * - Lazily `echarts.init`s on the container div (canvas renderer).
 * - Re-applies `option` with `{ notMerge: true }` on every change, so a series
 *   set that shrinks (fewer metrics, RTL flip rebuilding axes) never leaves
 *   stale geometry merged in.
 * - A ResizeObserver drives `chart.resize()` — required because the kit sizes
 *   via a flex/height wrapper, not fixed pixels, and ECharts canvas does NOT
 *   auto-track its container.
 * - Disposes on unmount (frees the canvas + listeners).
 *
 * Height comes from the wrapper div style (default fills the parent, matching
 * the old ResponsiveContainer height='100%' contract that ChartCard relies on).
 *
 * @param {object} option            ECharts option object (rebuilt by the chart)
 * @param {number|string} [height]   wrapper height (px number or CSS string)
 * @param {string} [className]
 * @param {(chart:object|null)=>void} [instanceRef]  receives the live ECharts
 *        instance on init and `null` on dispose, so a parent can call imperative
 *        APIs (e.g. `getDataURL` for PNG export) without owning the lifecycle.
 *        Non-breaking — existing callers omit it.
 */
function EChartBase({ option, height = '100%', className, instanceRef }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)

  // Init once + dispose on unmount. `instanceRef` intentionally NOT in the dep
  // array — it's a stable handoff callback; re-running init on its identity
  // change would needlessly tear down + rebuild the canvas.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return undefined
    const chart = echarts.init(el, null, { renderer: 'canvas' })
    chartRef.current = chart
    instanceRef?.(chart)

    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(el)

    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
      instanceRef?.(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Re-apply option whenever it changes. notMerge so axis/series removals stick.
  // `animation:false` (overridable per-chart) — a notMerge re-option while a
  // zrender animation clip is still in flight (entrance sweep, rapid
  // granularity toggles) makes `interpolate1DArray` step a disposed series
  // array → "Cannot read properties of undefined (reading 'length')" → the
  // whole section ErrorBoundary. No clips = no interpolation = no crash.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !option) return
    chart.setOption({ animation: false, ...option }, { notMerge: true })
  }, [option])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: '100%', height: typeof height === 'number' ? `${height}px` : height }}
    />
  )
}

export const EChart = memo(EChartBase)
export default EChart

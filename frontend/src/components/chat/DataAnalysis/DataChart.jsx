import { memo, useMemo } from 'react'
import { EChart } from '../../charts/EChart'
import { useEchartTheme } from '../../charts/useEchartTheme'
import { echarts } from '../../charts/echartsCore'
import { fmtNumber } from '../../../utils/persianLocale'

// ECharts tooltip `formatter` returns are injected as innerHTML (renderMode
// 'html', no auto-escape). Model-generated category values + encoding key
// labels MUST be HTML-escaped or a cell like `<img src=x onerror=...>` is a
// stored-XSS sink. Numeric values (fmtNumber/percent) are inherently safe.
const enc = echarts.format.encodeHTML

/**
 * Data Analyzer chart artifact.
 *
 * Renders a themed ECharts `option` from the backend's STRUCTURAL chart spec —
 * NOT a pre-baked option. The agentic Python loop emits:
 *   { kind:'bar'|'line'|'pie'|'scatter'|'area'|'histogram'|'box'|'heatmap'|'combo',
 *     encoding:{ x:<col>, y:<col>, series:<col|null>, y2:<col|null> },
 *     data:[{...rows}], title:<str|null> }
 *
 * We map `kind` → an ECharts series type and build axes/legend from the
 * encoding, reusing the analytics chart kit's conventions:
 *   - colors come from the resolved `--chart-N` ramp (`theme.palette`) — the
 *     canvas painter can't read CSS vars, so the theme hook resolves literals;
 *   - `theme.fontFamily` is pinned (Vazirmatn/Inter) so Persian glyphs render;
 *   - RTL flips the category/value axis sides + bar corner radius via
 *     `theme.isRTL`, matching TimeSeriesChart / BreakdownBarChart;
 *   - NO `emphasis.focus` and NO animations (EChart.jsx forces animation:false)
 *     — re-adding either crashes zrender (interpolate1DArray / addColorStop)
 *     and trips the section ErrorBoundary. Every series sets
 *     `emphasis:{disabled:true}`.
 *
 * Kind → series mapping:
 *   bar       → type:'bar'      (category x, value y)
 *   line      → type:'line'     (category x, value y, smooth)
 *   area      → type:'line' + areaStyle:{} gradient fill
 *   pie       → type:'pie'      (donut; name=x, value=y)
 *   scatter   → type:'scatter'  (value x, value y — numeric correlation)
 *   histogram → type:'bar'      (JS-binned numeric x → bucket counts)
 *   combo     → type:'bar'+'line' on two y-axes (y=bar, y2=line)
 *   box       → type:'boxplot'  (JS 5-number summary of y per x category)
 *   heatmap   → type:'heatmap'  (x×y grid, value=y2, continuous visualMap)
 *
 * @param {'bar'|'line'|'pie'|'scatter'|'area'|'histogram'|'box'|'heatmap'|'combo'} kind
 * @param {{ x:string, y:string, series?:string|null, y2?:string|null }} encoding
 * @param {Array<Record<string, unknown>>} data
 * @param {string|null} [title]
 * @param {number|string} [height]
 * @param {(chart:object|null)=>void} [instanceRef]  forwarded to EChart so a
 *        parent can grab the instance for PNG export (chart download button).
 */

/** rgba(...) for a resolved `hsl(h s% l%)` color at a given alpha. */
function hslWithAlpha(hslColor, alpha) {
  const inner = hslColor.replace(/^hsl\(/, '').replace(/\)$/, '')
  return `hsla(${inner} / ${alpha})`
}

/** Coerce a cell to a finite number (chart axes / pie values), else 0. */
function num(v) {
  if (v == null) return 0
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

/** Coerce to a finite number, else null (so non-numeric cells can be skipped). */
function toFiniteOrNull(v) {
  if (v == null || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

/** Quantile of a SORTED ascending numeric array via linear interpolation. */
function quantileSorted(sorted, q) {
  if (sorted.length === 0) return 0
  if (sorted.length === 1) return sorted[0]
  const pos = (sorted.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  if (lo === hi) return sorted[lo]
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

/**
 * Bin a numeric array into ~target buckets. Width is a "nice" round step (1/2/5
 * × 10^k) derived from the data range so bucket labels read cleanly. Returns
 * `{ labels, counts }` (empty arrays for a degenerate / single-value range).
 */
function histogramBins(values, target = 20) {
  const nums = values.map(toFiniteOrNull).filter((n) => n != null)
  if (nums.length === 0) return { labels: [], counts: [] }
  let min = Math.min(...nums)
  let max = Math.max(...nums)
  if (min === max) {
    // All identical — a single bucket holding everything.
    return { labels: [fmtNumber(min)], counts: [nums.length] }
  }
  const rawStep = (max - min) / target
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)))
  const norm = rawStep / mag
  const niceMul = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10
  const step = niceMul * mag
  const start = Math.floor(min / step) * step
  const end = Math.ceil(max / step) * step
  const binCount = Math.max(1, Math.round((end - start) / step))
  const counts = new Array(binCount).fill(0)
  for (const n of nums) {
    let idx = Math.floor((n - start) / step)
    if (idx < 0) idx = 0
    if (idx >= binCount) idx = binCount - 1 // include the max edge in the last bin
    counts[idx] += 1
  }
  const labels = counts.map((_, i) => {
    const lo = start + i * step
    const hi = lo + step
    return `${fmtNumber(lo)}–${fmtNumber(hi)}`
  })
  return { labels, counts }
}

function DataChartBase({ kind = 'bar', encoding, data, title = null, height = 280, instanceRef }) {
  const theme = useEchartTheme()
  const { isRTL } = theme

  const option = useMemo(() => {
    const rows = Array.isArray(data) ? data : []
    const palette = theme.palette
    const xKey = encoding?.x
    const yKey = encoding?.y
    const seriesKey = encoding?.series || null

    const baseTextStyle = { fontFamily: theme.fontFamily }
    const titleBlock = title
      ? {
          title: {
            text: title,
            left: isRTL ? 'right' : 'left',
            textStyle: {
              color: theme.fgColor,
              fontFamily: theme.fontFamily,
              fontSize: 13,
              fontWeight: 600,
            },
          },
        }
      : {}
    // Leave headroom for the title row when present.
    const gridTop = title ? 40 : 16

    // ── Pie ──────────────────────────────────────────────────────────────
    // name = x column, value = y column. Donut to match the analytics SharePie.
    if (kind === 'pie') {
      const pieData = rows.map((r, i) => ({
        name: String(r?.[xKey] ?? ''),
        value: num(r?.[yKey]),
        itemStyle: { color: palette[i % palette.length] },
      }))
      return {
        ...titleBlock,
        color: palette,
        textStyle: baseTextStyle,
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
            `${fmtNumber(p.value)}</span></div>` +
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
          rtl: isRTL,
        },
        series: [
          {
            type: 'pie',
            radius: ['52%', '78%'],
            center: ['50%', title ? '52%' : '46%'],
            avoidLabelOverlap: true,
            padAngle: pieData.length > 1 ? 2 : 0,
            itemStyle: { borderColor: theme.tooltipBg, borderWidth: 2 },
            label: { show: false },
            labelLine: { show: false },
            // scale-on-hover is safe (no focus, no gradient interpolation).
            emphasis: { scale: true, scaleSize: 4 },
            data: pieData,
          },
        ],
      }
    }

    // ── Scatter ──────────────────────────────────────────────────────────
    // Both axes are VALUE axes (numeric correlation). Optional `series` splits
    // the points into colored groups sharing the same x/y axes.
    if (kind === 'scatter') {
      let echSeries
      if (seriesKey) {
        const groups = new Map()
        for (const r of rows) {
          const g = String(r?.[seriesKey] ?? '')
          if (!groups.has(g)) groups.set(g, [])
          groups.get(g).push([num(r?.[xKey]), num(r?.[yKey])])
        }
        echSeries = Array.from(groups.entries()).map(([name, points], i) => ({
          name,
          type: 'scatter',
          symbolSize: 9,
          itemStyle: { color: palette[i % palette.length], opacity: 0.85 },
          data: points,
          emphasis: { disabled: true },
        }))
      } else {
        echSeries = [
          {
            name: yKey || 'y',
            type: 'scatter',
            symbolSize: 9,
            itemStyle: { color: palette[0], opacity: 0.85 },
            data: rows.map((r) => [num(r?.[xKey]), num(r?.[yKey])]),
            emphasis: { disabled: true },
          },
        ]
      }
      return {
        ...titleBlock,
        color: palette,
        textStyle: baseTextStyle,
        grid: { top: gridTop, right: 16, bottom: seriesKey ? 28 : 8, left: 8, containLabel: true },
        tooltip: {
          trigger: 'item',
          backgroundColor: theme.tooltipBg,
          borderColor: theme.gridColor,
          borderWidth: 1,
          textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
          extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
          formatter: (p) => {
            const [x, y] = p.value || []
            const sName = seriesKey
              ? `<div style="font-weight:600;margin-bottom:2px">${enc(String(p.seriesName))}</div>`
              : ''
            return (
              sName +
              `<div style="color:${theme.fgSecondary}">${enc(String(xKey))}: ` +
              `<span style="font-variant-numeric:tabular-nums;color:${theme.fgColor}">${fmtNumber(x)}</span></div>` +
              `<div style="color:${theme.fgSecondary}">${enc(String(yKey))}: ` +
              `<span style="font-variant-numeric:tabular-nums;color:${theme.fgColor}">${fmtNumber(y)}</span></div>`
            )
          },
        },
        legend: seriesKey
          ? {
              bottom: 0,
              left: 'center',
              icon: 'circle',
              itemWidth: 8,
              itemHeight: 8,
              textStyle: { color: theme.fgSecondary, fontFamily: theme.fontFamily, fontSize: 11 },
              rtl: isRTL,
            }
          : undefined,
        xAxis: {
          type: 'value',
          name: xKey || undefined,
          nameLocation: 'middle',
          nameGap: 26,
          nameTextStyle: { color: theme.axisColor, fontFamily: theme.fontFamily, fontSize: 11 },
          inverse: isRTL,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: theme.axisColor,
            fontSize: 11,
            fontFamily: theme.fontFamily,
            formatter: (v) => fmtNumber(v),
          },
          splitLine: { show: true, lineStyle: { color: theme.gridColor, type: 'dashed' } },
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
            formatter: (v) => fmtNumber(v),
          },
          splitLine: { show: true, lineStyle: { color: theme.gridColor, type: 'dashed' } },
        },
        series: echSeries,
      }
    }

    // ── Histogram ────────────────────────────────────────────────────────
    // JS-bin the numeric `encoding.x` column into ~20 nice buckets → a bar of
    // counts. Category axis = bucket ranges, value axis = frequency.
    if (kind === 'histogram') {
      const { labels, counts } = histogramBins(rows.map((r) => r?.[xKey]))
      const color = palette[0]
      return {
        ...titleBlock,
        color: palette,
        textStyle: baseTextStyle,
        grid: { top: gridTop, right: 14, bottom: 6, left: 8, containLabel: true },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow', lineStyle: { color: theme.gridColor, width: 1 } },
          backgroundColor: theme.tooltipBg,
          borderColor: theme.gridColor,
          borderWidth: 1,
          textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
          extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
          valueFormatter: (v) => fmtNumber(v),
        },
        xAxis: {
          type: 'category',
          data: labels,
          inverse: isRTL,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: theme.axisColor,
            fontSize: 11,
            fontFamily: theme.fontFamily,
            hideOverlap: true,
          },
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
            formatter: (v) => fmtNumber(v),
          },
          splitLine: { show: true, lineStyle: { color: theme.gridColor, type: 'dashed' } },
        },
        series: [
          {
            name: xKey || 'count',
            type: 'bar',
            data: counts,
            // Touching bars read as a continuous distribution.
            barCategoryGap: '2%',
            itemStyle: { color, borderRadius: isRTL ? [0, 0, 3, 3] : [3, 3, 0, 0] },
            emphasis: { disabled: true },
          },
        ],
      }
    }

    // ── Combo (bar + line, dual y-axis) ────────────────────────────────────
    // categories from `encoding.x`; bar series = `encoding.y` (left axis), line
    // series = `encoding.y2` (right axis, yAxisIndex:1).
    if (kind === 'combo') {
      const y2Key = encoding?.y2 || null
      const comboCats = []
      const comboSeen = new Set()
      for (const r of rows) {
        const c = String(r?.[xKey] ?? '')
        if (!comboSeen.has(c)) {
          comboSeen.add(c)
          comboCats.push(c)
        }
      }
      const barByCat = new Map()
      const lineByCat = new Map()
      for (const r of rows) {
        const c = String(r?.[xKey] ?? '')
        barByCat.set(c, num(r?.[yKey]))
        if (y2Key) lineByCat.set(c, num(r?.[y2Key]))
      }
      const barColor = palette[0]
      const lineColor = palette[1 % palette.length]
      return {
        ...titleBlock,
        color: palette,
        textStyle: baseTextStyle,
        grid: { top: gridTop, right: 14, bottom: 28, left: 8, containLabel: true },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow', lineStyle: { color: theme.gridColor, width: 1 } },
          backgroundColor: theme.tooltipBg,
          borderColor: theme.gridColor,
          borderWidth: 1,
          textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
          extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
          valueFormatter: (v) => fmtNumber(v),
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
          rtl: isRTL,
        },
        xAxis: {
          type: 'category',
          data: comboCats,
          inverse: isRTL,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: theme.axisColor,
            fontSize: 11,
            fontFamily: theme.fontFamily,
            hideOverlap: true,
          },
          splitLine: { show: false },
        },
        // Two value axes. Under RTL the left/right physical sides swap so the
        // bar measure stays on the reading-start edge.
        yAxis: [
          {
            type: 'value',
            position: isRTL ? 'right' : 'left',
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: {
              color: theme.axisColor,
              fontSize: 11,
              fontFamily: theme.fontFamily,
              formatter: (v) => fmtNumber(v),
            },
            splitLine: { show: true, lineStyle: { color: theme.gridColor, type: 'dashed' } },
          },
          {
            type: 'value',
            position: isRTL ? 'left' : 'right',
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: {
              color: theme.axisColor,
              fontSize: 11,
              fontFamily: theme.fontFamily,
              formatter: (v) => fmtNumber(v),
            },
            splitLine: { show: false },
          },
        ],
        series: [
          {
            name: yKey || 'bar',
            type: 'bar',
            yAxisIndex: 0,
            data: comboCats.map((c) => barByCat.get(c) ?? 0),
            barMaxWidth: 36,
            itemStyle: { color: barColor, borderRadius: isRTL ? [0, 0, 4, 4] : [4, 4, 0, 0] },
            emphasis: { disabled: true },
          },
          {
            name: y2Key || 'line',
            type: 'line',
            yAxisIndex: 1,
            smooth: true,
            showSymbol: false,
            data: comboCats.map((c) => (y2Key ? lineByCat.get(c) ?? 0 : 0)),
            lineStyle: { width: 2, color: lineColor },
            itemStyle: { color: lineColor },
            emphasis: { disabled: true },
          },
        ],
      }
    }

    // ── Box plot (5-number summary per category) ───────────────────────────
    // Group rows by `encoding.x`; compute [min,Q1,median,Q3,max] of the numeric
    // `encoding.y` per group. Category axis = groups.
    if (kind === 'box') {
      const groups = new Map()
      for (const r of rows) {
        const g = String(r?.[xKey] ?? '')
        const v = toFiniteOrNull(r?.[yKey])
        if (v == null) continue
        if (!groups.has(g)) groups.set(g, [])
        groups.get(g).push(v)
      }
      const boxCats = Array.from(groups.keys())
      const boxData = boxCats.map((g) => {
        const sorted = groups.get(g).slice().sort((a, b) => a - b)
        return [
          sorted[0],
          quantileSorted(sorted, 0.25),
          quantileSorted(sorted, 0.5),
          quantileSorted(sorted, 0.75),
          sorted[sorted.length - 1],
        ]
      })
      const color = palette[0]
      return {
        ...titleBlock,
        color: palette,
        textStyle: baseTextStyle,
        grid: { top: gridTop, right: 14, bottom: 6, left: 8, containLabel: true },
        tooltip: {
          trigger: 'item',
          backgroundColor: theme.tooltipBg,
          borderColor: theme.gridColor,
          borderWidth: 1,
          textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
          extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
          formatter: (p) => {
            const v = p.value || []
            // boxplot value is [name(idx0 in series data), min, Q1, med, Q3, max];
            // ECharts injects the category as value[0], stats at [1..5].
            const [, lo, q1, med, q3, hi] = v
            const row = (lbl, n) =>
              `<div style="color:${theme.fgSecondary}">${lbl}: ` +
              `<span style="font-variant-numeric:tabular-nums;color:${theme.fgColor}">${fmtNumber(n)}</span></div>`
            return (
              `<div style="font-weight:600;margin-bottom:2px">${enc(String(p.name))}</div>` +
              row('max', hi) + row('Q3', q3) + row('median', med) + row('Q1', q1) + row('min', lo)
            )
          },
        },
        xAxis: {
          type: 'category',
          data: boxCats,
          inverse: isRTL,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: theme.axisColor,
            fontSize: 11,
            fontFamily: theme.fontFamily,
            hideOverlap: true,
          },
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
            formatter: (v) => fmtNumber(v),
          },
          splitLine: { show: true, lineStyle: { color: theme.gridColor, type: 'dashed' } },
        },
        series: [
          {
            name: yKey || 'value',
            type: 'boxplot',
            data: boxData,
            itemStyle: { color: hslWithAlpha(color, 0.18), borderColor: color, borderWidth: 1.5 },
            emphasis: { disabled: true },
          },
        ],
      }
    }

    // ── Heatmap (x×y grid, value=y2) ───────────────────────────────────────
    // Distinct x → columns, distinct y → rows, value = `encoding.y2`. A
    // continuous visualMap drives the color ramp from the data min/max.
    if (kind === 'heatmap') {
      const y2Key = encoding?.y2 || null
      const xCats = []
      const xSeen = new Set()
      const yCats = []
      const ySeen = new Set()
      for (const r of rows) {
        const xv = String(r?.[xKey] ?? '')
        const yv = String(r?.[yKey] ?? '')
        if (!xSeen.has(xv)) {
          xSeen.add(xv)
          xCats.push(xv)
        }
        if (!ySeen.has(yv)) {
          ySeen.add(yv)
          yCats.push(yv)
        }
      }
      const xIndex = new Map(xCats.map((c, i) => [c, i]))
      const yIndex = new Map(yCats.map((c, i) => [c, i]))
      let vMin = Infinity
      let vMax = -Infinity
      const heatData = []
      for (const r of rows) {
        const xi = xIndex.get(String(r?.[xKey] ?? ''))
        const yi = yIndex.get(String(r?.[yKey] ?? ''))
        if (xi == null || yi == null) continue
        const value = num(y2Key ? r?.[y2Key] : r?.[yKey])
        if (value < vMin) vMin = value
        if (value > vMax) vMax = value
        heatData.push([xi, yi, value])
      }
      if (!Number.isFinite(vMin)) {
        vMin = 0
        vMax = 1
      }
      if (vMin === vMax) vMax = vMin + 1 // avoid a zero-width color scale
      return {
        ...titleBlock,
        textStyle: baseTextStyle,
        grid: { top: gridTop, right: 14, bottom: 56, left: 8, containLabel: true },
        tooltip: {
          trigger: 'item',
          backgroundColor: theme.tooltipBg,
          borderColor: theme.gridColor,
          borderWidth: 1,
          textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
          extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
          formatter: (p) => {
            const [xi, yi, value] = p.value || []
            return (
              `<div style="color:${theme.fgSecondary}">${enc(String(xKey))}: ` +
              `<span style="color:${theme.fgColor}">${enc(String(xCats[xi] ?? ''))}</span></div>` +
              `<div style="color:${theme.fgSecondary}">${enc(String(yKey))}: ` +
              `<span style="color:${theme.fgColor}">${enc(String(yCats[yi] ?? ''))}</span></div>` +
              `<div style="color:${theme.fgSecondary}">${enc(String(y2Key || 'value'))}: ` +
              `<span style="font-variant-numeric:tabular-nums;color:${theme.fgColor}">${fmtNumber(value)}</span></div>`
            )
          },
        },
        xAxis: {
          type: 'category',
          data: xCats,
          inverse: isRTL,
          splitArea: { show: true, areaStyle: { color: ['transparent'] } },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: theme.axisColor,
            fontSize: 11,
            fontFamily: theme.fontFamily,
            hideOverlap: true,
          },
        },
        yAxis: {
          type: 'category',
          data: yCats,
          position: isRTL ? 'right' : 'left',
          splitArea: { show: true, areaStyle: { color: ['transparent'] } },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: theme.axisColor, fontSize: 11, fontFamily: theme.fontFamily },
        },
        visualMap: {
          type: 'continuous',
          min: vMin,
          max: vMax,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: 0,
          itemWidth: 12,
          itemHeight: 90,
          textStyle: { color: theme.fgSecondary, fontFamily: theme.fontFamily, fontSize: 11 },
          // Low → high ramp across the resolved theme series colors (canvas can't
          // read CSS vars, so these are already literal `hsl(...)`).
          inRange: { color: [palette[2 % palette.length], palette[0], palette[4 % palette.length]] },
          formatter: (v) => fmtNumber(v),
        },
        series: [
          {
            name: y2Key || 'value',
            type: 'heatmap',
            data: heatData,
            itemStyle: { borderColor: theme.tooltipBg, borderWidth: 1 },
            label: { show: false },
            emphasis: { disabled: true },
          },
        ],
      }
    }

    // ── Bar / Line / Area (cartesian, category x) ──────────────────────────
    const isArea = kind === 'area'
    const isBar = kind === 'bar'

    // Category axis values come from distinct x in row order (first-seen wins).
    const categories = []
    const seen = new Set()
    for (const r of rows) {
      const c = String(r?.[xKey] ?? '')
      if (!seen.has(c)) {
        seen.add(c)
        categories.push(c)
      }
    }

    // Series names: distinct `series` values, else a single series = the y col.
    const seriesNames = seriesKey
      ? Array.from(new Set(rows.map((r) => String(r?.[seriesKey] ?? ''))))
      : [yKey || 'value']

    // For grouped series, index y by (category × seriesName).
    const echSeries = seriesNames.map((name, i) => {
      const color = palette[i % palette.length]
      const dataByCat = new Map()
      for (const r of rows) {
        const cat = String(r?.[xKey] ?? '')
        const belongs = seriesKey ? String(r?.[seriesKey] ?? '') === name : true
        if (belongs) dataByCat.set(cat, num(r?.[yKey]))
      }
      const seriesData = categories.map((c) => dataByCat.get(c) ?? 0)

      const s = {
        name,
        type: isBar ? 'bar' : 'line',
        data: seriesData,
        itemStyle: isBar
          ? { color, borderRadius: isRTL ? [0, 0, 4, 4] : [4, 4, 0, 0] }
          : { color },
        emphasis: { disabled: true },
      }
      if (!isBar) {
        s.smooth = true
        s.showSymbol = false
        s.lineStyle = { width: 2, color }
        if (isArea) {
          s.areaStyle = {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: hslWithAlpha(color, 0.35) },
                { offset: 1, color: hslWithAlpha(color, 0) },
              ],
            },
          }
        }
      }
      if (isBar) s.barMaxWidth = 36
      return s
    })

    const multi = seriesNames.length > 1

    return {
      ...titleBlock,
      color: palette,
      textStyle: baseTextStyle,
      grid: { top: gridTop, right: 14, bottom: multi ? 28 : 6, left: 8, containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: isBar ? 'shadow' : 'line', lineStyle: { color: theme.gridColor, width: 1 } },
        backgroundColor: theme.tooltipBg,
        borderColor: theme.gridColor,
        borderWidth: 1,
        textStyle: { color: theme.fgColor, fontFamily: theme.fontFamily, fontSize: 12 },
        extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);',
        valueFormatter: (v) => fmtNumber(v),
      },
      legend: multi
        ? {
            type: 'scroll',
            bottom: 0,
            left: 'center',
            icon: 'circle',
            itemWidth: 8,
            itemHeight: 8,
            itemGap: 12,
            textStyle: { color: theme.fgSecondary, fontFamily: theme.fontFamily, fontSize: 11 },
            rtl: isRTL,
          }
        : undefined,
      xAxis: {
        type: 'category',
        data: categories,
        boundaryGap: isBar || isArea ? true : false,
        inverse: isRTL,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: theme.axisColor,
          fontSize: 11,
          fontFamily: theme.fontFamily,
          hideOverlap: true,
        },
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
          formatter: (v) => fmtNumber(v),
        },
        splitLine: { show: true, lineStyle: { color: theme.gridColor, type: 'dashed' } },
      },
      series: echSeries,
    }
  }, [kind, encoding, data, title, theme, isRTL])

  return <EChart option={option} height={height} instanceRef={instanceRef} />
}

export const DataChart = memo(DataChartBase)
export default DataChart

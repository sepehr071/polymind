// Analytics chart kit — shared Apache ECharts wrappers for the admin/platform
// analytics dashboards (spec §6). Theming via the `--chart-N` HSL-triplet
// tokens (index.css), RESOLVED to literal colors for the canvas through
// useEchartTheme; RTL-aware; graceful loading/empty states via ChartCard.
export { ChartCard } from './ChartCard'
export { EChart } from './EChart'
export { useEchartTheme } from './useEchartTheme'
export { buildTooltipFormatter } from './ChartTooltip'
export { TimeSeriesChart } from './TimeSeriesChart'
export { BreakdownBarChart } from './BreakdownBarChart'
export { SharePie } from './SharePie'
export { Sparkline } from './Sparkline'
export { GranularityRangePicker } from './GranularityRangePicker'
export { ExportButton } from './ExportButton'
export {
  CHART_COLORS,
  CHART_SERIES_COUNT,
  chartColor,
  chartColorAlpha,
} from './chartColors'

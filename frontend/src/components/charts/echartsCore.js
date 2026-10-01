/**
 * Tree-shaken ECharts registration — imported ONCE so the whole chart kit
 * shares a single registered core (no full `echarts` bundle).
 *
 * We register only the chart types + components the analytics kit actually
 * uses (Line/Bar/Pie + Grid/Tooltip/Legend + the Canvas renderer). Any new
 * chart feature MUST add its module here or `setOption` silently ignores it.
 *
 * Re-exports the configured `echarts` namespace so callers get `echarts.init`,
 * `echarts.graphic.LinearGradient`, `echarts.format.encodeHTML`, etc. from the
 * same registered instance.
 */
import * as echarts from 'echarts/core'
import {
  LineChart,
  BarChart,
  PieChart,
  ScatterChart,
  BoxplotChart,
  HeatmapChart,
} from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart,
  BarChart,
  PieChart,
  // ScatterChart powers the Data Analyzer scatter artifact. `area` reuses
  // LineChart (areaStyle); without this registration scatter silently no-ops.
  ScatterChart,
  // BoxplotChart powers the `box` Data Analyzer artifact (5-number summaries);
  // HeatmapChart + VisualMapComponent power the `heatmap` artifact (x×y grid
  // with a continuous color ramp). `histogram` reuses BarChart and `combo`
  // reuses Bar+Line, so neither needs its own registration. Without these,
  // setOption silently ignores the box/heatmap series.
  BoxplotChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  CanvasRenderer,
])

export { echarts }
export default echarts

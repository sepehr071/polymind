import { memo, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowUp, ArrowDown, ChevronsUpDown, Download } from 'lucide-react'
import { cn } from '../../../utils/cn'
import { fmtNumber, fmtCurrency } from '../../../utils/persianLocale'
import { toCsv, downloadCsv, downloadExcel } from '@/utils/exportCsv'
import { Card } from '../../ui/card'

/**
 * Data Analyzer table artifact.
 *
 * Headless @tanstack/react-table (sorting + core row model) feeding a
 * @tanstack/react-virtual windowed body — the MUI free DataGrid caps
 * virtualization at 100 rows, so we virtualize ourselves and never mount more
 * than the visible row span. Sticky sortable headers, horizontal scroll for
 * wide schemas, an internal max-height (the chat <pre> cap idiom) so a 10k-row
 * artifact can't blow out the reading column.
 *
 * Numeric cells format through the locale-aware helpers (digits follow the
 * user's numeral preference): `dtype` of `currency`/`money` → fmtCurrency,
 * int/float/number → fmtNumber. Everything else renders as a plain string. The
 * whole table is LTR-locked (`dir="ltr"`) — tabular data with numbers + Latin
 * column keys reorders wrong under RTL; we keep header/value alignment honest
 * with logical text-start.
 *
 * @param {Array<{ key:string, label:string, dtype:string }>} columns
 * @param {Array<Record<string, unknown>>} rows
 * @param {number} [total_rows]  full row count server-side (footer when > rows)
 * @param {string|null} [name]   optional table caption
 */

const NUMERIC_DTYPES = new Set([
  'int', 'int64', 'integer', 'float', 'float64', 'number', 'numeric', 'double', 'decimal',
])
const CURRENCY_DTYPES = new Set(['currency', 'money', 'usd'])

function isNumericDtype(dtype) {
  return NUMERIC_DTYPES.has(String(dtype || '').toLowerCase())
}
function isCurrencyDtype(dtype) {
  return CURRENCY_DTYPES.has(String(dtype || '').toLowerCase())
}

/** Render one cell value per its column dtype. */
function formatCell(value, dtype) {
  if (value == null || value === '') return ''
  if (isCurrencyDtype(dtype)) {
    const n = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(n) ? fmtCurrency(n) : String(value)
  }
  if (isNumericDtype(dtype)) {
    const n = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(n) ? fmtNumber(n) : String(value)
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const ROW_HEIGHT = 40

function DataTableBase({ columns, rows, total_rows, name = null }) {
  const { t } = useTranslation('chat')
  const [sorting, setSorting] = useState([])
  const scrollRef = useRef(null)

  const data = useMemo(() => (Array.isArray(rows) ? rows : []), [rows])

  const tableColumns = useMemo(() => {
    const helper = createColumnHelper()
    const cols = Array.isArray(columns) ? columns : []
    // react-table THROWS ("Columns require an id when using an accessorFn") when
    // an accessorFn column has a falsy or duplicate id. A table artifact can
    // carry an empty-string or duplicate column name (corr() / transpose /
    // describe() / joins), so derive a guaranteed non-empty, unique id — while
    // the accessor still reads the cell by its ORIGINAL key. Never let one bad
    // column crash the whole page.
    const usedIds = new Set()
    return cols.map((c, i) => {
      const rawKey = c?.key
      let id = (rawKey == null ? '' : String(rawKey)) || (c?.label ? String(c.label) : '') || `col_${i}`
      while (usedIds.has(id)) id = `${id}_${i}`
      usedIds.add(id)
      return helper.accessor((row) => row?.[rawKey], {
        id,
        header: c?.label || (rawKey != null && String(rawKey)) || id,
        // Numeric columns sort numerically; everything else falls back to the
        // default alphanumeric comparator.
        sortingFn: isNumericDtype(c?.dtype) || isCurrencyDtype(c?.dtype) ? 'basic' : 'auto',
        meta: { dtype: c?.dtype, numeric: isNumericDtype(c?.dtype) || isCurrencyDtype(c?.dtype) },
        cell: (info) => formatCell(info.getValue(), c?.dtype),
      })
    })
  }, [columns])

  const table = useReactTable({
    data,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  const { rows: modelRows } = table.getRowModel()

  const rowVirtualizer = useVirtualizer({
    count: modelRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  })
  const virtualRows = rowVirtualizer.getVirtualItems()
  const totalSize = rowVirtualizer.getTotalSize()
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0
  const paddingBottom =
    virtualRows.length > 0 ? totalSize - virtualRows[virtualRows.length - 1].end : 0

  const colCount = tableColumns.length
  const truncated = typeof total_rows === 'number' && total_rows > data.length

  // Export the FULL `rows` (not just the virtualized window). Columns map to
  // {key,label} so headers carry human labels.
  const exportCols = useMemo(
    () =>
      (Array.isArray(columns) ? columns : []).map((c) => ({
        key: c.key,
        label: c.label || c.key,
      })),
    [columns],
  )
  const handleExportCsv = () => {
    downloadCsv(toCsv(exportCols, data), name || 'table')
  }
  const handleExportExcel = () => {
    downloadExcel(exportCols, data, name || 'table')
  }

  if (colCount === 0) {
    return (
      <Card className="px-4 py-6 text-center text-sm text-foreground-tertiary">
        {t('dataAnalyzer.empty')}
      </Card>
    )
  }

  return (
    <figure className="my-1" dir="ltr">
      {/* Caption + export controls share one inline row (LTR-locked table). */}
      <div className="mb-1.5 flex items-center justify-between gap-2">
        {name ? (
          <figcaption className="text-xs font-medium text-foreground-secondary text-start">
            {name}
          </figcaption>
        ) : (
          <span aria-hidden="true" />
        )}
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={handleExportCsv}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-background-secondary/60 px-2 py-1 text-[11px] font-medium text-foreground-secondary transition-colors hover:bg-background-tertiary hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            <Download className="h-3 w-3" aria-hidden="true" />
            {t('dataAnalyzer.exportCsv')}
          </button>
          <button
            type="button"
            onClick={handleExportExcel}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-background-secondary/60 px-2 py-1 text-[11px] font-medium text-foreground-secondary transition-colors hover:bg-background-tertiary hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            <Download className="h-3 w-3" aria-hidden="true" />
            {t('dataAnalyzer.exportExcel')}
          </button>
        </div>
      </div>
      <Card className="overflow-hidden">
        <div
          ref={scrollRef}
          className="max-h-[420px] overflow-auto"
          // Native scrollbars; horizontal for wide schemas. Internal cap mirrors
          // the chat <pre> 55vh idiom so a tall artifact scrolls in place.
        >
          <table className="w-full border-collapse text-sm" style={{ tableLayout: 'auto' }}>
            <thead className="sticky top-0 z-10">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id} className="bg-background-secondary">
                  {headerGroup.headers.map((header) => {
                    const numeric = header.column.columnDef.meta?.numeric
                    const sorted = header.column.getIsSorted()
                    return (
                      <th
                        key={header.id}
                        scope="col"
                        aria-sort={
                          sorted === 'asc'
                            ? 'ascending'
                            : sorted === 'desc'
                              ? 'descending'
                              : 'none'
                        }
                        className={cn(
                          'border-b border-border px-3 py-2.5 text-[12px] font-bold text-foreground-secondary whitespace-nowrap',
                          numeric ? 'text-end' : 'text-start',
                        )}
                      >
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className={cn(
                            'inline-flex items-center gap-1 rounded transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/50',
                            numeric && 'flex-row-reverse',
                          )}
                          title={t('dataAnalyzer.sortBy', { name: String(header.column.columnDef.header) })}
                        >
                          <span>{flexRender(header.column.columnDef.header, header.getContext())}</span>
                          {sorted === 'asc' ? (
                            <ArrowUp className="h-3 w-3 text-accent" aria-hidden="true" />
                          ) : sorted === 'desc' ? (
                            <ArrowDown className="h-3 w-3 text-accent" aria-hidden="true" />
                          ) : (
                            <ChevronsUpDown
                              className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-40"
                              aria-hidden="true"
                            />
                          )}
                        </button>
                      </th>
                    )
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {paddingTop > 0 && (
                <tr aria-hidden="true">
                  <td colSpan={colCount} style={{ height: paddingTop, padding: 0, border: 0 }} />
                </tr>
              )}
              {virtualRows.map((virtualRow) => {
                const row = modelRows[virtualRow.index]
                return (
                  <tr
                    key={row.id}
                    data-index={virtualRow.index}
                    className="border-b border-border/60 transition-colors last:border-b-0 hover:bg-background-tertiary/50"
                    style={{ height: ROW_HEIGHT }}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const numeric = cell.column.columnDef.meta?.numeric
                      return (
                        <td
                          key={cell.id}
                          className={cn(
                            'px-3 py-2.5 text-[13px] text-foreground/90 align-middle',
                            numeric
                              ? 'text-end tabular-nums whitespace-nowrap'
                              : 'text-start max-w-[260px] truncate',
                          )}
                          title={numeric ? undefined : formatCell(cell.getValue(), cell.column.columnDef.meta?.dtype)}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
              {paddingBottom > 0 && (
                <tr aria-hidden="true">
                  <td colSpan={colCount} style={{ height: paddingBottom, padding: 0, border: 0 }} />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
      {truncated && (
        <figcaption className="mt-1.5 px-1 text-xs text-foreground-tertiary text-start">
          {t('dataAnalyzer.tableFooter', { n: fmtNumber(data.length), total: fmtNumber(total_rows) })}
        </figcaption>
      )}
    </figure>
  )
}

export const DataTable = memo(DataTableBase)
export default DataTable

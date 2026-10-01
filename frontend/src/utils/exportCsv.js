/**
 * CSV export for the analytics envelope. Flattens `series[]` and/or
 * `breakdown.{by_model,children}[]` into rows and triggers a client-side
 * download. No deps — builds the string, blobs it, clicks a transient anchor.
 *
 * Excel-safe: prefixes a UTF-8 BOM so Persian labels (and the localized header
 * row) don't mojibake on open. Values are RFC-4180 escaped (wrap in quotes when
 * they contain a comma / quote / newline; double embedded quotes). `null`
 * (masked cost) becomes an empty cell.
 *
 * CSV-injection safe: cells from uploaded data / model output can start with a
 * formula trigger (`= + - @`) or a leading tab/CR; Excel & Sheets would execute
 * those as live formulas (`=WEBSERVICE(...)` exfil, `=cmd|...`). We neutralize
 * by prefixing a single quote so the spreadsheet treats the cell as text.
 */

const BOM = '﻿'

// Leading chars a spreadsheet interprets as the start of a formula.
const FORMULA_TRIGGERS = /^[=+\-@\t\r]/

/** Escape a single cell per RFC 4180, neutralizing formula-injection triggers. */
function escapeCell(value) {
  if (value == null) return ''
  let str = String(value)
  // Defang formula triggers BEFORE quoting so the leading "'" survives the
  // RFC-4180 wrapping (applies to every exporter sharing this util).
  if (FORMULA_TRIGGERS.test(str)) {
    str = `'${str}`
  }
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}

/**
 * Build a CSV string from a header array + row objects.
 * @param {Array<{key:string,label:string}>} columns
 * @param {Array<object>} rows
 */
export function toCsv(columns, rows) {
  const header = columns.map((c) => escapeCell(c.label)).join(',')
  const body = rows
    .map((row) => columns.map((c) => escapeCell(row[c.key])).join(','))
    .join('\r\n')
  return `${header}\r\n${body}`
}

/** Trigger a browser download of `content` as `filename`. */
export function downloadCsv(content, filename) {
  const blob = new Blob([BOM, content], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // Revoke on the next tick so the click has a chance to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/**
 * Flatten an analytics envelope's time `series` to CSV and download.
 * Columns: bucket, cost, calls, tokens, active_users. `columns` defaults cover
 * the standard envelope; pass `labels` to localize the header row.
 *
 * @param {{series?: Array<object>}} envelope
 * @param {string} filename
 * @param {Object} [opts]
 * @param {Record<string,string>} [opts.labels]  key → localized header label
 */
export function exportSeriesCsv(envelope, filename, { labels = {} } = {}) {
  const series = Array.isArray(envelope?.series) ? envelope.series : []
  const columns = [
    { key: 'bucket', label: labels.bucket || 'bucket' },
    { key: 'cost', label: labels.cost || 'cost' },
    { key: 'calls', label: labels.calls || 'calls' },
    { key: 'tokens', label: labels.tokens || 'tokens' },
    { key: 'active_users', label: labels.active_users || 'active_users' },
  ]
  downloadCsv(toCsv(columns, series), filename)
}

/**
 * Flatten a breakdown list (`breakdown.children` or `breakdown.by_model`) to
 * CSV and download. Auto-detects the available columns from the first row so it
 * works for both children (id/label/cost/calls/tokens/active_users) and models
 * (key/label/cost/calls/tokens).
 *
 * @param {Array<object>} rows
 * @param {string} filename
 * @param {Object} [opts]
 * @param {Record<string,string>} [opts.labels]
 */
export function exportBreakdownCsv(rows, filename, { labels = {} } = {}) {
  const list = Array.isArray(rows) ? rows : []
  // Stable, human-meaningful column order; only keep keys present on the data.
  const ORDER = ['label', 'key', 'id', 'cost', 'calls', 'tokens', 'active_users', 'delta_pct']
  const present = new Set()
  for (const row of list) {
    for (const k of Object.keys(row || {})) present.add(k)
  }
  const columns = ORDER.filter((k) => present.has(k)).map((k) => ({
    key: k,
    label: labels[k] || k,
  }))
  downloadCsv(toCsv(columns, list), filename)
}

/**
 * Excel-compatible SpreadsheetML (no extra deps). Opens in Excel / LibreOffice
 * as a workbook. Extension ``.xls`` is intentional for this XML dialect.
 *
 * @param {Array<{key:string,label?:string}>} columns
 * @param {Array<object>} rows
 * @returns {string} XML document
 */
export function toExcelXml(columns, rows) {
  const cols = Array.isArray(columns) ? columns : []
  const data = Array.isArray(rows) ? rows : []
  const esc = (v) =>
    String(v ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')

  const cell = (value, type = 'String') =>
    `<Cell><Data ss:Type="${type}">${esc(value)}</Data></Cell>`

  const headerRow = `<Row>${cols.map((c) => cell(c.label || c.key)).join('')}</Row>`
  const bodyRows = data
    .map((row) => {
      const cells = cols.map((c) => {
        const raw = row?.[c.key]
        if (raw == null || raw === '') return cell('')
        if (typeof raw === 'number' && Number.isFinite(raw)) {
          return cell(raw, 'Number')
        }
        return cell(raw)
      })
      return `<Row>${cells.join('')}</Row>`
    })
    .join('')

  return (
    `<?xml version="1.0"?>\r\n` +
    `<?mso-application progid="Excel.Sheet"?>\r\n` +
    `<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" ` +
    `xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">\r\n` +
    `<Worksheet ss:Name="Sheet1"><Table>\r\n` +
    `${headerRow}\r\n${bodyRows}\r\n` +
    `</Table></Worksheet></Workbook>`
  )
}

/** Download table data as Excel-openable SpreadsheetML (``.xls``). */
export function downloadExcel(columns, rows, filename = 'table') {
  const xml = toExcelXml(columns, rows)
  const blob = new Blob([BOM, xml], { type: 'application/vnd.ms-excel;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const base = String(filename || 'table').replace(/\.xlsx?$/i, '')
  a.download = `${base}.xls`
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export default exportSeriesCsv

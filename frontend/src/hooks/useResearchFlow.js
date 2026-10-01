import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import { streamResearch, uploadResearchFile } from '@/services/researchService'
import { researchMessageText } from '@/utils/studioDlpText'

export const RESEARCH_STARTER_IDS = ['market', 'competitors', 'regulation', 'vendor']

/** @typedef {'idle'|'running'|'done'|'failed'} ResearchStage */

function sanitizeFilename(raw) {
  const s = String(raw || '')
    .replace(/[#*_`[\]|\\/<>:"?]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60)
  return s || 'research-report'
}

/** First markdown H1, else query snippet. */
export function reportDownloadBasename(report, query) {
  const md = String(report || '')
  const m = md.match(/^#\s+(.+)$/m)
  if (m?.[1]) return sanitizeFilename(m[1])
  return sanitizeFilename(query)
}

export default function useResearchFlow() {
  const { t } = useTranslation('research')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('deep')
  const [lang, setLang] = useState('fa')
  const [focus, setFocus] = useState('')
  const [files, setFiles] = useState([])
  const [report, setReport] = useState('')
  const [citations, setCitations] = useState([])
  const [meta, setMeta] = useState(null)
  /** @type {[ResearchStage, function]} */
  const [stage, setStage] = useState('idle')
  const [elapsedS, setElapsedS] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'research' })
  const streamRef = useRef(null)
  const runStartedRef = useRef(null)

  const running = stage === 'running'

  useEffect(() => () => streamRef.current?.abort(), [])

  useEffect(() => {
    if (!running) return undefined
    const tick = () => {
      if (runStartedRef.current != null) {
        setElapsedS(Math.floor((Date.now() - runStartedRef.current) / 1000))
      }
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [running])

  const applyStarter = useCallback((id) => {
    const key = RESEARCH_STARTER_IDS.includes(id) ? id : null
    if (!key) return
    setQuery(t(`starters.${key}.query`))
    setFocus(t(`starters.${key}.focus`))
    setError(null)
  }, [t])

  const addFiles = useCallback(async (fileList) => {
    const incoming = Array.from(fileList || []).slice(0, 5 - files.length)
    if (!incoming.length) return
    setUploading(true)
    try {
      const uploaded = []
      for (const f of incoming) {
        try {
          const row = await uploadResearchFile(f)
          const id = row?._id || row?.id
          if (id) uploaded.push({ upload_id: id, name: row.original_name || f.name })
        } catch {
          setError(t('errors.uploadFailed', { name: f.name }))
        }
      }
      if (uploaded.length) setFiles((p) => [...p, ...uploaded].slice(0, 5))
    } finally {
      setUploading(false)
    }
  }, [files.length, t])

  const run = useCallback(async () => {
    if (!query.trim() || stage === 'running') return
    setError(null)
    const attachments = files.map((f) => ({ upload_id: f.upload_id }))
    const dlp = await scan(researchMessageText(query, focus), attachments)
    if (dlp === null) return

    streamRef.current?.abort()
    setStage('running')
    setReport('')
    setCitations([])
    setMeta(null)
    setElapsedS(0)
    runStartedRef.current = Date.now()

    const body = {
      query: query.trim(),
      mode,
      lang,
      focus,
      upload_ids: files.map((f) => f.upload_id),
      workspace_id: workspaceId,
      dlp_confirmed: !!dlp?.confirmed,
      dlp_confirm_token: dlp?.confirm_token || undefined,
      dlp_redact: dlp?.redact || undefined,
    }
    streamRef.current = streamResearch(body, {
      onStatus: (p) => {
        // Heartbeats keep the stream alive; only use elapsed for the clock.
        if (typeof p?.elapsed_s === 'number') setElapsedS(p.elapsed_s)
      },
      onDelta: (p) => setReport((r) => r + (p.text || '')),
      onDone: (p) => {
        if (p?.report_md) setReport(p.report_md)
        setCitations(p?.citations || [])
        setMeta({
          model_id: p?.model_id,
          mode: p?.mode,
          elapsed_s: runStartedRef.current != null
            ? Math.floor((Date.now() - runStartedRef.current) / 1000)
            : undefined,
        })
        setStage('done')
        runStartedRef.current = null
      },
      onError: (e) => {
        if (handleBudgetError?.(e)) {
          setStage('failed')
          runStartedRef.current = null
          return
        }
        const raw = String(e?.error || e?.message || '')
        let msg = raw || t('errors.generic')
        if (/failed to fetch|networkerror|network error|load failed/i.test(raw)) {
          msg = t('errors.network')
        } else if (/stream timed out|timed?\s*out/i.test(raw)) {
          msg = t('errors.timeout')
        }
        setError(msg)
        setStage('failed')
        runStartedRef.current = null
      },
    })
  }, [query, focus, mode, lang, files, workspaceId, stage, scan, handleBudgetError, t])

  const retry = useCallback(() => {
    if (stage === 'running') return
    void run()
  }, [run, stage])

  const cancel = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    runStartedRef.current = null
    // Cancel with no report → idle; keep form filled
    setStage((s) => (s === 'running' ? 'idle' : s))
  }, [])

  const reset = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    runStartedRef.current = null
    setQuery('')
    setFocus('')
    setFiles([])
    setReport('')
    setCitations([])
    setMeta(null)
    setError(null)
    setElapsedS(0)
    setStage('idle')
  }, [])

  const downloadName = reportDownloadBasename(report, query)

  return {
    query, setQuery, mode, setMode, lang, setLang, focus, setFocus,
    files, setFiles, addFiles, applyStarter,
    report, citations, meta, stage, elapsedS,
    running, uploading, error, setError,
    run, retry, cancel, reset, downloadName,
    budgetModal, dlpModal,
  }
}

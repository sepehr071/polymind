import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import {
  OCR_MAX_FILES,
  isOcrFile,
  streamOcrExtract,
  uploadOcrFile,
  listOcrJobs,
  getOcrJob,
  deleteOcrJob,
} from '@/services/ocrService'

function resultsFromJob(job) {
  return (job?.files || []).map((f) => ({
    upload_id: f.upload_id,
    original_name: f.original_name,
    status: f.status || 'pending',
    content: f.content || null,
    error: f.error || null,
  }))
}

/**
 * OCR page state: upload chips + prompt + per-file results + persisted history.
 */
export default function useOcrFlow() {
  const { t } = useTranslation('ocr')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null
  const [params, setParams] = useSearchParams()

  const [files, setFiles] = useState([])
  const [prompt, setPrompt] = useState('')
  const [results, setResults] = useState([])
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [jobs, setJobs] = useState([])
  const [currentJobId, setCurrentJobId] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'ocr' })
  const streamRef = useRef(null)
  const currentJobIdRef = useRef(null)
  const runningRef = useRef(false)

  const setJobParam = useCallback(
    (id) => {
      if (id) setParams({ job: id }, { replace: true })
      else setParams({}, { replace: true })
    },
    [setParams],
  )

  const loadHistory = useCallback(async () => {
    try {
      const data = await listOcrJobs({ limit: 50 })
      setJobs(data.jobs || [])
    } catch {
      // rail is best-effort
    }
  }, [])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  useEffect(() => {
    return () => {
      streamRef.current?.abort()
    }
  }, [])

  const onErr = useCallback(
    (e) => {
      if (handleBudgetError?.(e)) return
      setError(e?.error || e?.message || t('errors.generic'))
    },
    [handleBudgetError, t],
  )

  const loadJob = useCallback(
    async (id) => {
      if (!id || runningRef.current) return
      setError(null)
      try {
        const rec = await getOcrJob(id)
        currentJobIdRef.current = rec._id
        setCurrentJobId(rec._id)
        setPrompt(rec.prompt || '')
        setResults(resultsFromJob(rec))
        setFiles([])
        setProgress(null)
        setJobParam(rec._id)
      } catch {
        setError(t('errors.loadFailed'))
      }
    },
    [setJobParam, t],
  )

  const newJob = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    runningRef.current = false
    currentJobIdRef.current = null
    setCurrentJobId(null)
    setFiles([])
    setPrompt('')
    setResults([])
    setProgress(null)
    setError(null)
    setRunning(false)
    setJobParam(null)
  }, [setJobParam])

  const removeJob = useCallback(
    async (id) => {
      try {
        await deleteOcrJob(id)
        setJobs((prev) => prev.filter((j) => j._id !== id))
        if (currentJobIdRef.current === id) newJob()
      } catch {
        setError(t('errors.generic'))
      }
    },
    [newJob, t],
  )

  useEffect(() => {
    const id = params.get('job')
    if (!id || id === currentJobIdRef.current || runningRef.current) return
    loadJob(id)
  }, [params, loadJob])

  const addFiles = useCallback(
    async (fileList) => {
      const incoming = Array.from(fileList || [])
      if (!incoming.length) return
      setError(null)

      const room = OCR_MAX_FILES - files.length
      if (room <= 0) {
        setError(t('errors.maxFiles', { count: OCR_MAX_FILES }))
        return
      }

      const accepted = []
      for (const f of incoming) {
        if (accepted.length >= room) break
        if (!isOcrFile(f)) {
          setError(t('errors.badType', { name: f.name }))
          continue
        }
        accepted.push(f)
      }
      if (!accepted.length) return

      setUploading(true)
      try {
        const uploaded = []
        for (const f of accepted) {
          try {
            const row = await uploadOcrFile(f)
            const id = row?._id || row?.id
            if (!id) throw new Error('no upload id')
            uploaded.push({
              upload_id: id,
              name: row.original_name || f.name,
              mime: row.mime_type || f.type,
              size: row.size ?? f.size,
            })
          } catch {
            setError(t('errors.uploadFailed', { name: f.name }))
          }
        }
        if (uploaded.length) {
          setFiles((prev) => [...prev, ...uploaded].slice(0, OCR_MAX_FILES))
        }
      } finally {
        setUploading(false)
      }
    },
    [files.length, t],
  )

  const removeFile = useCallback((uploadId) => {
    setFiles((prev) => prev.filter((f) => f.upload_id !== uploadId))
  }, [])

  const extract = useCallback(async () => {
    if (!files.length || running) return
    setError(null)

    const attachments = files.map((f) => ({ upload_id: f.upload_id }))
    const dlp = await scan(prompt || '', attachments)
    if (dlp === null) return

    streamRef.current?.abort()
    runningRef.current = true
    setRunning(true)
    setProgress({ done: 0, total: files.length })
    setResults(
      files.map((f) => ({
        upload_id: f.upload_id,
        original_name: f.name,
        status: 'pending',
        content: null,
        error: null,
      })),
    )

    const body = {
      upload_ids: files.map((f) => f.upload_id),
      prompt: prompt || '',
      workspace_id: workspaceId,
      dlp_confirmed: !!dlp?.confirmed,
      dlp_confirm_token: dlp?.confirm_token || undefined,
      dlp_redact: dlp?.redact || undefined,
    }

    streamRef.current = streamOcrExtract(body, {
      onStatus: (p) => {
        setProgress(p)
        if (p?.job_id && p.job_id !== currentJobIdRef.current) {
          currentJobIdRef.current = p.job_id
          setCurrentJobId(p.job_id)
          setJobParam(p.job_id)
        }
      },
      onFileResult: (p) => {
        setResults((prev) =>
          prev.map((r) =>
            r.upload_id === p.upload_id
              ? {
                  ...r,
                  status: 'ok',
                  content: p.content || '',
                  original_name: p.original_name || r.original_name,
                  error: null,
                }
              : r,
          ),
        )
      },
      onFileError: (p) => {
        setResults((prev) =>
          prev.map((r) =>
            r.upload_id === p.upload_id
              ? {
                  ...r,
                  status: 'error',
                  error: p.error || t('errors.extractFailed'),
                  original_name: p.original_name || r.original_name,
                }
              : r,
          ),
        )
      },
      onDone: () => {
        runningRef.current = false
        setRunning(false)
        setProgress(null)
        streamRef.current = null
        loadHistory()
      },
      onError: (e) => {
        onErr(e)
        runningRef.current = false
        setRunning(false)
        setProgress(null)
        streamRef.current = null
        loadHistory()
      },
    })
  }, [files, running, prompt, workspaceId, scan, onErr, t, setJobParam, loadHistory])

  const cancel = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    runningRef.current = false
    setRunning(false)
    setProgress(null)
    loadHistory()
  }, [loadHistory])

  const clearResults = useCallback(() => {
    setResults([])
    setError(null)
  }, [])

  return {
    files,
    prompt,
    setPrompt,
    results,
    running,
    progress,
    error,
    uploading,
    addFiles,
    removeFile,
    extract,
    cancel,
    clearResults,
    maxFiles: OCR_MAX_FILES,
    budgetModal,
    dlpModal,
    jobs,
    currentJobId,
    loadJob,
    newJob,
    removeJob,
  }
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import {
  CONTRACT_MAX_FILES,
  isContractFile,
  streamContractReview,
  uploadContractFile,
} from '@/services/contractService'

export default function useContractReviewFlow() {
  const { t } = useTranslation('contracts')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const [files, setFiles] = useState([])
  const [notes, setNotes] = useState('')
  const [lang, setLang] = useState('fa')
  const [result, setResult] = useState(null)
  const [status, setStatus] = useState(null)
  const [running, setRunning] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'contract' })
  const streamRef = useRef(null)
  useEffect(() => () => streamRef.current?.abort(), [])

  const addFiles = useCallback(async (fileList) => {
    const room = CONTRACT_MAX_FILES - files.length
    const incoming = Array.from(fileList || []).filter(isContractFile).slice(0, room)
    if (!incoming.length) return
    setUploading(true)
    try {
      const uploaded = []
      for (const f of incoming) {
        try {
          const row = await uploadContractFile(f)
          const id = row?._id || row?.id
          if (id) uploaded.push({ upload_id: id, name: row.original_name || f.name, size: f.size })
        } catch {
          setError(t('errors.uploadFailed'))
        }
      }
      if (uploaded.length) setFiles((p) => [...p, ...uploaded].slice(0, CONTRACT_MAX_FILES))
    } finally {
      setUploading(false)
    }
  }, [files.length, t])

  const replaceFile = useCallback(async (uploadId, file) => {
    if (!file || !isContractFile(file)) return
    setUploading(true)
    try {
      const row = await uploadContractFile(file)
      const id = row?._id || row?.id
      if (!id) return
      const next = { upload_id: id, name: row.original_name || file.name, size: file.size }
      setFiles((p) => p.map((x) => (x.upload_id === uploadId ? next : x)))
    } catch {
      setError(t('errors.uploadFailed'))
    } finally {
      setUploading(false)
    }
  }, [t])

  const run = useCallback(async () => {
    if (!files.length || running) return
    setError(null)
    // Message = raw notes (may be ''); uploads join server-side — never notes||' '.
    const attachments = files.map((f) => ({ upload_id: f.upload_id }))
    const dlp = await scan(notes || '', attachments)
    if (dlp === null) return

    streamRef.current?.abort()
    setRunning(true)
    setResult(null)
    const body = {
      upload_ids: files.map((f) => f.upload_id),
      notes,
      lang,
      workspace_id: workspaceId,
      dlp_confirmed: !!dlp?.confirmed,
      dlp_confirm_token: dlp?.confirm_token || undefined,
      dlp_redact: dlp?.redact || undefined,
    }
    streamRef.current = streamContractReview(body, {
      onStatus: setStatus,
      onResult: (p) => setResult(p),
      onDone: () => setRunning(false),
      onError: (e) => {
        if (handleBudgetError?.(e)) {
          setRunning(false)
          return
        }
        setError(e?.error || e?.message || t('errors.generic'))
        setRunning(false)
      },
    })
  }, [files, notes, lang, workspaceId, running, scan, handleBudgetError, t])

  return {
    files, setFiles, addFiles, replaceFile, notes, setNotes, lang, setLang,
    result, status, running, uploading, error, setError, run,
    maxFiles: CONTRACT_MAX_FILES, budgetModal, dlpModal,
  }
}

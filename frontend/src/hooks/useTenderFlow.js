import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import { hasFeature } from '@/utils/featureFlags'
import {
  TENDER_MAX_FILES,
  handoffPresentation,
  isTenderFile,
  streamTenderAnalyze,
  uploadTenderFile,
} from '@/services/tenderService'

export default function useTenderFlow() {
  const { t } = useTranslation('tenders')
  const { user } = useAuth()
  const navigate = useNavigate()
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const [mode, setMode] = useState('tender')
  const [currencyUnit, setCurrencyUnit] = useState('toman')
  const [lang, setLang] = useState('fa')
  const [files, setFiles] = useState([])
  const [notes, setNotes] = useState('')
  const [result, setResult] = useState(null)
  const [status, setStatus] = useState(null)
  const [running, setRunning] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'tender' })
  const streamRef = useRef(null)
  useEffect(() => () => streamRef.current?.abort(), [])

  const canHandoff = hasFeature(user, 'presentations')

  const addFiles = useCallback(async (fileList) => {
    const room = TENDER_MAX_FILES - files.length
    const incoming = Array.from(fileList || []).filter(isTenderFile).slice(0, room)
    if (!incoming.length) return
    setUploading(true)
    try {
      const uploaded = []
      for (const f of incoming) {
        try {
          const row = await uploadTenderFile(f)
          const id = row?._id || row?.id
          if (id) uploaded.push({ upload_id: id, name: row.original_name || f.name })
        } catch {
          setError(t('errors.uploadFailed'))
        }
      }
      if (uploaded.length) setFiles((p) => [...p, ...uploaded].slice(0, TENDER_MAX_FILES))
    } finally {
      setUploading(false)
    }
  }, [files.length, t])

  const run = useCallback(async () => {
    if (!files.length || running) return
    setError(null)
    const attachments = files.map((f) => ({ upload_id: f.upload_id }))
    const dlp = await scan(notes || '', attachments)
    if (dlp === null) return

    streamRef.current?.abort()
    setRunning(true)
    setResult(null)
    const body = {
      upload_ids: files.map((f) => f.upload_id),
      notes,
      mode,
      lang,
      currency_unit: currencyUnit,
      workspace_id: workspaceId,
      dlp_confirmed: !!dlp?.confirmed,
      dlp_confirm_token: dlp?.confirm_token || undefined,
      dlp_redact: dlp?.redact || undefined,
    }
    streamRef.current = streamTenderAnalyze(body, {
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
  }, [files, notes, mode, lang, currencyUnit, workspaceId, running, scan, handleBudgetError, t])

  const handoff = useCallback(async () => {
    if (!result || !canHandoff) return
    try {
      const data = await handoffPresentation({ result, lang, title: result.title })
      const hand = data?.handoff
      if (hand) {
        sessionStorage.setItem('presentation_brief_prefill', JSON.stringify(hand))
      }
      navigate(data?.path || '/presentations')
    } catch {
      setError(t('errors.handoffFailed'))
    }
  }, [result, canHandoff, lang, navigate, t])

  return {
    mode, setMode, currencyUnit, setCurrencyUnit, lang, setLang,
    files, setFiles, addFiles, notes, setNotes,
    result, status, running, uploading, error, setError, run,
    canHandoff, handoff, maxFiles: TENDER_MAX_FILES, budgetModal, dlpModal,
  }
}

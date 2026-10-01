import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import { isCvFile, streamCvCheck, uploadCvFile } from '@/services/cvCheckerService'
import { cvMessageText } from '@/utils/studioDlpText'

export default function useCvCheckerFlow() {
  const { t } = useTranslation('cvChecker')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const [mode, setMode] = useState('screen')
  const [lang, setLang] = useState('fa')
  const [cv, setCv] = useState(null) // {upload_id, name}
  const [jdFile, setJdFile] = useState(null)
  const [jdText, setJdText] = useState('')
  const [focus, setFocus] = useState('')
  const [result, setResult] = useState(null)
  const [status, setStatus] = useState(null)
  const [running, setRunning] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'cv_checker' })
  const streamRef = useRef(null)
  useEffect(() => () => streamRef.current?.abort(), [])

  const addCv = useCallback(async (file) => {
    if (!file || !isCvFile(file)) {
      setError(t('errors.badType'))
      return
    }
    setUploading(true)
    setError(null)
    try {
      const row = await uploadCvFile(file)
      const id = row?._id || row?.id
      if (!id) throw new Error('no id')
      setCv({ upload_id: id, name: row.original_name || file.name })
    } catch {
      setError(t('errors.uploadFailed'))
    } finally {
      setUploading(false)
    }
  }, [t])

  const addJdFile = useCallback(async (file) => {
    if (!file || !isCvFile(file)) {
      setError(t('errors.badType'))
      return
    }
    setUploading(true)
    try {
      const row = await uploadCvFile(file)
      const id = row?._id || row?.id
      if (!id) throw new Error('no id')
      setJdFile({ upload_id: id, name: row.original_name || file.name })
    } catch {
      setError(t('errors.uploadFailed'))
    } finally {
      setUploading(false)
    }
  }, [t])

  const run = useCallback(async () => {
    if (!cv || running) return
    setError(null)
    const attachments = [{ upload_id: cv.upload_id }]
    if (jdFile) attachments.push({ upload_id: jdFile.upload_id })
    const dlp = await scan(cvMessageText(focus, jdText), attachments)
    if (dlp === null) return

    streamRef.current?.abort()
    setRunning(true)
    setResult(null)
    setStatus({ phase: 'starting' })
    const body = {
      mode,
      lang,
      cv_upload_id: cv.upload_id,
      jd_text: jdText,
      jd_upload_id: jdFile?.upload_id || null,
      focus,
      workspace_id: workspaceId,
      dlp_confirmed: !!dlp?.confirmed,
      dlp_confirm_token: dlp?.confirm_token || undefined,
      dlp_redact: dlp?.redact || undefined,
    }
    streamRef.current = streamCvCheck(body, {
      onStatus: setStatus,
      onDone: (p) => {
        setResult(p)
        setRunning(false)
        setStatus(null)
      },
      onError: (e) => {
        if (handleBudgetError?.(e)) {
          setRunning(false)
          return
        }
        setError(e?.error || e?.message || t('errors.generic'))
        setRunning(false)
      },
    })
  }, [cv, jdFile, jdText, focus, mode, lang, workspaceId, running, scan, handleBudgetError, t])

  /** Keep JD + focus + mode/lang; clear CV + result for next candidate. */
  const screenAnother = useCallback(() => {
    streamRef.current?.abort()
    setCv(null)
    setResult(null)
    setStatus(null)
    setError(null)
    setRunning(false)
  }, [])

  const clearForm = useCallback(() => {
    streamRef.current?.abort()
    setCv(null)
    setJdFile(null)
    setJdText('')
    setFocus('')
    setResult(null)
    setStatus(null)
    setError(null)
    setRunning(false)
  }, [])

  return {
    mode, setMode, lang, setLang,
    cv, setCv, addCv, jdFile, setJdFile, addJdFile, jdText, setJdText, focus, setFocus,
    result, status, running, uploading, error, setError, run,
    screenAnother, clearForm,
    budgetModal, dlpModal,
  }
}

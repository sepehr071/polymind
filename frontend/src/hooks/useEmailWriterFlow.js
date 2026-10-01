import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import { EMAIL_TEMPLATES, streamEmailGenerate } from '@/services/emailWriterService'
import { emailWriterScanText } from '@/utils/studioDlpText'

const emptyFields = () => ({
  recipient: '',
  sender_name: '',
  sender_title: '',
  org: '',
  subject: '',
  points: '',
  prior_context: '',
  ref_number: '',
  date_shamsi: '',
  event_time: '',
  event_place: '',
  deadline: '',
  last_day: '',
  extra: '',
})

export default function useEmailWriterFlow() {
  const { t } = useTranslation('emailWriter')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const [templateId, setTemplateId] = useState('official_letter')
  const [fields, setFields] = useState(emptyFields)
  const [lang, setLang] = useState('fa')
  const [tone, setTone] = useState('formal')
  const [draft, setDraft] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'email_writer' })
  const streamRef = useRef(null)

  useEffect(() => () => streamRef.current?.abort(), [])

  const setField = useCallback((key, val) => {
    setFields((prev) => ({ ...prev, [key]: val }))
  }, [])

  const generate = useCallback(async () => {
    if (running) return
    setError(null)
    // Must match backend email_writer_scan_text (template:id + fields, \n\n).
    const scanText = emailWriterScanText(templateId, fields)
    const dlp = await scan(scanText || '[email_writer]')
    if (dlp === null) return

    streamRef.current?.abort()
    setRunning(true)
    setDraft('')
    const body = {
      template_id: templateId,
      fields,
      lang,
      tone,
      workspace_id: workspaceId,
      dlp_confirmed: !!dlp?.confirmed,
      dlp_confirm_token: dlp?.confirm_token || undefined,
      dlp_redact: dlp?.redact || undefined,
    }
    streamRef.current = streamEmailGenerate(body, {
      onToken: (p) => setDraft((d) => d + (p.text || '')),
      onDone: (p) => {
        if (p?.content) setDraft(p.content)
        setRunning(false)
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
  }, [running, templateId, fields, lang, tone, workspaceId, scan, handleBudgetError, t])

  return {
    templates: EMAIL_TEMPLATES,
    templateId,
    setTemplateId,
    fields,
    setField,
    lang,
    setLang,
    tone,
    setTone,
    draft,
    setDraft,
    running,
    error,
    setError,
    generate,
    budgetModal,
    dlpModal,
  }
}

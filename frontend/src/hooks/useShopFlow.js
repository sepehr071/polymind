import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import { streamShop } from '@/services/shopService'
import { shopMessageText } from '@/utils/studioDlpText'

export const SHOP_PIPELINE = ['planning', 'searching', 'comparing', 'done']

export default function useShopFlow() {
  const { t } = useTranslation('shop')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const [need, setNeed] = useState('')
  const [qty, setQty] = useState(1)
  const [maxBudget, setMaxBudget] = useState('')
  const [category, setCategory] = useState('auto')
  const [notes, setNotes] = useState('')
  const [lang, setLang] = useState('fa')

  const [result, setResult] = useState(null)
  const [plan, setPlan] = useState(null)
  const [liveCandidates, setLiveCandidates] = useState([])
  const [status, setStatus] = useState(null)
  const [activity, setActivity] = useState([])
  const [elapsedS, setElapsedS] = useState(0)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan, dlpModal } = useDlpConfirm({ source: 'shop' })
  const streamRef = useRef(null)
  const runStartedRef = useRef(null)

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

  const cancel = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    setRunning(false)
  }, [])

  const run = useCallback(async () => {
    if (!need.trim() || running) return
    setError(null)

    const qtyN = Math.max(1, Math.min(9999, Number(qty) || 1))
    let budgetVal = null
    if (String(maxBudget).trim() !== '') {
      const n = Number(String(maxBudget).replace(/[^\d]/g, ''))
      if (Number.isFinite(n) && n > 0) budgetVal = Math.floor(n)
    }

    const dlp = await scan(shopMessageText(need, qtyN, budgetVal, notes) || '[shop]')
    if (dlp === null) return

    streamRef.current?.abort()
    setRunning(true)
    setResult(null)
    setPlan(null)
    setLiveCandidates([])
    setActivity([])
    setElapsedS(0)
    runStartedRef.current = Date.now()
    setStatus({ phase: 'planning', message_key: 'planning', elapsed_s: 0 })
    setActivity([{ id: 0, phase: 'planning', at: Date.now() }])

    const body = {
      need: need.trim(),
      qty: qtyN,
      max_budget_toman: budgetVal,
      category,
      lang,
      notes: notes.trim() || undefined,
      workspace_id: workspaceId,
      dlp_confirmed: !!dlp?.confirmed,
      dlp_confirm_token: dlp?.confirm_token || undefined,
      dlp_redact: dlp?.redact || undefined,
    }

    streamRef.current = streamShop(body, {
      onStatus: (p) => {
        setStatus(p)
        if (typeof p?.elapsed_s === 'number') setElapsedS(p.elapsed_s)
        if (p?.heartbeat) return
        const phase = p?.phase || p?.message_key
        if (!phase || phase === 'done') return
        setActivity((prev) => {
          if (prev.length && prev[prev.length - 1].phase === phase) return prev
          return [...prev, { id: prev.length, phase, at: Date.now(), elapsed_s: p.elapsed_s }]
        })
      },
      onPlan: (p) => {
        setPlan(p)
      },
      onCandidates: (p) => {
        const items = Array.isArray(p?.items) ? p.items : []
        if (!items.length) return
        setLiveCandidates((prev) => {
          const seen = new Set(prev.map((c) => c.url))
          const next = [...prev]
          for (const c of items) {
            if (c?.url && !seen.has(c.url)) {
              seen.add(c.url)
              next.push(c)
            }
          }
          return next
        })
      },
      onDone: (pack) => {
        setResult(pack || null)
        setRunning(false)
        setStatus((s) => ({ ...(s || {}), phase: 'done', message_key: 'done' }))
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
  }, [
    need, qty, maxBudget, category, lang, notes, workspaceId,
    running, scan, handleBudgetError, t,
  ])

  return {
    need, setNeed,
    qty, setQty,
    maxBudget, setMaxBudget,
    category, setCategory,
    notes, setNotes,
    lang, setLang,
    result, plan, liveCandidates,
    status, activity, elapsedS,
    running, error, setError,
    run, cancel,
    budgetModal, dlpModal,
  }
}

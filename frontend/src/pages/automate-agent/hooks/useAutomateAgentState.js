import { useState, useCallback, useRef, useEffect } from 'react'
import { automateAgentService } from '../../../services/automateAgentService'
import { streamAutomateTask } from '../../../services/streamService'
import { DEFAULT_BROWSER_USE_MODEL } from '../../../constants/models'
import toast from 'react-hot-toast'
import i18n from '../../../i18n'

export function useAutomateAgentState({ onBudgetError } = {}) {
  const [currentTask, setCurrentTask]     = useState(null)
  const [status, setStatus]               = useState('idle') // idle|pending|running|completed|error|stopped|timed_out
  const [liveUrl, setLiveUrl]             = useState(null)
  const [messages, setMessages]           = useState([])
  const [taskHistory, setTaskHistory]     = useState([])
  const [selectedModel, setSelectedModel] = useState(DEFAULT_BROWSER_USE_MODEL)
  const [taskInput, setTaskInput]         = useState('')
  const [error, setError]                 = useState(null)

  const abortControllerRef = useRef(null)
  const liveUrlRetryTimer = useRef(null)

  const loadHistory = useCallback(async () => {
    try {
      const data = await automateAgentService.listTasks({ limit: 50, skip: 0 })
      setTaskHistory(data.tasks || [])
    } catch (err) {
      // Non-critical — silently fail on history load
    }
  }, [])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  // Cleanup retry timer on unmount
  useEffect(() => {
    return () => {
      if (liveUrlRetryTimer.current) clearTimeout(liveUrlRetryTimer.current)
    }
  }, [])

  const runTask = useCallback(async ({ dlpConfirmed = false, dlpConfirmToken = null } = {}) => {
    if (!taskInput.trim()) return

    setStatus('pending')
    setError(null)
    setMessages([])
    setLiveUrl(null)
    setCurrentTask(null)

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      await streamAutomateTask({
        task: taskInput.trim(),
        model: selectedModel,
        dlp_confirmed: dlpConfirmed || undefined,
        dlp_confirm_token: dlpConfirmToken || undefined,
        signal: controller.signal,
        onTaskStarted: (data) => {
          setStatus('running')
          setLiveUrl(data.live_url || null)
          setCurrentTask({
            _id: data.task_id,
            session_id: data.session_id,
            task_text: taskInput.trim(),
            model: data.model,
            status: 'running',
          })

          // If live_url wasn't in the initial event, poll once after 3s
          if (!data.live_url) {
            if (liveUrlRetryTimer.current) clearTimeout(liveUrlRetryTimer.current)
            liveUrlRetryTimer.current = setTimeout(async () => {
              try {
                const resp = await automateAgentService.getTask(data.task_id)
                if (resp?.task?.live_url) {
                  setLiveUrl((prev) => prev || resp.task.live_url)
                }
              } catch {
                // Best-effort — swallow
              }
            }, 3000)
          }
        },
        onMessage: (data) => {
          setMessages((prev) => {
            // Warn user if approaching expensive territory
            if (prev.length === 50) {
              toast(i18n.t('common:runtime.automate.costWarning'), { icon: '⚠️' })
            }
            return [...prev, data]
          })
        },
        onStatusChange: (data) => {
          setStatus(data.status)
          setCurrentTask((prev) => prev ? { ...prev, status: data.status } : prev)
        },
        onComplete: (data) => {
          setStatus('completed')
          setCurrentTask((prev) => prev ? { ...prev, status: 'completed', output: data.output } : prev)
          loadHistory()
        },
        onError: (data) => {
          // Budget/credit ceiling reached (402) — hard block, no resend.
          // Forward to the page's useBudgetBlock modal; suppress the generic
          // error toast/banner so only the budget modal shows.
          if (onBudgetError?.(data)) {
            setStatus('idle')
            return
          }
          setStatus('error')
          setError(data.message || 'An error occurred')
          toast.error(data.message || i18n.t('common:runtime.automate.taskFailed'))
        },
      })
    } catch (err) {
      if (err.name !== 'AbortError') {
        setStatus('error')
        setError(err.message)
      }
    } finally {
      abortControllerRef.current = null
    }
  }, [taskInput, selectedModel, loadHistory, onBudgetError])

  const stopTask = useCallback(async () => {
    // Abort the SSE stream first for immediate UI feedback
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    if (currentTask?._id) {
      try {
        await automateAgentService.stopTask(currentTask._id)
      } catch (err) {
        // Best-effort — stream already aborted
      }
    }

    setStatus('stopped')
    loadHistory()
  }, [currentTask, loadHistory])

  const loadTask = useCallback(async (taskId) => {
    try {
      const data = await automateAgentService.getTask(taskId)
      const { task, messages: msgs } = data
      setCurrentTask(task)
      setStatus(task.status)
      setLiveUrl(task.live_url || null)
      setMessages(msgs || [])
      setError(task.error || null)
    } catch (err) {
      toast.error(i18n.t('common:runtime.automate.loadTaskFailed'))
    }
  }, [])

  const deleteTask = useCallback(async (taskId) => {
    try {
      await automateAgentService.deleteTask(taskId)
      if (currentTask?._id === taskId) {
        newTask()
      }
      await loadHistory()
    } catch (err) {
      toast.error(i18n.t('common:runtime.automate.deleteTaskFailed'))
    }
  }, [currentTask, loadHistory])

  const newTask = useCallback(() => {
    // Abort any running stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    if (liveUrlRetryTimer.current) {
      clearTimeout(liveUrlRetryTimer.current)
      liveUrlRetryTimer.current = null
    }
    setCurrentTask(null)
    setStatus('idle')
    setLiveUrl(null)
    setMessages([])
    setError(null)
    setTaskInput('')
  }, [])

  return {
    currentTask,
    status,
    liveUrl,
    messages,
    taskHistory,
    selectedModel,
    taskInput,
    error,
    setSelectedModel,
    setTaskInput,
    runTask,
    stopTask,
    loadTask,
    deleteTask,
    loadHistory,
    newTask,
  }
}

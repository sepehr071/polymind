import { useState, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { LayoutGrid, Plus, Send, Square, X } from 'lucide-react'
import { streamArena, cancelArena } from '../../services/streamService'
import { arenaService } from '../../services/arenaService'
import ArenaPanel from '../../components/arena/ArenaPanel'
import ArenaConfigSelector from '../../components/arena/ArenaConfigSelector'
import HeaderSlot from '../../components/layout/HeaderSlot'
import PageHeader from '../../components/layout/PageHeader'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { cn } from '../../utils/cn'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import ModelLogo from '../../components/chat/ModelLogo'
import { Card } from '@/components/ui/card'
import { useDlpConfirm } from '../../hooks/useDlpConfirm'
import { useBudgetBlock } from '../../hooks/useBudgetBlock'

export default function ArenaPage() {
  const { t } = useTranslation('arena')
  const [showSelector, setShowSelector] = useState(false)
  const [configs, setConfigs] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState({})
  const [streaming, setStreaming] = useState({})
  const [loading, setLoading] = useState({})
  const [input, setInput] = useState('')

  // Ref to store abort controller for cancellation
  const abortControllerRef = useRef(null)

  // DLP pre-flight + violation modal (workspace Content Safety policy).
  const { scan: dlpScan, dlpModal } = useDlpConfirm({ source: 'arena' })
  // Budget/credit 402 catcher (hard block — no "send anyway").
  const { handleBudgetError, budgetModal } = useBudgetBlock()

  const handleSelectConfigs = (selectedConfigs) => {
    setConfigs(selectedConfigs)
    setMessages({})
    setStreaming({})
    setLoading({})
    setSessionId(null)
  }

  const handleSendMessage = useCallback(async () => {
    if (!input.trim() || configs.length < 2) return

    const configIds = configs.map(c => c._id)
    const messageContent = input

    // Pre-flight DLP scan. `decision` is:
    //   - `{ confirmed: false }` for allow / warn
    //   - `{ confirmed: true }`  after "Send anyway" on require_confirm
    //   - `null`                 for block / modify / close
    const decision = await dlpScan(messageContent)
    if (decision === null) {
      // User cancelled or content was blocked — keep input intact so they can edit.
      return
    }

    // Set loading for all configs
    const newLoading = {}
    configs.forEach(c => { newLoading[c._id] = true })
    setLoading(newLoading)

    // Clear input immediately
    setInput('')

    // Create abort controller for this stream
    const controller = new AbortController()
    abortControllerRef.current = controller

    const runStream = async (confirmed) => {
      await streamArena(
        {
          session_id: sessionId,
          message: messageContent,
          config_ids: configIds,
          dlp_confirmed: confirmed || undefined,
          dlp_confirm_token: decision.confirm_token || undefined,
        },
        {
          onSessionCreated: (data) => {
            setSessionId(data.session._id)
          },
          onUserMessage: (data) => {
            // User message is shared across all panels
            setMessages(prev => {
              const newMessages = { ...prev }
              configIds.forEach(configId => {
                // Check for duplicates
                const existingMessages = prev[configId] || []
                const isDuplicate = existingMessages.some(
                  m => m.role === 'user' && m.content === data.message.content
                )
                if (!isDuplicate) {
                  newMessages[configId] = [...existingMessages, { role: 'user', content: data.message.content }]
                }
              })
              return newMessages
            })
          },
          onMessageStart: (data) => {
            setLoading(prev => ({ ...prev, [data.config_id]: true }))
            setStreaming(prev => ({ ...prev, [data.config_id]: '' }))
          },
          onMessageChunk: (data) => {
            setStreaming(prev => ({
              ...prev,
              [data.config_id]: (prev[data.config_id] || '') + data.content
            }))
          },
          onMessageComplete: (data) => {
            setLoading(prev => ({ ...prev, [data.config_id]: false }))
            setStreaming(prev => ({ ...prev, [data.config_id]: null }))
            setMessages(prev => ({
              ...prev,
              [data.config_id]: [...(prev[data.config_id] || []), { role: 'assistant', content: data.content }]
            }))
          },
          onMessageError: async (data) => {
            const errText = data?.error || data?.message || 'Arena stream failed'
            const resetAll = () => {
              const resetLoading = {}
              configs.forEach(c => { resetLoading[c._id] = false })
              setLoading(resetLoading)
              setStreaming({})
            }
            // Budget/credit ceiling reached (402) — hard block, no resend.
            // Restore the input + clear loading exactly like the DLP branch.
            if (handleBudgetError(data)) {
              resetAll()
              setInput(messageContent)
              return
            }
            // Defence-in-depth: backend rejected with a DLP code even though
            // pre-flight let us through (race / pre-flight skipped). Restore
            // the input and let the standard pre-flight path resurface.
            if (data?.code === 'dlp_blocked' || data?.code === 'dlp_confirm_required') {
              resetAll()
              setInput(messageContent)
              toast.error(errText)
              return
            }
            if (!data?.config_id) {
              resetAll()
              toast.error(errText)
              return
            }
            setLoading(prev => ({ ...prev, [data.config_id]: false }))
            setStreaming(prev => ({ ...prev, [data.config_id]: null }))
            toast.error(errText)
          }
        },
        controller.signal
      )
    }

    try {
      await runStream(decision.confirmed)
    } catch (error) {
      // Stop button aborted the stream — not a failure, stay quiet.
      if (error.name !== 'AbortError') {
        console.error('Arena stream error:', error)
        toast.error(error.message || 'Arena stream failed')
      }
    } finally {
      // Stream ended (success, error, idle-timeout abort, or Stop). Never leave
      // the four panels spinning because a frame lacked config_id.
      const resetLoading = {}
      configs.forEach(c => { resetLoading[c._id] = false })
      setLoading(resetLoading)
    }
  }, [input, configs, sessionId, dlpScan, handleBudgetError])

  const handleStopGeneration = useCallback(async () => {
    // First try to abort the fetch request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    // Also call cancel endpoint if we have a session ID
    if (sessionId) {
      try {
        await cancelArena(sessionId)
      } catch (error) {
        console.error('Cancel error:', error)
      }
    }

    // Reset loading states
    const resetLoading = {}
    configs.forEach(c => { resetLoading[c._id] = false })
    setLoading(resetLoading)

    // Clear streaming content
    const resetStreaming = {}
    configs.forEach(c => { resetStreaming[c._id] = null })
    setStreaming(resetStreaming)
  }, [sessionId, configs])

  const handleRemoveConfig = async (configId) => {
    if (configs.length <= 2) {
      toast.error(t('error_min_configs'))
      return
    }
    const nextConfigs = configs.filter(c => c._id !== configId)
    setConfigs(nextConfigs)
    setMessages(prev => {
      const newMessages = { ...prev }
      delete newMessages[configId]
      return newMessages
    })
    // P2.12 — keep backend session.config_ids in sync so history reload
    // doesn't resurrect the removed panel.
    if (sessionId) {
      try {
        await arenaService.updateSession(sessionId, {
          config_ids: nextConfigs.map(c => c._id),
        })
      } catch (err) {
        console.error('Arena removeConfig sync failed:', err)
      }
    }
  }

  const isAnyLoading = Object.values(loading).some(Boolean)

  return (
    <div className="h-full flex flex-col">
      {/* Primary action lives in the global top bar (no second glass band). */}
      <HeaderSlot side="end">
        <Button onClick={() => setShowSelector(true)} size="sm" className="shrink-0">
          <Plus className="h-4 w-4 me-2" />
          {configs.length > 0 ? t('change_configs') : t('select_configs')}
        </Button>
      </HeaderSlot>

      {/* In-flow PageHeader (canonical IconTile + 19px title) — the AppTopBar is
          the only glass header; the config chips ride as a sub-row. */}
      <div className="flex-shrink-0 p-4 md:p-6 border-b border-border space-y-3">
        <PageHeader
          icon={LayoutGrid}
          title={t('title')}
          subtitle={t('subtitle')}
          actions={<PrivacyBadge mode="cloud" />}
        >
          {configs.length > 0 && (
            <div className="flex gap-2 mt-4 flex-wrap" data-testid="config-chips">
              {configs.map(config => (
                <Badge
                  key={config._id}
                  variant="secondary"
                  className="flex items-center gap-2 px-3 py-1.5"
                >
                  {config.avatar?.type === 'logo' ? (
                    <ModelLogo logo={config.avatar.value} modelId={config.model_id} size={14} />
                  ) : (
                    <span>{config.avatar?.value || '🤖'}</span>
                  )}
                  <span className="text-sm">{config.name}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRemoveConfig(config._id)}
                    className="h-5 w-5 p-0 ms-1"
                  >
                    <X className="h-3 w-3 text-foreground-tertiary" />
                  </Button>
                </Badge>
              ))}
            </div>
          )}
        </PageHeader>
        <PrivacyBanner mode="cloud" />
      </div>

      {/* Arena Grid */}
      <div className="flex-1 overflow-hidden p-4 md:p-6">
        {configs.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <Card className="text-center px-8 py-10 max-w-md">
              <LayoutGrid className="h-16 w-16 mx-auto mb-4 text-foreground-tertiary opacity-50" />
              <h2 className="text-xl font-medium text-foreground mb-2">{t('empty_title')}</h2>
              <p className="text-foreground-secondary mb-4">{t('empty_hint')}</p>
              <Button
                onClick={() => setShowSelector(true)}
              >
                <Plus className="h-4 w-4 me-2" />
                {t('select_configs')}
              </Button>
            </Card>
          </div>
        ) : (
          <div
            className={cn(
              // Wrapped rows SCROLL (never clip) — panels are h-full, so when the
              // auto-fit track wraps on narrow widths the extra rows must be
              // reachable. overflow-hidden here silently clipped them.
              'grid gap-3 md:gap-4 h-full overflow-y-auto',
              // Auto-fit: each panel claims >= min(100%, 320px) so >=2 columns
              // appear from md up (~720px content fits two 320 tracks), spreading
              // ALL panels across the freed (sidebar-less) viewport instead of
              // clustering centered. Single col below 320px.
              'grid-cols-1',
              configs.length === 2 &&
                'md:[grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))]',
              configs.length === 3 &&
                'md:[grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))] xl:grid-cols-3',
              // 4 configs: spread to a true 4-up row on xl, auto-fit between.
              configs.length === 4 &&
                'sm:[grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))] xl:grid-cols-4'
            )}
            data-testid="arena-grid"
          >
            {configs.map(config => (
              <div key={config._id} className="h-[70vh] md:h-full min-h-0">
                <ArenaPanel
                  config={config}
                  messages={messages[config._id] || []}
                  streaming={streaming[config._id]}
                  isLoading={loading[config._id]}
                  sessionId={sessionId}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Input — flat composer surface (glass is reserved for the top bar). */}
      {configs.length >= 2 && (
        <div className="flex-shrink-0 p-4 border-t border-border bg-background shadow-[0_-1px_2px_-1px_rgb(15_23_42_/_0.08)]">
          <div className="flex gap-3">
            <Input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
              placeholder={t('input_placeholder')}
              className="flex-1"
              disabled={isAnyLoading}
            />
            {isAnyLoading ? (
              <Button
                onClick={handleStopGeneration}
                variant="secondary"
              >
                <Square className="h-5 w-5" />
              </Button>
            ) : (
              <Button
                onClick={handleSendMessage}
                disabled={!input.trim()}
              >
                <Send className="h-5 w-5 rtl:-scale-x-100" />
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Config Selector Modal */}
      {showSelector && (
        <ArenaConfigSelector
          selectedConfigs={configs}
          onSelect={handleSelectConfigs}
          onClose={() => setShowSelector(false)}
          maxConfigs={4}
        />
      )}

      {/* DLP violation modal */}
      {dlpModal}
      {/* Budget/credit exceeded modal */}
      {budgetModal}
    </div>
  )
}

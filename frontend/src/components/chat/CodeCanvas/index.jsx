import { useState, useCallback, useEffect, useRef, memo } from 'react'
import { useTranslation } from 'react-i18next'
import { Play, RotateCcw, ChevronUp, ChevronDown, ExternalLink } from 'lucide-react'
import { Panel, Group, Separator, usePanelRef } from 'react-resizable-panels'
import CodeEditor from './CodeEditor'
import CodePreview, { buildPreviewDoc } from './CodePreview'
import ConsolePanel from './ConsolePanel'

// Minimal HTML-attribute escape for embedding a full document in srcdoc="…".
const escapeAttr = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;')

/**
 * Main CodeCanvas component with tabbed editor, live preview, and console
 */
const CodeCanvas = memo(function CodeCanvas({
  initialCode = { html: '', css: '', js: '' }
}) {
  const { t } = useTranslation('chat')
  // Code state
  const [code, setCode] = useState(initialCode)
  const [activeTab, setActiveTab] = useState('html')

  // Preview state (debounced)
  const [previewCode, setPreviewCode] = useState(initialCode)
  const debounceRef = useRef(null)

  // Console state
  const [logs, setLogs] = useState([])
  const [errors, setErrors] = useState([])

  // Track if code has been modified
  const [isModified, setIsModified] = useState(false)

  // Editor panel state for collapse/expand (using v4 API)
  const editorPanelRef = usePanelRef()
  const [isEditorCollapsed, setIsEditorCollapsed] = useState(false)

  // Tabs configuration
  const tabs = [
    { id: 'html', label: 'HTML' },
    { id: 'css', label: 'CSS' },
    { id: 'js', label: 'JS' }
  ]

  // Auto-detect which tab should be active based on initial code
  useEffect(() => {
    if (initialCode.html) {
      setActiveTab('html')
    } else if (initialCode.css) {
      setActiveTab('css')
    } else if (initialCode.js) {
      setActiveTab('js')
    }
  }, [])

  // Debounced preview update (500ms after typing stops)
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }
    debounceRef.current = setTimeout(() => {
      setPreviewCode(code)
      // Clear previous errors when code changes
      setErrors([])
    }, 500)

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [code])

  // Handle code change for a specific tab
  const handleCodeChange = useCallback((tab, value) => {
    setCode(prev => ({
      ...prev,
      [tab]: value
    }))
    setIsModified(true)
  }, [])

  // Handle manual run button
  const handleRun = useCallback(() => {
    setPreviewCode(code)
    setErrors([])
    setLogs([])
  }, [code])

  // Handle reset to original code
  const handleReset = useCallback(() => {
    setCode(initialCode)
    setPreviewCode(initialCode)
    setIsModified(false)
    setLogs([])
    setErrors([])
  }, [initialCode])

  // Handle console output from preview
  const handleConsole = useCallback((entry) => {
    setLogs(prev => [...prev, entry])
  }, [])

  // Handle errors from preview
  const handleError = useCallback((error) => {
    setErrors(prev => [...prev, error])
  }, [])

  // Clear console
  const handleClearConsole = useCallback(() => {
    setLogs([])
    setErrors([])
  }, [])

  // Open the CURRENT preview fullscreen in a new tab. The new tab gets a tiny
  // same-origin wrapper page (our markup only) hosting a full-viewport iframe
  // with the exact same sandbox="allow-scripts" srcdoc the inline preview uses
  // — user code stays confined (NO allow-same-origin, per CLAUDE.md), it just
  // gets the whole screen. Must run in the click handler so popup blockers
  // treat it as a user gesture.
  const handleOpenNewTab = useCallback(() => {
    const doc = buildPreviewDoc(code)
    const win = window.open('', '_blank')
    if (!win) return // popup blocked
    win.document.write(
      `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${t('codeCanvas.title')}</title>` +
      '<style>html,body{margin:0;height:100%;background:#fff}iframe{border:0;width:100%;height:100%;display:block}</style>' +
      `</head><body><iframe sandbox="allow-scripts" srcdoc="${escapeAttr(doc)}"></iframe></body></html>`
    )
    win.document.close()
  }, [code, t])

  // Ctrl/Cmd+Enter → Run. Capture phase so it fires BEFORE CodeMirror's own
  // keymap (which otherwise swallows Enter combos inside the editor) — leaner
  // than threading a CM keymap extension through CodeEditor.
  const handleKeyDownCapture = useCallback((e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      e.stopPropagation()
      handleRun()
    }
  }, [handleRun])

  // Toggle editor collapse/expand
  const toggleEditorCollapse = useCallback(() => {
    const panel = editorPanelRef.current
    if (panel) {
      if (panel.isCollapsed()) {
        panel.expand()
        setIsEditorCollapsed(false)
      } else {
        panel.collapse()
        setIsEditorCollapsed(true)
      }
    }
  }, [])

  return (
    <div className="h-full flex flex-col bg-background overflow-hidden" onKeyDownCapture={handleKeyDownCapture}>
      {/* Header with tabs and actions. flex-wrap + min-w-0 keep it from
          overflowing the mobile fixed-overlay (text labels hide below md). */}
      <div className="flex flex-wrap items-center justify-between gap-y-1 border-b border-border bg-background-secondary px-2 py-1.5">
        {/* Tabs */}
        <div className="flex items-center gap-1">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1.5 text-sm font-medium rounded transition-colors ${
                activeTab === tab.id
                  ? 'bg-accent text-accent-foreground'
                  : 'text-foreground-secondary hover:text-foreground hover:bg-background-tertiary'
              }`}
            >
              {tab.label}
              {code[tab.id] && (
                <span className="ms-1.5 w-1.5 h-1.5 rounded-full bg-current inline-block opacity-50" />
              )}
            </button>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1">
          <button
            onClick={handleOpenNewTab}
            className="flex items-center gap-1.5 px-2 py-1.5 text-sm text-foreground-secondary hover:text-foreground hover:bg-background-tertiary rounded transition-colors"
            title={t('codeCanvas.openNewTab')}
            aria-label={t('codeCanvas.openNewTab')}
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={toggleEditorCollapse}
            className="flex items-center gap-1.5 px-2 py-1.5 text-sm text-foreground-secondary hover:text-foreground hover:bg-background-tertiary rounded transition-colors"
            title={isEditorCollapsed ? t('codeCanvas.expandEditor') : t('codeCanvas.collapseEditor')}
          >
            {isEditorCollapsed ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronUp className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            onClick={handleRun}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-medium text-white bg-success hover:bg-success/90 rounded transition-colors"
            title={t('codeCanvas.runTitle')}
          >
            <Play className="h-3.5 w-3.5" />
            <span className="hidden md:inline">{t('codeCanvas.run')}</span>
          </button>
          {isModified && (
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm text-foreground-secondary hover:text-foreground hover:bg-background-tertiary rounded transition-colors"
              title={t('codeCanvas.resetTitle')}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span className="hidden md:inline">{t('codeCanvas.reset')}</span>
            </button>
          )}
        </div>
      </div>

      {/* Main content - Resizable Editor and Preview */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <Group orientation="vertical">
          {/* Editor Panel - Collapsible */}
          <Panel
            panelRef={editorPanelRef}
            collapsible
            collapsedSize={0}
            minSize={15}
            defaultSize={50}
          >
            <div className="h-full overflow-hidden">
              <CodeEditor
                value={code[activeTab] || ''}
                language={activeTab}
                onChange={(value) => handleCodeChange(activeTab, value)}
                height="100%"
              />
            </div>
          </Panel>

          {/* Resize Handle */}
          <Separator className="h-2 bg-border hover:bg-accent/50 cursor-row-resize flex items-center justify-center group">
            <div className="w-8 h-1 bg-foreground-tertiary rounded group-hover:bg-accent transition-colors" />
          </Separator>

          {/* Preview Panel */}
          <Panel minSize={20} defaultSize={50}>
            <div className="h-full p-2 bg-background-tertiary">
              <CodePreview
                html={previewCode.html}
                css={previewCode.css}
                js={previewCode.js}
                onConsole={handleConsole}
                onError={handleError}
              />
            </div>
          </Panel>
        </Group>
      </div>

      {/* Console */}
      <ConsolePanel
        logs={logs}
        errors={errors}
        onClear={handleClearConsole}
      />
    </div>
  )
})

export default CodeCanvas

// Helpers moved to ./parse (a leaf module with NO React/CodeMirror imports) so
// eager consumers (ChatPage, useChatStream) can use them without pulling the
// heavy CodeMirror editor into the always-loaded chat chunk. Re-exported here
// for backward-compat — but new code should import from './parse' directly.
export { parseHtmlCode, isRunnableCode } from './parse'

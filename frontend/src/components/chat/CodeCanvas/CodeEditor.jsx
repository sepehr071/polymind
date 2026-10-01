import { memo, useCallback } from 'react'
import CodeMirror, { EditorView } from '@uiw/react-codemirror'
import { langs } from '@uiw/codemirror-extensions-langs'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'

// Code Canvas only ever edits HTML / CSS / JS(X)(/TS(X)) / JSON. We pin the
// lookup to exactly those grammar loaders instead of indexing `langs[...]` by a
// free-form string, so it's obvious which grammars this editor actually uses.
//
// NOTE: `@uiw/codemirror-extensions-langs` is a single barrel — its `esm/index.js`
// statically imports ~80 `@codemirror/lang-*` grammars into module scope and
// closes over them in one exported `langs` object, so referencing only a few
// `langs.*` keys does NOT tree-shake the rest out (the whole object, and thus
// every captured import, is retained). The barrel also exposes NO individual
// named member exports — only `langs` / `langNames` / `loadLanguage` — so there
// is nothing finer-grained to import from it. True per-grammar imports would
// mean importing `@codemirror/lang-html` etc. directly, but those are undeclared
// (phantom) deps: under pnpm's strict node_modules they aren't resolvable from
// the frontend root (verified MODULE_NOT_FOUND), and declaring them is barred in
// this repo (no new deps). The real payload win therefore comes from lazy-loading
// this whole editor (CodeCanvas is `lazyWithRetry`-imported in ChatPage), which
// moves the barrel out of the always-loaded chat chunk into the on-demand Code
// Canvas chunk. The `langs.*` keys below are kept minimal so that if/when the
// individual grammar deps are added, the swap is mechanical.
const GRAMMARS = {
  html: () => langs.html(),
  css: () => langs.css(),
  javascript: () => langs.jsx(),
  typescript: () => langs.tsx(),
  json: () => langs.json(),
}

// Map every accepted alias onto one of the GRAMMARS keys above.
const LANGUAGE_ALIASES = {
  html: 'html',
  htm: 'html',
  css: 'css',
  javascript: 'javascript',
  js: 'javascript',
  jsx: 'javascript',
  typescript: 'typescript',
  ts: 'typescript',
  tsx: 'typescript',
  json: 'json',
}

/**
 * CodeMirror-based code editor with language support
 */
const CodeEditor = memo(function CodeEditor({
  value,
  language = 'html',
  onChange,
  height = '100%',
  readOnly = false
}) {
  // Get language extension based on language type
  const getExtension = useCallback((lang) => {
    const key = LANGUAGE_ALIASES[lang?.toLowerCase()] || 'html'
    return GRAMMARS[key]()
  }, [])

  const handleChange = useCallback((val) => {
    if (onChange) {
      onChange(val)
    }
  }, [onChange])

  // Ensure value is never undefined (causes CodeMirror issues)
  const safeValue = value ?? ''

  return (
    <div dir="ltr" className="h-full">
    <CodeMirror
      key={language}  // Force clean remount on language change to prevent extension issues
      value={safeValue}
      height={height}
      theme={vscodeDark}
      // lineWrapping: the canvas panel is a narrow side column — without wrap
      // every long line forces horizontal scrolling and code reads clipped.
      extensions={[getExtension(language), EditorView.lineWrapping]}
      onChange={handleChange}
      readOnly={readOnly}
      basicSetup={{
        lineNumbers: true,
        highlightActiveLineGutter: true,
        highlightSpecialChars: true,
        history: true,
        foldGutter: true,
        drawSelection: true,
        dropCursor: true,
        allowMultipleSelections: true,
        indentOnInput: true,
        syntaxHighlighting: true,
        bracketMatching: true,
        closeBrackets: true,
        autocompletion: true,
        rectangularSelection: true,
        crosshairCursor: false,
        highlightActiveLine: true,
        highlightSelectionMatches: true,
        closeBracketsKeymap: true,
        defaultKeymap: true,
        searchKeymap: true,
        historyKeymap: true,
        foldKeymap: true,
        completionKeymap: true,
        lintKeymap: true,
      }}
      className="h-full text-sm"
    />
    </div>
  )
})

export default CodeEditor

import { useEffect, useMemo, useRef, memo } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Helper to escape closing tags that would break srcdoc.
 * Prevents user code containing </script>, </style>, or even bare </script
 * (with attribute or whitespace before the `>`) from breaking HTML structure.
 *
 * Match opening of close tag — anything starting with `</tag` — and rewrite
 * the slash so the parser cannot terminate the surrounding block.
 */
const escapeClosingTags = (code, tag) => {
  if (!code) return ''
  // Match `</<tag>` not followed by another letter — covers `</script>`,
  // `</script `, `</script\n`, `</script type="foo">`, and bare `</script`.
  const regex = new RegExp(`</(${tag})(?![a-z0-9])`, 'gi')
  return code.replace(regex, '<\\/$1')
}

/**
 * Build the full sandbox-ready HTML document for a {html, css, js} bundle:
 * console/error capture shim + user code. Exported so the "open in new tab"
 * action (CodeCanvas header) can render the exact same document fullscreen.
 *
 * User JS gets its OWN top-level <script> tag (NOT wrapped in a function):
 *  - top-level function declarations become window globals, so LLM-generated
 *    inline handlers (onclick="fn()") resolve — the old runUserCode() wrapper
 *    kept them function-scoped → "fn is not defined" on every interaction;
 *  - a SyntaxError there kills only that tag; the capture shim's
 *    window.onerror (installed by the preceding tag) still reports it;
 *  - the tag sits after ${html} at the end of <body>, so the DOM is parsed
 *    before it runs (same guarantee the old DOMContentLoaded branch gave).
 */
export const buildPreviewDoc = ({ html, css, js }) => {
  // Escape closing tags to prevent breaking out of script/style blocks
  const safeCSS = escapeClosingTags(css, 'style')
  const safeJS = escapeClosingTags(js, 'script')
  // Pin postMessage target to the embedder origin (P0.10). The iframe is
  // sandbox="allow-scripts" with no allow-same-origin, so its own
  // event.origin will be the literal string "null". JSON-encoding here
  // both safely escapes for inline JS and yields a quoted string literal.
  const parentOriginLiteral = JSON.stringify(window.location.origin)

  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    /* Reset styles */
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 16px;
      font-family: system-ui, -apple-system, sans-serif;
      background: white;
      color: #1a1a1a;
    }
    /* User CSS */
    ${safeCSS}
  </style>
</head>
<body>
  ${html}
  <script>
    // Console capture - send to parent
    const originalConsole = { ...console };
    ['log', 'warn', 'error', 'info'].forEach(method => {
      console[method] = (...args) => {
        const formatted = args.map(arg => {
          if (typeof arg === 'object') {
            try {
              return JSON.stringify(arg, null, 2);
            } catch {
              return String(arg);
            }
          }
          return String(arg);
        });
        parent.postMessage({
          type: 'console',
          method,
          args: formatted,
          timestamp: Date.now()
        }, ${parentOriginLiteral});
        originalConsole[method](...args);
      };
    });

    // Error capture — also fires for runtime AND syntax errors thrown by the
    // separate user-JS script tag below (it parses/executes after this shim).
    window.onerror = (msg, url, line, col, error) => {
      parent.postMessage({
        type: 'error',
        message: msg,
        line,
        col,
        stack: error?.stack
      }, ${parentOriginLiteral});
      return false; // Allow errors to also show in browser console for debugging
    };

    // Unhandled promise rejection
    window.onunhandledrejection = (event) => {
      parent.postMessage({
        type: 'error',
        message: 'Unhandled Promise Rejection: ' + event.reason,
        line: 0,
        col: 0
      }, ${parentOriginLiteral});
    };
  </script>
  <script>
${safeJS}
  </script>
</body>
</html>`
}

/**
 * Sandboxed iframe preview for HTML/CSS/JS code
 * Uses srcdoc for secure, instant preview without server
 */
const CodePreview = memo(function CodePreview({ html, css, js, onConsole, onError }) {
  const { t } = useTranslation('chat')
  const iframeRef = useRef(null)

  // Memoised on the code inputs — the doc was being rebuilt twice per render
  // (once for the effect, once for the `srcDoc` prop) even when unchanged.
  const previewDoc = useMemo(() => buildPreviewDoc({ html, css, js }), [html, css, js])

  // Listen for messages from iframe
  useEffect(() => {
    const handleMessage = (event) => {
      // Sandbox-without-allow-same-origin iframes have opaque origin "null".
      // Reject anything else even if event.source matches (defence in depth).
      if (event.origin !== 'null') return
      // Only accept messages from our iframe
      if (iframeRef.current && event.source === iframeRef.current.contentWindow) {
        const { type, method, args, message, line, col, timestamp } = event.data

        if (type === 'console' && onConsole) {
          onConsole({ method, args, timestamp })
        } else if (type === 'error' && onError) {
          onError({ message, line, col })
        }
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [onConsole, onError])

  // Update iframe content when code changes
  useEffect(() => {
    if (iframeRef.current) {
      iframeRef.current.srcdoc = previewDoc
    }
  }, [previewDoc])

  return (
    <div className="h-full w-full bg-white rounded-lg overflow-hidden">
      <iframe
        ref={iframeRef}
        title={t('codeCanvas.previewTitle')}
        sandbox="allow-scripts"
        className="w-full h-full border-0"
        srcDoc={previewDoc}
      />
    </div>
  )
})

export default CodePreview

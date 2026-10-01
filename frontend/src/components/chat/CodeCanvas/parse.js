// Pure, dependency-free helpers for the Code Canvas.
//
// IMPORTANT: this module must import NOTHING from React or CodeMirror. It is
// imported eagerly by the always-loaded chat chunk (ChatPage, useChatStream),
// so any heavy import here would re-introduce CodeMirror into that bundle —
// the exact regression these helpers were extracted to avoid. Keep it leaf-only.

/**
 * Parse a code block and split it into { html, css, js } for the live preview.
 * For pure CSS/JS blocks the content lands in the matching slot; for HTML it
 * extracts embedded <style>/<script> tags and strips document wrapper tags.
 */
export const parseHtmlCode = (code, language) => {
  // If it's pure CSS or JS, return as-is
  if (language === 'css') {
    return { html: '', css: code, js: '' }
  }
  if (['javascript', 'js', 'jsx'].includes(language)) {
    return { html: '', css: '', js: code }
  }

  // For HTML, try to extract embedded style and script tags
  if (['html', 'htm'].includes(language)) {
    const cssMatch = code.match(/<style[^>]*>([\s\S]*?)<\/style>/gi)
    // INLINE scripts only — a `src`-bearing tag (CDN lib) must stay in the html
    // slot so the browser loads it in document order, BEFORE the extracted user
    // JS that the preview appends at the end of <body>. The old pattern matched
    // ALL <script> tags, so external libs were silently discarded → every
    // `THREE is not defined`-style preview error.
    const jsMatch = code.match(/<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)

    let css = ''
    let js = ''
    let html = code

    // Extract CSS
    if (cssMatch) {
      cssMatch.forEach(match => {
        const content = match.replace(/<style[^>]*>/i, '').replace(/<\/style>/i, '')
        css += content + '\n'
        html = html.replace(match, '')
      })
    }

    // Extract JS
    if (jsMatch) {
      jsMatch.forEach(match => {
        const content = match.replace(/<script[^>]*>/i, '').replace(/<\/script>/i, '')
        js += content + '\n'
        html = html.replace(match, '')
      })
    }

    // Unwrap <head> instead of discarding it: after the style/inline-script
    // extraction above, the head's remaining children are things the preview
    // must keep — CDN <script src>, <link rel="stylesheet">, meta. Relocate
    // them to the top of the body slot (browsers tolerate all of them there;
    // <title>/<meta> stay inert). Dropping the whole head — the old behavior —
    // lost external libs and stylesheets.
    const headMatch = html.match(/<head[^>]*>([\s\S]*?)<\/head>/i)
    if (headMatch) {
      html = headMatch[1] + '\n' + html.replace(headMatch[0], '')
    }

    // Clean up HTML (remove doctype, html, body wrapper tags for inner content)
    html = html
      .replace(/<!DOCTYPE[^>]*>/i, '')
      .replace(/<\/?html[^>]*>/gi, '')
      .replace(/<\/?body[^>]*>/gi, '')
      .trim()

    return {
      html: html.trim(),
      css: css.trim(),
      js: js.trim()
    }
  }

  // Default: treat as HTML
  return { html: code, css: '', js: '' }
}

/**
 * Whether a fenced code block's language is renderable in the Code Canvas.
 */
export const isRunnableCode = (language) => {
  const runnableLanguages = ['html', 'htm', 'css', 'javascript', 'js', 'jsx']
  return runnableLanguages.includes(language?.toLowerCase())
}

/**
 * Coarse "section" key for route-level remount/transition gating.
 * Collapses param-only / sub-path changes within a top-level section to one
 * stable key ('/chat' and '/chat/<id>' → '/chat'), so a param-only navigation
 * does NOT remount the routed subtree.
 *
 * Used by PageTransition (motion key) AND App's ErrorBoundary key — these two
 * MUST stay byte-identical, hence one source of truth. Without this, adding the
 * conversation id to the URL after the first chat message changed the full
 * pathname key, remounting ChatPage mid-stream (visible "page refresh" + lost
 * live stream).
 */
export function getRouteSectionKey(pathname) {
  return '/' + (pathname || '').split('/')[1]
}

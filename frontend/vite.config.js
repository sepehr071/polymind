import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Backend (uvicorn) origin for the dev proxy. run-fastapi.bat picks a free
// backend port and exports it as VITE_BACKEND_PORT so the /api proxy always
// targets the uvicorn it actually launched (avoids fighting a zombie on :5000).
// Falls back to :5000 when launched directly.
const backendTarget = `http://localhost:${process.env.VITE_BACKEND_PORT || 5000}`

// Content-Security-Policy injected as a <meta> tag at BUILD time only (never in
// dev — Vite HMR needs 'unsafe-eval'/ws: that a strict policy would block). This
// is the CSP that actually ships to the live prod (prod) via the normal
// frontend deploy, since that origin's nginx is managed server-side.
//
// Deliberate tradeoffs:
//  - script-src 'unsafe-inline': the Code Canvas preview is a `srcdoc` iframe
//    that inherits the parent document CSP and injects inline <script> (the
//    console shim + model-generated JS); the index.html theme bootstrap is also
//    inline. We do NOT add a hash alongside 'unsafe-inline' — CSP2 ignores
//    'unsafe-inline' the moment any hash/nonce is present, which would silently
//    kill the canvas. The real win remains: external script origins blocked,
//    object-src none, base-uri, form-action. (Follow-up: move the canvas to a
//    blob: iframe with its own CSP, then tighten this to 'self'.)
//  - style-src 'unsafe-inline': MUI/Emotion inject runtime <style> — unavoidable.
//  - connect-src includes the Keycloak origin: keycloakClient.js does the PKCE
//    token exchange + discovery + refresh as fetch() straight to KC.
//  - frame-ancestors / upgrade-insecure-requests are omitted: a <meta> CSP can't
//    express frame-ancestors (served as a header by nginx/asgi), and
//    upgrade-insecure-requests would break the local http preview.
function cspMetaPlugin(kcOrigin) {
  let isBuild = false
  return {
    name: 'inject-csp-meta',
    config(_config, { command }) {
      isBuild = command === 'build'
    },
    transformIndexHtml(html) {
      if (!isBuild) return html
      const connectSrc = ["'self'", kcOrigin].filter(Boolean).join(' ')
      const formAction = ["'self'", kcOrigin].filter(Boolean).join(' ')
      const policy = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' data: blob:",
        "font-src 'self' data:",
        `connect-src ${connectSrc}`,
        "frame-src 'self' blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        `form-action ${formAction}`,
      ].join('; ')
      return {
        html,
        tags: [
          {
            tag: 'meta',
            attrs: { 'http-equiv': 'Content-Security-Policy', content: policy },
            injectTo: 'head-prepend',
          },
        ],
      }
    },
  }
}

export default defineConfig(({ mode }) => {
  // loadEnv (not process.env) so the KC origin is read from .env at build time;
  // Dockerfile_front copies .env_front -> .env, so VITE_KEYCLOAK_URL is present.
  const env = loadEnv(mode, process.cwd(), '')
  let kcOrigin = ''
  try {
    if (env.VITE_KEYCLOAK_URL) kcOrigin = new URL(env.VITE_KEYCLOAK_URL).origin
  } catch {
    kcOrigin = ''
  }

  return {
    plugins: [react(), cspMetaPlugin(kcOrigin)],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      host: '0.0.0.0',
      // VITE_PORT lets the launcher pin a free port; Vite still auto-increments
      // if it's taken. Default 3000.
      port: Number(process.env.VITE_PORT) || 3000,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            // Coalesce each language's locale JSON into ONE async chunk so the
            // active language loads in a single request (not 22), and the other
            // language stays in its own chunk that a single-language user never
            // fetches. Keeps i18n bundle-splitting (see src/i18n/index.js).
            // ONLY locale JSON is manually chunked. Vendor libs are left to
            // rollup's automatic chunking: hand-rolled vendor splits (react /
            // radix / i18n / motion...) produced a circular chunk graph whose
            // execution order broke module init in prod builds (blank page —
            // "createContext of undefined" / TDZ errors at startup).
            const locale = id.match(/[\\/]i18n[\\/]locales[\\/]([^\\/]+)[\\/][^\\/]+\.json$/)
            if (locale) return `locale-${locale[1]}`
          },
        },
      },
    },
  }
})

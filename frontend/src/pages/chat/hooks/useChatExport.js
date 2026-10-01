import { useState, useCallback } from 'react'
import { chatService } from '../../../services/chatService'
import toast from 'react-hot-toast'
import i18n from '../../../i18n'

const EXPORT_EXT = { json: 'json', markdown: 'md', pdf: 'pdf' }

function filenameFromDisposition(header, fallback) {
  const raw = typeof header === 'string' ? header : ''
  if (!raw) return fallback
  // ASCII filename= is the one the browser can always save. The UTF-8
  // filename* is only a nicer title; a bad decode must not fail the export.
  const plain = /filename="([^"]+)"/i.exec(raw)
  if (plain?.[1]) return plain[1]
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(raw)
  if (star) {
    try { return decodeURIComponent(star[1].trim().replace(/^"|"$/g, '')) } catch { /* fallback */ }
  }
  return fallback
}

function saveBlob(blob, name) {
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name || 'polymind-chat.txt'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1500)
}

export function useChatExport(conversationId) {
  const [showExportMenu, setShowExportMenu] = useState(false)

  const handleExport = useCallback(async (format) => {
    if (!conversationId) return

    const ext = EXPORT_EXT[format] || 'txt'
    let saved = false
    try {
      const response = await chatService.exportConversation(conversationId, format, true)
      const blob = response.data
      if (!(blob instanceof Blob) || blob.size === 0) throw new Error('empty export')
      const name = filenameFromDisposition(
        response.headers?.['content-disposition'],
        `polymind-chat.${ext}`,
      )
      saveBlob(blob, name)
      saved = true
      toast.success(i18n.t('common:runtime.chat.exportedAs', { kind: String(format || ext).toUpperCase() }))
      setShowExportMenu(false)
    } catch (error) {
      if (saved) return
      let message = i18n.t('common:runtime.chat.exportFailed')
      const data = error?.response?.data
      if (data instanceof Blob) {
        try {
          const body = JSON.parse(await data.text())
          if (body?.error) message = body.error
        } catch { /* keep generic */ }
      } else if (data?.error) {
        message = data.error
      }
      toast.error(message)
    }
  }, [conversationId])

  return { showExportMenu, setShowExportMenu, handleExport }
}

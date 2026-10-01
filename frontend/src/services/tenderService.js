import api from './api'
import { chatService } from './chatService'
import { streamStudio } from './studioStream'

const EXT = new Set(['pdf', 'png', 'jpg', 'jpeg', 'webp', 'docx', 'doc', 'txt'])

export function isTenderFile(file) {
  if (!file) return false
  const ext = (file.name || '').toLowerCase().split('.').pop()
  return EXT.has(ext)
}

export async function uploadTenderFile(file) {
  return chatService.uploadFile(file)
}

export function streamTenderAnalyze(body, handlers = {}, signal) {
  return streamStudio({
    url: '/tenders/analyze',
    body,
    handlers: {
      onStatus: handlers.onStatus,
      onResult: handlers.onResult,
      onDone: handlers.onDone,
      onError: handlers.onError,
    },
    signal,
    idleTimeoutMs: 180_000,
  })
}

export async function handoffPresentation(body) {
  const res = await api.post('/tenders/handoff-presentation', body)
  return res.data
}

export const TENDER_MAX_FILES = 5

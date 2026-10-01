import { chatService } from './chatService'
import { streamStudio } from './studioStream'

const ACCEPT = new Set([
  'application/pdf',
  'image/png',
  'image/jpeg',
  'image/jpg',
  'image/webp',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/msword',
])
const EXT = new Set(['pdf', 'png', 'jpg', 'jpeg', 'webp', 'docx', 'doc'])

export function isCvFile(file) {
  if (!file) return false
  if (file.type && ACCEPT.has(file.type.toLowerCase())) return true
  const ext = (file.name || '').toLowerCase().split('.').pop()
  return EXT.has(ext)
}

export async function uploadCvFile(file) {
  return chatService.uploadFile(file)
}

export function streamCvCheck(body, handlers = {}, signal) {
  return streamStudio({
    url: '/cv-checker/run',
    body,
    handlers: {
      onStatus: handlers.onStatus,
      onDone: handlers.onDone,
      onError: handlers.onError,
    },
    signal,
    idleTimeoutMs: 180_000,
  })
}

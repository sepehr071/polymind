import { chatService } from './chatService'
import { streamStudio } from './studioStream'

const EXT = new Set(['pdf', 'png', 'jpg', 'jpeg', 'webp'])

export function isContractFile(file) {
  if (!file) return false
  const ext = (file.name || '').toLowerCase().split('.').pop()
  return EXT.has(ext) || (file.type || '').includes('pdf') || (file.type || '').startsWith('image/')
}

export async function uploadContractFile(file) {
  return chatService.uploadFile(file)
}

export function streamContractReview(body, handlers = {}, signal) {
  return streamStudio({
    url: '/contracts/review',
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

export const CONTRACT_MAX_FILES = 3

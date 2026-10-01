import api from './api'
import { chatService } from './chatService'
import { streamStudio } from './studioStream'

export async function listResearchModels() {
  const res = await api.get('/research/models')
  return res.data?.models ?? []
}

export async function uploadResearchFile(file) {
  return chatService.uploadFile(file)
}

export function streamResearch(body, handlers = {}, signal) {
  return streamStudio({
    url: '/research/run',
    body,
    handlers: {
      onStatus: handlers.onStatus,
      onDelta: handlers.onDelta,
      onDone: handlers.onDone,
      onError: handlers.onError,
    },
    signal,
    idleTimeoutMs: 600_000,
  })
}

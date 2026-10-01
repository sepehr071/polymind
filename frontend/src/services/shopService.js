import { streamStudio } from './studioStream'

export function streamShop(body, handlers = {}, signal) {
  return streamStudio({
    url: '/shop/run',
    body,
    handlers: {
      onStatus: handlers.onStatus,
      onPlan: handlers.onPlan,
      onCandidates: handlers.onCandidates,
      onDone: handlers.onDone,
      onError: handlers.onError,
    },
    signal,
    idleTimeoutMs: 300_000,
  })
}

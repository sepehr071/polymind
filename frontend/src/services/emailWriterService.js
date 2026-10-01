import { streamStudio } from './studioStream'

export const EMAIL_TEMPLATES = [
  'official_letter',
  'internal_email',
  'follow_up',
  'request',
  'complaint',
  'invitation',
  'resignation',
  'thank_you',
  'introduction',
  'reply',
]

export function streamEmailGenerate(body, handlers = {}, signal) {
  return streamStudio({
    url: '/email-writer/generate',
    body,
    handlers: {
      onStatus: handlers.onStatus,
      onToken: handlers.onToken,
      onDelta: handlers.onToken,
      onDone: handlers.onDone,
      onError: handlers.onError,
    },
    signal,
    idleTimeoutMs: 180_000,
  })
}

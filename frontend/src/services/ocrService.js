/**
 * OCR assistant — multi-file extract via SSE.
 *
 * POST /ocr/extract — events: status | file_result | file_error | error | done
 * Thin-wraps shared studioStream.
 */

import api from './api'
import { chatService } from './chatService'
import { streamStudio } from './studioStream'

/**
 * @param {Object} body
 * @param {string[]} body.upload_ids
 * @param {string} [body.prompt]
 * @param {string} [body.workspace_id]
 * @param {Object} handlers
 * @param {AbortSignal} [signal]
 */
export function streamOcrExtract(body, handlers = {}, signal) {
  return streamStudio({
    url: '/ocr/extract',
    body,
    handlers,
    signal,
    idleTimeoutMs: 180_000,
  })
}

export async function listOcrJobs({ limit = 50 } = {}) {
  const response = await api.get('/ocr/jobs', { params: { limit } })
  return response.data
}

export async function getOcrJob(id) {
  const response = await api.get(`/ocr/jobs/${id}`)
  return response.data
}

export async function deleteOcrJob(id) {
  const response = await api.delete(`/ocr/jobs/${id}`)
  return response.data
}

const OCR_ACCEPT = new Set([
  'image/png',
  'image/jpeg',
  'image/jpg',
  'image/webp',
  'image/gif',
  'application/pdf',
])

const OCR_EXT = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'pdf'])

export function isOcrFile(file) {
  if (!file) return false
  if (file.type && OCR_ACCEPT.has(file.type.toLowerCase())) return true
  const name = (file.name || '').toLowerCase()
  const ext = name.includes('.') ? name.split('.').pop() : ''
  return OCR_EXT.has(ext)
}

/** Upload one file via existing /uploads/file; returns unwrapped upload row. */
export async function uploadOcrFile(file) {
  return chatService.uploadFile(file)
}

export const OCR_MAX_FILES = 5

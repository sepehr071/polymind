import { HardDrive } from 'lucide-react'
import { cn } from '@/utils/cn'
import google from '@/assets/model-logos/google.svg'
import gemma from '@/assets/model-logos/gemma.svg'
import anthropic from '@/assets/model-logos/anthropic.svg'
import openai from '@/assets/model-logos/openai.svg'
import deepseek from '@/assets/model-logos/deepseek.svg'
import xai from '@/assets/model-logos/xai.svg'
import nvidia from '@/assets/model-logos/nvidia.svg'

/** Vendor key → local SVG (Lobe Icons; vendored for air-gap). */
export const MODEL_LOGOS = {
  google,
  gemma,
  anthropic,
  openai,
  deepseek,
  xai,
  nvidia,
}

/** Monochrome SVGs need invert in dark mode to stay visible. */
const MONO_LOGOS = new Set(['openai', 'deepseek', 'xai'])

/**
 * Infer vendor logo key from an OpenRouter model id (`vendor/slug`).
 * @param {string|null|undefined} modelId
 * @returns {string|null}
 */
export function logoKeyFromModelId(modelId) {
  if (!modelId) return null
  const id = String(modelId).toLowerCase()
  if (id.includes('gemma')) return 'gemma'
  if (id.startsWith('google/') || id.includes('gemini')) return 'google'
  if (id.startsWith('anthropic/') || id.includes('claude')) return 'anthropic'
  if (id.startsWith('openai/') || id.includes('gpt-')) return 'openai'
  if (id.startsWith('deepseek/')) return 'deepseek'
  if (id.startsWith('x-ai/') || id.includes('grok')) return 'xai'
  if (id.startsWith('nvidia/') || id.includes('nemotron')) return 'nvidia'
  return null
}

/**
 * Company logo for a quick model / vendor.
 * @param {{ logo?: string, modelId?: string, size?: number, className?: string }} props
 */
export default function ModelLogo({ logo, modelId, size = 20, className }) {
  const key = logo || logoKeyFromModelId(modelId)
  // Self-hosted local model has no vendor SVG — use a distinct in-house glyph.
  if (key === 'local') {
    return (
      <span
        className={cn(
          'inline-flex items-center justify-center rounded-md bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 shrink-0',
          className
        )}
        style={{ width: size, height: size }}
        aria-hidden
      >
        <HardDrive style={{ width: size * 0.6, height: size * 0.6 }} />
      </span>
    )
  }
  const src = key ? MODEL_LOGOS[key] : null
  if (!src) {
    return (
      <span
        className={cn(
          'inline-flex items-center justify-center rounded-md bg-accent/15 text-accent text-[10px] font-semibold shrink-0',
          className
        )}
        style={{ width: size, height: size }}
        aria-hidden
      >
        AI
      </span>
    )
  }
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      draggable={false}
      className={cn(
        'object-contain shrink-0 select-none',
        MONO_LOGOS.has(key) && 'dark:invert',
        className
      )}
      aria-hidden
    />
  )
}

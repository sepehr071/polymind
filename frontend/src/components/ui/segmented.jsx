import * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * Segmented — canonical SEGMENTED FILTER control (Consistent UI System).
 *
 * One container (hover-bg surface + 1px line + radius 11 + pad 4); the active
 * segment lifts onto a flat surface with a small shadow, inactive segments are
 * fg-2 text. NO per-item borders and NO accent fill — accent is reserved for
 * primary actions, not filter state.
 *
 * Replaces the per-page hand-rolled "Seg" patterns (ProjectsPage etc.) and
 * accent-filled button groups. Built on theme tokens so it tracks light/dark.
 *
 * @param {{value:string,label:React.ReactNode,icon?:React.ReactNode,suffix?:React.ReactNode}[]} items
 * @param {string} value          currently-selected segment value
 * @param {(value:string)=>void} onChange
 * @param {string} [size]         'sm' (default) | 'md'
 * @param {string} [ariaLabel]    accessible group label
 * @param {string} [className]    extra classes on the container
 */
const SIZES = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-3 py-1.5 text-sm',
}

export function Segmented({ items, value, onChange, size = 'sm', ariaLabel, className }) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        'inline-flex items-center gap-0.5 rounded-[11px] border border-border bg-background-secondary p-1',
        className,
      )}
    >
      {items.map((it) => {
        const active = it.value === value
        return (
          <button
            key={it.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(it.value)}
            className={cn(
              'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors',
              SIZES[size] || SIZES.sm,
              active
                ? 'bg-background text-foreground shadow-sm'
                : 'text-foreground-secondary hover:text-foreground',
            )}
          >
            {it.icon}
            {it.label}
            {it.suffix}
          </button>
        )
      })}
    </div>
  )
}

export default Segmented

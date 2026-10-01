import { useState } from 'react'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { cn } from '../../utils/cn'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'

/**
 * Adaptive disclosure surface: renders a Popover on >=md (768px) and a
 * bottom Sheet on <md. Dumb container — owns NO item rendering, just passes
 * `children` straight through and wraps `trigger` with the surface's trigger.
 *
 * Props (EXACT contract — downstream agents depend on these names):
 *   trigger          ReactNode — wrapped via asChild on both surfaces.
 *   title            string    — heading for the mobile Sheet header.
 *   children         ReactNode — surface body, passed through unchanged.
 *   open             boolean   — controlled open state (optional).
 *   onOpenChange     (next: boolean) => void — controlled setter (optional).
 *   align            'start' | 'center' | 'end' (default 'start') — desktop only.
 *   contentClassName string    — extra classes on the desktop PopoverContent.
 *
 * Controlled-or-uncontrolled: if `open`/`onOpenChange` are supplied they drive
 * the surface, otherwise an internal state is used.
 */
export default function ResponsivePicker({
  trigger,
  title,
  children,
  open: openProp,
  onOpenChange,
  align = 'start',
  contentClassName,
}) {
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const isControlled = openProp !== undefined
  const [uncontrolled, setUncontrolled] = useState(false)
  const open = isControlled ? openProp : uncontrolled

  const setOpen = (next) => {
    if (!isControlled) setUncontrolled(next)
    onOpenChange?.(next)
  }

  if (isDesktop) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent align={align} className={cn('w-auto', contentClassName)}>
          {children}
        </PopoverContent>
      </Popover>
    )
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{trigger}</SheetTrigger>
      <SheetContent
        side="bottom"
        className="rounded-t-2xl p-0"
      >
        <SheetHeader className="border-b border-border px-4 py-3 text-start">
          <SheetTitle>{title}</SheetTitle>
        </SheetHeader>
        <div className={cn('max-h-[70vh] overflow-y-auto p-4', contentClassName)}>
          {children}
        </div>
      </SheetContent>
    </Sheet>
  )
}

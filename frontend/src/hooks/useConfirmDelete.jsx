import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { cn } from '@/lib/utils'

/**
 * Promise-based confirmation dialog built on the Radix AlertDialog primitives.
 *
 * Replaces the native, un-styled `window.confirm` with an in-app modal that
 * honours theme tokens + RTL. Mirrors the `useDlpConfirm` pattern: a single
 * pending-state object carries the prompt copy and a `resolve` so the caller's
 * awaited promise unblocks once the user confirms or cancels.
 *
 * Usage:
 *
 *   const { confirm, confirmDialog } = useConfirmDelete()
 *   const ok = await confirm({
 *     title,
 *     description,
 *     confirmLabel,   // optional — defaults to common:actions.confirm
 *     cancelLabel,    // optional — defaults to common:actions.cancel
 *     destructive: true, // optional — paints the confirm button with the error token
 *   })
 *   if (!ok) return
 *   // ...do the destructive thing
 *   // render ONCE in the component's JSX:
 *   { confirmDialog }
 *
 * `confirm` resolves:
 *   - `true`  when the user clicks the confirm action
 *   - `false` when the user cancels, closes (Esc / overlay), or dismisses
 *
 * @returns {{ confirm: (opts: Object) => Promise<boolean>, confirmDialog: JSX.Element }}
 */
export function useConfirmDelete() {
  const { t } = useTranslation('common')

  // null = closed. Otherwise carries the prompt copy + the awaited `resolve`.
  const [pending, setPending] = useState(null)

  const confirm = useCallback((opts = {}) => {
    return new Promise((resolve) => {
      setPending((current) => {
        // A second confirm() before the first settled would orphan the prior
        // promise forever — resolve the abandoned one as cancelled first.
        if (current) current.resolve(false)
        return {
          title: opts.title || '',
          description: opts.description || '',
          confirmLabel: opts.confirmLabel || null,
          cancelLabel: opts.cancelLabel || null,
          destructive: !!opts.destructive,
          resolve,
        }
      })
    })
  }, [])

  // Settle the awaited promise and close. `open` toggling to false (Esc /
  // overlay click) routes through here with `false`.
  const settle = useCallback((value) => {
    setPending((current) => {
      if (current) current.resolve(value)
      return null
    })
  }, [])

  const handleOpenChange = useCallback(
    (open) => {
      if (!open) settle(false)
    },
    [settle],
  )

  const confirmDialog = (
    <AlertDialog open={!!pending} onOpenChange={handleOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          {pending?.title ? (
            <AlertDialogTitle>{pending.title}</AlertDialogTitle>
          ) : null}
          {pending?.description ? (
            <AlertDialogDescription>
              {pending.description}
            </AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => settle(false)}>
            {pending?.cancelLabel || t('actions.cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() => settle(true)}
            className={cn(
              pending?.destructive &&
                'bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90',
            )}
          >
            {pending?.confirmLabel || t('actions.confirm')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )

  return { confirm, confirmDialog }
}

export default useConfirmDelete

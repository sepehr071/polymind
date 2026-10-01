"use client"

import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import MuiDialog from "@mui/material/Dialog"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { solidPanelSx } from "@/theme/glass"
import { RADII } from "@/theme/tokens"

// ---------------------------------------------------------------------------
// MUI-backed AlertDialog preserving the Radix compound API. Like Dialog, but
// non-dismissable by backdrop/escape so a confirm flow can't be skipped — the
// only exits are AlertDialogAction / AlertDialogCancel. A context relays the
// open state + setter (Trigger opens, Action/Cancel close after their onClick).
// Action/Cancel render the real <Button> so every dialog button shares the one
// Material appearance (theme-owned) instead of the legacy cva look.
// ---------------------------------------------------------------------------

const AlertDialogContext = React.createContext({
  open: false,
  setOpen: () => {},
  titleId: undefined,
  descriptionId: undefined,
  // Title/Description register so MuiDialog only references ids that actually
  // render (a dangling aria-labelledby/describedby is itself an a11y defect).
  registerTitle: () => {},
  registerDescription: () => {},
})

const AlertDialog = ({ open: openProp, defaultOpen = false, onOpenChange, children }) => {
  const isControlled = openProp !== undefined
  const [uncontrolled, setUncontrolled] = React.useState(defaultOpen)
  const open = isControlled ? openProp : uncontrolled

  const setOpen = React.useCallback(
    (next) => {
      if (!isControlled) setUncontrolled(next)
      onOpenChange?.(next)
    },
    [isControlled, onOpenChange],
  )

  const ctx = React.useMemo(() => ({ open, setOpen }), [open, setOpen])
  return (
    <AlertDialogContext.Provider value={ctx}>{children}</AlertDialogContext.Provider>
  )
}
AlertDialog.displayName = "AlertDialog"

const AlertDialogTrigger = React.forwardRef(
  ({ asChild = false, onClick, children, ...props }, ref) => {
    const { setOpen } = React.useContext(AlertDialogContext)
    const handleClick = (e) => {
      onClick?.(e)
      if (!e.defaultPrevented) setOpen(true)
    }
    const Comp = asChild ? Slot : "button"
    return (
      <Comp ref={ref} onClick={handleClick} {...props}>
        {children}
      </Comp>
    )
  },
)
AlertDialogTrigger.displayName = "AlertDialogTrigger"

// MUI Dialog owns the portal + backdrop; these stay as inert pass-throughs for
// API + barrel-export parity.
const AlertDialogPortal = ({ children }) => <>{children}</>
AlertDialogPortal.displayName = "AlertDialogPortal"

const AlertDialogOverlay = React.forwardRef(({ className, ...props }, ref) => (
  <div ref={ref} className={className} {...props} />
))
AlertDialogOverlay.displayName = "AlertDialogOverlay"

const AlertDialogContent = React.forwardRef(({ className, children, ...props }, ref) => {
  const { open, setOpen } = React.useContext(AlertDialogContext)
  // Stable ids so the alertdialog is labelled/described by the consumer's
  // Title/Description — restores screen-reader parity with the Radix original.
  const baseId = React.useId()
  const titleId = `${baseId}-title`
  const descriptionId = `${baseId}-description`
  const [hasTitle, setHasTitle] = React.useState(false)
  const [hasDescription, setHasDescription] = React.useState(false)
  const a11yCtx = React.useMemo(
    () => ({
      open,
      setOpen,
      titleId,
      descriptionId,
      registerTitle: setHasTitle,
      registerDescription: setHasDescription,
    }),
    [open, setOpen, titleId, descriptionId],
  )
  return (
    <AlertDialogContext.Provider value={a11yCtx}>
    <MuiDialog
      open={open}
      // Alert dialogs are intentionally NOT dismissable by backdrop click;
      // escape still routes through onClose so Esc closes (Radix parity).
      onClose={(_event, reason) => {
        if (reason === "backdropClick") return
        setOpen(false)
      }}
      role="alertdialog"
      maxWidth={false}
      // Same as dialog.jsx: don't let MUI's focus trap kill Radix portals
      // (Select/DropdownMenu) opened from inside the dialog.
      disableEnforceFocus
      aria-labelledby={hasTitle ? titleId : undefined}
      aria-describedby={hasDescription ? descriptionId : undefined}
      slotProps={{
        paper: {
          ref,
          className: cn(
            "grid w-full max-w-lg gap-4 p-6 text-foreground",
            className,
          ),
          sx: solidPanelSx({ radius: RADII.surface }),
          ...props,
        },
        backdrop: {
          className: "bg-foreground/20",
        },
      }}
    >
      {/* Children MUST be MuiDialog JSX children — spreading them into
          slotProps.paper lets MUI's own (empty) child list override them,
          rendering a blank dialog (same gotcha as dialog.jsx, see CLAUDE.md). */}
      {children}
    </MuiDialog>
    </AlertDialogContext.Provider>
  )
})
AlertDialogContent.displayName = "AlertDialogContent"

const AlertDialogHeader = ({ className, ...props }) => (
  <div
    className={cn("flex flex-col space-y-2 text-center sm:text-start", className)}
    {...props}
  />
)
AlertDialogHeader.displayName = "AlertDialogHeader"

const AlertDialogFooter = ({ className, ...props }) => (
  <div
    className={cn("flex flex-col-reverse sm:flex-row sm:justify-end sm:gap-2", className)}
    {...props}
  />
)
AlertDialogFooter.displayName = "AlertDialogFooter"

const AlertDialogTitle = React.forwardRef(({ className, ...props }, ref) => {
  const { titleId, registerTitle } = React.useContext(AlertDialogContext)
  React.useEffect(() => {
    registerTitle(true)
    return () => registerTitle(false)
  }, [registerTitle])
  return (
    <h2
      ref={ref}
      id={titleId}
      className={cn("text-lg font-semibold text-foreground", className)}
      {...props}
    />
  )
})
AlertDialogTitle.displayName = "AlertDialogTitle"

const AlertDialogDescription = React.forwardRef(({ className, ...props }, ref) => {
  const { descriptionId, registerDescription } = React.useContext(AlertDialogContext)
  React.useEffect(() => {
    registerDescription(true)
    return () => registerDescription(false)
  }, [registerDescription])
  return (
    <p
      ref={ref}
      id={descriptionId}
      className={cn("text-sm text-foreground-secondary", className)}
      {...props}
    />
  )
})
AlertDialogDescription.displayName = "AlertDialogDescription"

// Action / Cancel run the consumer's onClick first, then close the dialog —
// mirroring Radix's auto-close-on-select behaviour. Both render the real
// <Button> (Material look). `variant` is forwarded so a destructive confirm
// passes variant="destructive" instead of a buttonVariants className.
const AlertDialogAction = React.forwardRef(
  ({ className, onClick, variant = "default", ...props }, ref) => {
    const { setOpen } = React.useContext(AlertDialogContext)
    const handleClick = (e) => {
      onClick?.(e)
      if (!e.defaultPrevented) setOpen(false)
    }
    return (
      <Button
        ref={ref}
        variant={variant}
        className={cn(className)}
        onClick={handleClick}
        {...props}
      />
    )
  },
)
AlertDialogAction.displayName = "AlertDialogAction"

const AlertDialogCancel = React.forwardRef(
  ({ className, onClick, variant = "outline", ...props }, ref) => {
    const { setOpen } = React.useContext(AlertDialogContext)
    const handleClick = (e) => {
      onClick?.(e)
      if (!e.defaultPrevented) setOpen(false)
    }
    return (
      <Button
        ref={ref}
        variant={variant}
        className={cn("mt-2 sm:mt-0", className)}
        onClick={handleClick}
        {...props}
      />
    )
  },
)
AlertDialogCancel.displayName = "AlertDialogCancel"

export {
  AlertDialog,
  AlertDialogPortal,
  AlertDialogOverlay,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
}

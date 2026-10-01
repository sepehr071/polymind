import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import MuiDialog from "@mui/material/Dialog"
import { X } from "lucide-react"
import { useTranslation } from "react-i18next"

import { cn } from "@/lib/utils"
import { solidPanelSx } from "@/theme/glass"
import { RADII } from "@/theme/tokens"

// ---------------------------------------------------------------------------
// MUI-backed Dialog that preserves the Radix-style compound API.
//
// Consumers keep writing `<Dialog open onOpenChange><DialogTrigger asChild/>
// <DialogContent/></Dialog>` unchanged. Internally a tiny React context relays
// the open state + setter so the Trigger can toggle it and MUI Dialog renders
// the portal/overlay/paper. Portal/Overlay remain exported (the barrel re-emits
// them) but are pass-through shims since MUI's Dialog owns the portal + backdrop.
// ---------------------------------------------------------------------------

const DialogContext = React.createContext({
  open: false,
  setOpen: () => {},
  titleId: undefined,
  descriptionId: undefined,
  // Title/Description register so MuiDialog only references ids that actually
  // render (a dangling aria-labelledby/describedby is itself an a11y defect).
  registerTitle: () => {},
  registerDescription: () => {},
})

const Dialog = ({ open: openProp, defaultOpen = false, onOpenChange, children }) => {
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
  return <DialogContext.Provider value={ctx}>{children}</DialogContext.Provider>
}
Dialog.displayName = "Dialog"

// Trigger: opens the dialog. `asChild` clones the single child (Radix parity);
// otherwise renders a plain <button>.
const DialogTrigger = React.forwardRef(
  ({ asChild = false, onClick, children, ...props }, ref) => {
    const { setOpen } = React.useContext(DialogContext)
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
DialogTrigger.displayName = "DialogTrigger"

// Portal / Overlay: MUI Dialog already renders its own portal + backdrop, so
// these are inert pass-throughs kept only for API + barrel-export parity.
const DialogPortal = ({ children }) => <>{children}</>
DialogPortal.displayName = "DialogPortal"

const DialogOverlay = React.forwardRef(({ className, ...props }, ref) => (
  <div ref={ref} className={className} {...props} />
))
DialogOverlay.displayName = "DialogOverlay"

// Close: any element that should dismiss the dialog (used by DialogContent's
// built-in close button + consumers via <DialogClose asChild>).
const DialogClose = React.forwardRef(
  ({ asChild = false, onClick, children, ...props }, ref) => {
    const { setOpen } = React.useContext(DialogContext)
    const handleClick = (e) => {
      onClick?.(e)
      if (!e.defaultPrevented) setOpen(false)
    }
    const Comp = asChild ? Slot : "button"
    return (
      <Comp ref={ref} onClick={handleClick} {...props}>
        {children}
      </Comp>
    )
  },
)
DialogClose.displayName = "DialogClose"

const DialogContent = React.forwardRef(
  ({ className, children, showClose = true, ...props }, ref) => {
    const { t } = useTranslation("common")
    const { open, setOpen } = React.useContext(DialogContext)
    // Stable ids so MUI Dialog (role="dialog") is labelled/described by the
    // consumer's DialogTitle/DialogDescription — restores screen-reader parity
    // with the Radix original. Title/Description consume these via context and
    // register their presence so we never reference a missing element.
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
      <DialogContext.Provider value={a11yCtx}>
      <MuiDialog
        open={open}
        onClose={() => setOpen(false)}
        maxWidth={false}
        // Radix portals (Select/DropdownMenu content) render OUTSIDE the MUI
        // dialog subtree; MUI's focus trap would yank focus back the instant
        // they open, so Radix dismisses them in the same frame (see the same
        // fix + rationale in popover.jsx). Tab-cycle containment is lost, but
        // working dropdowns inside dialogs win.
        disableEnforceFocus
        aria-labelledby={hasTitle ? titleId : undefined}
        aria-describedby={hasDescription ? descriptionId : undefined}
        slotProps={{
          paper: {
            ref,
            className: cn(
              // Wide-but-capped centered panel. Phones: shrink Paper margins.
              // outline-none: the paper takes programmatic focus on open; the
              // browser default ring on the container reads as a heavy border.
              "relative grid w-[calc(100vw-1rem)] max-w-lg gap-4 p-6 text-foreground outline-none max-sm:mx-2 sm:w-full",
              className,
            ),
            // Solid paper — quiet-glass policy (dialogs not frosted).
            sx: solidPanelSx({ radius: RADII.overlay }),
            ...props,
          },
          backdrop: {
            // hoosh-style backdrop: soft foreground tint + light blur, theme-aware.
            className: "bg-foreground/20",
          },
        }}
      >
        {children}
        {showClose && (
          <button
            type="button"
            onClick={() => setOpen(false)}
            // Phones: full-screen dialogs (e.g. SettingsDialog) push the close X
            // below the safe-area inset and grow it to a ≥40px touch target so it
            // clears the notch + isn't a tiny clipped tap. Desktop unchanged.
            className="absolute end-4 top-4 z-10 grid place-items-center rounded-lg p-1.5 text-foreground-tertiary opacity-70 transition-all hover:opacity-100 hover:bg-background-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none max-sm:h-10 max-sm:w-10 max-sm:top-[max(0.75rem,var(--safe-top))] max-sm:end-3"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">{t("actions.close")}</span>
          </button>
        )}
      </MuiDialog>
      </DialogContext.Provider>
    )
  },
)
DialogContent.displayName = "DialogContent"

const DialogHeader = ({ className, ...props }) => (
  <div
    className={cn("flex flex-col space-y-2 text-center sm:text-start", className)}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

const DialogFooter = ({ className, ...props }) => (
  <div
    className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
    {...props}
  />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = React.forwardRef(({ className, ...props }, ref) => {
  const { titleId, registerTitle } = React.useContext(DialogContext)
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
DialogTitle.displayName = "DialogTitle"

const DialogDescription = React.forwardRef(({ className, ...props }, ref) => {
  const { descriptionId, registerDescription } = React.useContext(DialogContext)
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
DialogDescription.displayName = "DialogDescription"

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}

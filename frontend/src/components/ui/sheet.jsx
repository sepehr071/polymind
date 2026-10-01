"use client";
import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import MuiDrawer from "@mui/material/Drawer"
import { X } from "lucide-react"
import { useTranslation } from "react-i18next"

import { cn } from "@/lib/utils"
import { solidPanelSx } from "@/theme/glass"

// ---------------------------------------------------------------------------
// MUI Drawer-backed Sheet preserving the Radix compound API.
//
// `<Sheet open onOpenChange><SheetTrigger asChild/><SheetContent side className>
// …</SheetContent></Sheet>` keeps working. A context relays open/setter; the
// Trigger opens it; SheetContent renders a MUI Drawer with the side→anchor map.
// `side` accepts physical (top/bottom/left/right) AND logical (start/end) values
// — logical values resolve against the document direction for RTL correctness.
// ---------------------------------------------------------------------------

const SheetContext = React.createContext({
  open: false,
  setOpen: () => {},
  titleId: undefined,
  descriptionId: undefined,
  // Title/Description register so the Drawer paper only references ids that
  // actually render (a dangling aria-labelledby/describedby is an a11y defect).
  registerTitle: () => {},
  registerDescription: () => {},
})

const Sheet = ({ open: openProp, defaultOpen = false, onOpenChange, children }) => {
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
  return <SheetContext.Provider value={ctx}>{children}</SheetContext.Provider>
}
Sheet.displayName = "Sheet"

const SheetTrigger = React.forwardRef(
  ({ asChild = false, onClick, children, ...props }, ref) => {
    const { setOpen } = React.useContext(SheetContext)
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
SheetTrigger.displayName = "SheetTrigger"

const SheetClose = React.forwardRef(
  ({ asChild = false, onClick, children, ...props }, ref) => {
    const { setOpen } = React.useContext(SheetContext)
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
SheetClose.displayName = "SheetClose"

// MUI Drawer owns the portal + backdrop; these stay as inert pass-throughs for
// API + barrel-export parity.
const SheetPortal = ({ children }) => <>{children}</>
SheetPortal.displayName = "SheetPortal"

const SheetOverlay = React.forwardRef(({ className, ...props }, ref) => (
  <div ref={ref} className={className} {...props} />
))
SheetOverlay.displayName = "SheetOverlay"

// Resolve a (possibly logical) side to a physical MUI Drawer anchor.
function resolveAnchor(side) {
  if (side === "start" || side === "end") {
    const rtl =
      typeof document !== "undefined" &&
      document.documentElement.getAttribute("dir") === "rtl"
    if (side === "start") return rtl ? "right" : "left"
    return rtl ? "left" : "right"
  }
  return side === "top" || side === "bottom" || side === "left" || side === "right"
    ? side
    : "right"
}

const SheetContent = React.forwardRef(
  ({ side = "right", className, children, ...props }, ref) => {
    const { t } = useTranslation("common")
    const { open, setOpen } = React.useContext(SheetContext)
    const anchor = resolveAnchor(side)
    const isHorizontal = anchor === "left" || anchor === "right"

    // Stable ids so the sheet panel is labelled/described by the consumer's
    // SheetTitle/SheetDescription — restores screen-reader parity with the
    // Radix original. Set on the Drawer paper (the content region) as role
    // "dialog" + registered so we never reference a missing element.
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
      <SheetContext.Provider value={a11yCtx}>
      <MuiDrawer
        anchor={anchor}
        open={open}
        onClose={() => setOpen(false)}
        slotProps={{
          paper: {
            ref,
            role: "dialog",
            "aria-modal": true,
            "aria-labelledby": hasTitle ? titleId : undefined,
            "aria-describedby": hasDescription ? descriptionId : undefined,
            className: cn(
              // No `relative` here: Tailwind wins over MUI (emotion prepend),
              // so it would override the Drawer paper's `position: fixed`.
              "gap-4 p-6 text-foreground",
              isHorizontal ? "w-3/4 sm:max-w-sm" : "w-full",
              className,
            ),
            sx: solidPanelSx({ radius: 0 }),
            ...props,
          },
          backdrop: {
            className: "bg-foreground/20",
          },
        }}
      >
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="absolute end-4 top-4 rounded-lg p-1.5 text-foreground-tertiary opacity-70 transition-all hover:opacity-100 hover:bg-background-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none"
        >
          <X className="h-4 w-4" />
          <span className="sr-only">{t("aria.close")}</span>
        </button>
        {children}
      </MuiDrawer>
      </SheetContext.Provider>
    )
  },
)
SheetContent.displayName = "SheetContent"

const SheetHeader = ({ className, ...props }) => (
  <div
    className={cn("flex flex-col space-y-2 text-center sm:text-start", className)}
    {...props}
  />
)
SheetHeader.displayName = "SheetHeader"

const SheetFooter = ({ className, ...props }) => (
  <div
    className={cn("flex flex-col-reverse sm:flex-row sm:justify-end sm:gap-2", className)}
    {...props}
  />
)
SheetFooter.displayName = "SheetFooter"

const SheetTitle = React.forwardRef(({ className, ...props }, ref) => {
  const { titleId, registerTitle } = React.useContext(SheetContext)
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
SheetTitle.displayName = "SheetTitle"

const SheetDescription = React.forwardRef(({ className, ...props }, ref) => {
  const { descriptionId, registerDescription } = React.useContext(SheetContext)
  React.useEffect(() => {
    registerDescription(true)
    return () => registerDescription(false)
  }, [registerDescription])
  return (
    <p
      ref={ref}
      id={descriptionId}
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
})
SheetDescription.displayName = "SheetDescription"

export {
  Sheet,
  SheetPortal,
  SheetOverlay,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
}

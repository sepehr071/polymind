import * as React from "react"

import { cn } from "@/lib/utils"
import { solidPanelSx } from "@/theme/glass"
import MuiPopover from "@mui/material/Popover"

// ---------------------------------------------------------------------------
// MUI-backed Popover preserving the Radix compound API.
//
// `<Popover open onOpenChange><PopoverTrigger asChild/><PopoverContent
// side align sideOffset/></Popover>` keeps working. A context relays the open
// state, the setter, and the trigger's anchor element (captured via a merged
// ref on the trigger child) into MUI Popover. PopoverAnchor lets a consumer
// designate a different anchor element (kept for API parity; unused today).
// ---------------------------------------------------------------------------

const PopoverContext = React.createContext({
  open: false,
  setOpen: () => {},
  anchorRef: { current: null },
  setAnchorEl: () => {},
})

// Merge a parent-provided ref with our internal one (refs can be fn or object).
function setRef(ref, value) {
  if (typeof ref === "function") ref(value)
  else if (ref != null) ref.current = value
}

const Popover = ({ open: openProp, defaultOpen = false, onOpenChange, children }) => {
  const isControlled = openProp !== undefined
  const [uncontrolled, setUncontrolled] = React.useState(defaultOpen)
  const open = isControlled ? openProp : uncontrolled
  // `anchorEl` is tracked in state so MUI Popover re-reads it once the trigger
  // mounts; `anchorRef` lets PopoverAnchor override the default trigger anchor.
  const [anchorEl, setAnchorEl] = React.useState(null)
  const anchorRef = React.useRef(null)

  const setOpen = React.useCallback(
    (next) => {
      if (!isControlled) setUncontrolled(next)
      onOpenChange?.(next)
    },
    [isControlled, onOpenChange],
  )

  const ctx = React.useMemo(
    () => ({ open, setOpen, anchorEl, setAnchorEl, anchorRef }),
    [open, setOpen, anchorEl],
  )
  return <PopoverContext.Provider value={ctx}>{children}</PopoverContext.Provider>
}
Popover.displayName = "Popover"

const PopoverTrigger = React.forwardRef(
  ({ asChild = false, onClick, children, ...props }, ref) => {
    const { setOpen, setAnchorEl, anchorRef } = React.useContext(PopoverContext)

    const captureRef = React.useCallback(
      (node) => {
        anchorRef.current = node
        setAnchorEl(node)
        setRef(ref, node)
      },
      [ref, anchorRef, setAnchorEl],
    )

    if (asChild && React.isValidElement(children)) {
      return React.cloneElement(children, {
        ...props,
        ref: (node) => {
          captureRef(node)
          // Preserve the child's own ref (string refs unsupported — fine).
          setRef(children.ref, node)
        },
        onClick: (e) => {
          // Fire the child's own handler, this trigger's handler, then open.
          children.props.onClick?.(e)
          onClick?.(e)
          if (!e.defaultPrevented) setOpen(true)
        },
      })
    }

    const handleButtonClick = (e) => {
      onClick?.(e)
      if (!e.defaultPrevented) setOpen(true)
    }
    return (
      <button ref={captureRef} onClick={handleButtonClick} {...props}>
        {children}
      </button>
    )
  },
)
PopoverTrigger.displayName = "PopoverTrigger"

// Optional explicit anchor element. Designates `anchorRef` so PopoverContent
// positions against it instead of the trigger. Kept for Radix API parity.
const PopoverAnchor = React.forwardRef(({ asChild = false, children, ...props }, ref) => {
  const { anchorRef, setAnchorEl } = React.useContext(PopoverContext)
  const captureRef = React.useCallback(
    (node) => {
      anchorRef.current = node
      setAnchorEl(node)
      setRef(ref, node)
    },
    [ref, anchorRef, setAnchorEl],
  )
  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children, { ref: captureRef, ...props })
  }
  return (
    <span ref={captureRef} {...props}>
      {children}
    </span>
  )
})
PopoverAnchor.displayName = "PopoverAnchor"

// Map Radix side/align onto MUI anchor/transform origins. `sideOffset` is fed
// to MUI via anchorOrigin offset (handled by a sx margin on the paper).
const SIDE_ANCHOR = {
  top: { vertical: "top", horizontal: "center" },
  bottom: { vertical: "bottom", horizontal: "center" },
  left: { vertical: "center", horizontal: "left" },
  right: { vertical: "center", horizontal: "right" },
}
const SIDE_TRANSFORM = {
  top: { vertical: "bottom", horizontal: "center" },
  bottom: { vertical: "top", horizontal: "center" },
  left: { vertical: "center", horizontal: "right" },
  right: { vertical: "center", horizontal: "left" },
}
// align overrides the cross-axis on top/bottom sides.
const ALIGN_HORIZONTAL = { start: "left", center: "center", end: "right" }

const PopoverContent = React.forwardRef(
  ({ className, align = "center", side = "bottom", sideOffset = 4, style, children, ...props }, ref) => {
    const { open, setOpen, anchorEl } = React.useContext(PopoverContext)

    const anchorOrigin = { ...(SIDE_ANCHOR[side] || SIDE_ANCHOR.bottom) }
    const transformOrigin = { ...(SIDE_TRANSFORM[side] || SIDE_TRANSFORM.bottom) }
    if (side === "top" || side === "bottom") {
      anchorOrigin.horizontal = ALIGN_HORIZONTAL[align] || "center"
      transformOrigin.horizontal = ALIGN_HORIZONTAL[align] || "center"
    } else {
      // left/right sides: align controls the vertical edge.
      const v = align === "start" ? "top" : align === "end" ? "bottom" : "center"
      anchorOrigin.vertical = v
      transformOrigin.vertical = v
    }

    // sideOffset → push the paper away from the anchor along the active side.
    const offsetSx =
      side === "bottom"
        ? { mt: `${sideOffset}px` }
        : side === "top"
        ? { mb: `${sideOffset}px` }
        : side === "right"
        ? { ml: `${sideOffset}px` }
        : { mr: `${sideOffset}px` }

    return (
      <MuiPopover
        open={open}
        anchorEl={anchorEl}
        onClose={() => setOpen(false)}
        anchorOrigin={anchorOrigin}
        transformOrigin={transformOrigin}
        // Behave like a lightweight Radix popover, not a modal dialog:
        // no body scroll-lock (was causing a layout jump on every open) and
        // no focus trap (let cmdk/content own focus).
        disableScrollLock
        disableAutoFocus
        disableEnforceFocus
        slotProps={{
          paper: {
            ...props,
            ref,
            style,
            className: cn(
              "w-72 p-4 text-foreground overflow-visible",
              className,
              props.className,
            ),
            sx: { ...solidPanelSx({ radius: 8 }), ...offsetSx, ...(props.sx || {}) },
          },
        }}
      >
        {children}
      </MuiPopover>
    )
  },
)
PopoverContent.displayName = "PopoverContent"

export { Popover, PopoverTrigger, PopoverContent, PopoverAnchor }

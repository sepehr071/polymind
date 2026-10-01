import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import MuiTooltip from "@mui/material/Tooltip"

import { cn } from "@/lib/utils"

// ---------------------------------------------------------------------------
// MUI-backed Tooltip preserving the Radix compound API.
//
// `<TooltipProvider><Tooltip delayDuration><TooltipTrigger asChild>{el}
// </TooltipTrigger><TooltipContent side className>{title}</TooltipContent>
// </Tooltip></TooltipProvider>` keeps working. `Tooltip` walks its children to
// pull the trigger element + the title (TooltipContent's children) and renders a
// single MUI Tooltip. TooltipProvider is a pass-through (MUI needs no provider).
//
// Real-MUI behaviour restored:
//  - MUI Tooltip never fires on a DISABLED child (disabled DOM elements emit no
//    pointer/focus events). We detect a disabled trigger and wrap it in a
//    focusable <span> so hover + keyboard-focus tooltips work (Send button,
//    web-search toggle, MessageActions, etc.).
//  - `asChild` triggers that aren't natively focusable (e.g. an animated
//    motion.div, a plain span) get `tabIndex={0}` so the focus-triggered
//    tooltip is reachable by keyboard.
//  - Nested compound triggers (TooltipTrigger > PopoverTrigger, or the reverse
//    in the collapsed WorkspaceSwitcher) are unwrapped so MUI gets the deepest
//    real element while the intermediate Radix-style triggers keep forwarding
//    their ref + onClick down the chain.
// ---------------------------------------------------------------------------

const TooltipProvider = ({ children }) => <>{children}</>
TooltipProvider.displayName = "TooltipProvider"

// Trigger: renders its child (asChild) or a span wrapper. MUI Tooltip attaches
// hover/focus listeners + a ref to whatever this returns, so `asChild` uses Slot
// to forward them onto the consumer's element.
const TooltipTrigger = React.forwardRef(({ asChild = false, children, ...props }, ref) => {
  const Comp = asChild ? Slot : "span"
  return (
    <Comp ref={ref} {...props}>
      {children}
    </Comp>
  )
})
TooltipTrigger.displayName = "TooltipTrigger"

// Content is NOT rendered directly — `Tooltip` reads its props (className/side)
// + children to build the MUI tooltip label. Returning null keeps it inert if
// it ever renders standalone.
const TooltipContent = React.forwardRef(({ className, sideOffset, children, side, ...props }, ref) => {
  return null
})
TooltipContent.displayName = "TooltipContent"

const SIDE_TO_PLACEMENT = {
  top: "top",
  bottom: "bottom",
  left: "left",
  right: "right",
}

// Our own compound markers + the Radix Slot are pass-throughs that forward
// props/ref to a single child. To know whether the *real* trigger is disabled
// or natively focusable we drill through them to the first concrete element.
const PASS_THROUGH_DISPLAY_NAMES = new Set([
  "TooltipTrigger",
  "PopoverTrigger",
  "DropdownMenuTrigger",
  "PopoverAnchor",
])

function isPassThroughWrapper(el) {
  if (!React.isValidElement(el)) return false
  if (el.type === Slot) return true
  const name = el.type?.displayName || el.type?.name
  return typeof name === "string" && PASS_THROUGH_DISPLAY_NAMES.has(name)
}

// Walk down single-child wrappers (our markers / Slot) to the deepest concrete
// element — the thing that actually renders a DOM node.
function resolveDeepestElement(el) {
  let current = el
  // Guard against pathological cycles; trigger chains are 1-3 deep in practice.
  for (let i = 0; i < 8; i += 1) {
    if (!React.isValidElement(current)) return current
    const child = current.props?.children
    if (isPassThroughWrapper(current) && React.isValidElement(child)) {
      current = child
      continue
    }
    return current
  }
  return current
}

// Natively focusable intrinsic tags — these receive keyboard focus without
// help, so a focus-triggered tooltip already works.
const NATIVELY_FOCUSABLE = new Set(["button", "a", "input", "select", "textarea"])

function isNativelyFocusable(el) {
  if (!React.isValidElement(el)) return false
  if (el.props?.disabled) return false
  if (typeof el.type === "string") {
    if (NATIVELY_FOCUSABLE.has(el.type)) return true
    if (el.type === "a") return el.props?.href != null
  }
  // Custom components / motion.* / divs: assume not natively focusable unless
  // the consumer already set a tabIndex or it is an explicit anchor.
  return el.props?.tabIndex != null && el.props.tabIndex >= 0
}

const Tooltip = ({ children, delayDuration, open, defaultOpen, onOpenChange, disableHoverableContent, ...rest }) => {
  // Split children into the trigger element and the content descriptor.
  let triggerEl = null
  let contentProps = null
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return
    if (child.type === TooltipContent) {
      contentProps = child.props
    } else if (child.type === TooltipTrigger) {
      triggerEl = child
    } else if (triggerEl == null) {
      // Fallback: first non-content child is treated as the trigger. This is the
      // collapsed-WorkspaceSwitcher case where PopoverTrigger wraps the
      // TooltipTrigger — the wrapper IS the trigger element MUI must clone (it
      // forwards ref + handlers down to the real button via Slot).
      triggerEl = child
    }
  })

  if (!triggerEl) return null

  const title = contentProps ? contentProps.children : ""
  const placement = SIDE_TO_PLACEMENT[contentProps?.side] || "top"

  // Drill to the deepest real element to inspect disabled / focusable state.
  // MUI still clones `triggerEl` (the outermost wrapper) so the whole compound
  // chain keeps relaying ref + onClick to the underlying DOM node.
  const deepest = resolveDeepestElement(triggerEl)
  const deepestDisabled = Boolean(React.isValidElement(deepest) && deepest.props?.disabled)
  const deepestFocusable = isNativelyFocusable(deepest)

  let child = triggerEl
  // String tooltip -> accessible name when trigger has none (icon-only buttons).
  const titleText = typeof title === "string" ? title.trim() : ""
  const elHasName = (el) => Boolean(
    React.isValidElement(el) && (
      el.props?.["aria-label"] ||
      el.props?.["aria-labelledby"] ||
      (typeof el.props?.children === "string" && el.props.children.trim())
    )
  )
  // 1) Disabled trigger: MUI gets no events from a disabled element. Wrap it in
  //    a focusable span so hover + keyboard focus surface the tooltip.
  if (deepestDisabled) {
    child = (
      <span
        tabIndex={0}
        style={{ display: "inline-flex" }}
        aria-label={!elHasName(deepest) && titleText ? titleText : undefined}
      >
        {triggerEl}
      </span>
    )
  } else if (React.isValidElement(triggerEl)) {
    // 2) Non-focusable asChild: tabIndex. 3) Nameless icon: title -> aria-label.
    const patch = {}
    if (!deepestFocusable) {
      patch.tabIndex = triggerEl.props?.tabIndex ?? 0
    }
    if (titleText && !elHasName(triggerEl) && !elHasName(deepest)) {
      patch["aria-label"] = titleText
    }
    if (Object.keys(patch).length > 0) {
      child = React.cloneElement(triggerEl, patch)
    }
  }

  const controlledProps = {}
  if (open !== undefined) {
    controlledProps.open = open
    controlledProps.onOpen = () => onOpenChange?.(true)
    controlledProps.onClose = () => onOpenChange?.(false)
  } else if (onOpenChange) {
    controlledProps.onOpen = () => onOpenChange?.(true)
    controlledProps.onClose = () => onOpenChange?.(false)
  }

  return (
    <MuiTooltip
      title={title}
      placement={placement}
      enterDelay={typeof delayDuration === "number" ? delayDuration : 100}
      enterNextDelay={typeof delayDuration === "number" ? delayDuration : 100}
      disableInteractive={disableHoverableContent}
      slotProps={{
        tooltip: {
          // Look is owned by the theme MuiTooltip styleOverrides (glass surface,
          // radius, colour, padding) — ONE tooltip look. We only forward the
          // consumer's className + relax MUI's narrow default so multi-line
          // tooltips don't wrap awkwardly.
          className: cn(contentProps?.className),
          sx: { maxWidth: "none", m: 0 },
        },
      }}
      {...rest}
      {...controlledProps}
    >
      {child}
    </MuiTooltip>
  )
}
Tooltip.displayName = "Tooltip"

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }

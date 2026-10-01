import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva } from "class-variance-authority"
import MuiButton from "@mui/material/Button"
import MuiIconButton from "@mui/material/IconButton"

import { cn } from "@/lib/utils"

// visuals owned by createAppTheme (MuiButton) — the standalone <Button> renders
// real Material. buttonVariants now backs ONLY the `asChild` Slot path, where a
// link/anchor (e.g. `<Button asChild><Link/></Button>`) borrows the button look
// via these classes (Slot can't mount a MuiButton). External standalone callers
// were migrated to <Button>; alert-dialog Action/Cancel render <Button> too.
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-primary-glow hover:bg-primary-dark hover:shadow-primary-glow-lg active:scale-95",
        destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline: "border border-border bg-background shadow-sm hover:bg-background-tertiary hover:text-foreground",
        secondary: "bg-background-tertiary text-foreground shadow-sm hover:bg-background-elevated border border-border",
        ghost: "hover:bg-background-tertiary hover:text-foreground text-foreground-secondary",
        link: "text-accent underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-11 rounded-lg px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

// Map the cva variant/size onto the closest MUI semantics. The cva classes
// override visuals regardless, but these keep MUI's internal state classes
// (color, size) coherent.
const VARIANT_MAP = {
  default: "contained",
  destructive: "contained",
  outline: "outlined",
  secondary: "outlined",
  ghost: "text",
  link: "text",
}
const COLOR_MAP = {
  destructive: "error",
  link: "primary",
}
const SIZE_MAP = {
  default: "medium",
  sm: "small",
  lg: "large",
  icon: "medium",
}

// Micro-interaction (hover scale 1.02 / active scale 0.98) driven by CSS, not
// framer-motion — keeps this app-wide primitive out of the entry bundle. The
// global reduce-motion rule in index.css freezes the transition automatically.
// `transform-gpu` promotes to a layer so the scale tween stays smooth; the
// transform composites without triggering layout (so the design law against
// animating layout properties holds).
const ANIMATED_CLASS =
  "transition-transform duration-150 ease-out transform-gpu hover:scale-[1.02] active:scale-[0.98]"

const Button = React.forwardRef(({
  className,
  variant,
  size,
  asChild = false,
  animated = false,
  ...props
}, ref) => {
  // asChild renders a Slot so the consumer's child element receives the classes
  // (no MUI/motion wrapper) — preserves the original passthrough contract.
  if (asChild) {
    return (
      <Slot
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }

  // Material look now comes from MUI variant/color/size + the theme (not cva), so
  // buttons read as real Material. Only the consumer's className is forwarded
  // (layout utilities like w-full). buttonVariants stays exported for the few
  // non-MUI consumers (alert-dialog/sheet/KnowledgeFolderSidebar).
  const classes = cn(className)

  // Icon buttons back onto MUI IconButton (square, centered, ripple).
  if (size === "icon") {
    return (
      <MuiIconButton
        className={cn(animated && !props.disabled && ANIMATED_CLASS, classes)}
        ref={ref}
        color={COLOR_MAP[variant] ?? "default"}
        {...props}
      />
    )
  }

  // animated adds the CSS hover/tap scale micro-interaction (disabled buttons
  // get no animation, matching the prior framer-motion gate).
  const muiProps = {
    variant: VARIANT_MAP[variant] ?? "contained",
    color: COLOR_MAP[variant] ?? "primary",
    size: SIZE_MAP[size] ?? "medium",
    className: cn(animated && !props.disabled && ANIMATED_CLASS, classes),
    ref,
    ...props,
  }

  return <MuiButton {...muiProps} />
})
Button.displayName = "Button"

export { Button, buttonVariants }

import * as React from "react"
import { cva } from "class-variance-authority"
import MuiSwitch from "@mui/material/Switch"

import { cn } from "@/lib/utils"

// visuals owned by createAppTheme (MuiSwitch) — layout classes only here.
// `switchVariants` is kept exported (the barrel re-exports it) for API parity;
// the dead colour blocks (track fill per state) were dropped since the MUI theme
// drives them. Retained so any consumer importing it keeps working.
const switchVariants = cva(
  "peer inline-flex shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "",
        success: "",
      },
      size: {
        sm: "h-4 w-7",
        default: "h-5 w-9",
        lg: "h-6 w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

// MUI has only small|medium; map the legacy sm/default/lg scale onto it.
const SIZE_MAP = { sm: "small", default: "medium", lg: "medium" }
const COLOR_MAP = { default: "primary", success: "success" }

// MUI-backed adapter. Keeps the Radix-shaped API: `checked` +
// `onCheckedChange(bool)`, plus `variant`/`size`/`disabled`/`id`. MUI handles
// the RTL thumb flip automatically (no manual rtl translate needed).
const Switch = React.forwardRef(
  ({ className, variant = "default", size = "default", onCheckedChange, onChange, ...props }, ref) => (
    <MuiSwitch
      ref={ref}
      className={cn(className)}
      color={COLOR_MAP[variant] ?? "primary"}
      size={SIZE_MAP[size] ?? "medium"}
      onChange={(event, checked) => {
        onChange?.(event, checked)
        onCheckedChange?.(checked)
      }}
      {...props}
    />
  )
)
Switch.displayName = "Switch"

export { Switch, switchVariants }

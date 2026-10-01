"use client"

import * as React from "react"
import { cva } from "class-variance-authority"
import MuiToggleButton from "@mui/material/ToggleButton"

import { cn } from "@/lib/utils"

// visuals owned by createAppTheme (MuiToggleButton) — layout classes only here.
// `toggleVariants` is kept exported for API parity (consumers / toggle-group
// reuse it). The dead hover/selected/colour blocks were dropped since the MUI
// theme drives them; layout + sizing remain so any importer keeps working.
const toggleVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "",
        outline: "",
      },
      size: {
        default: "h-10 px-2 min-w-10",
        sm: "h-8 px-1.5 min-w-8",
        lg: "h-11 px-2.5 min-w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

const SIZE_MAP = { sm: "small", default: "medium", lg: "large" }

// MUI-backed adapter. Keeps the Radix-shaped API: `pressed` /
// `defaultPressed` / `onPressedChange(bool)`, plus `variant`/`size`/`disabled`.
// MUI ToggleButton requires a `value`; default to a sentinel for standalone use.
const Toggle = React.forwardRef(
  (
    {
      className,
      variant = "default",
      size = "default",
      pressed,
      defaultPressed,
      onPressedChange,
      onChange,
      value = "on",
      selected,
      ...props
    },
    ref
  ) => {
    const isSelected = selected ?? pressed ?? defaultPressed
    return (
      <MuiToggleButton
        ref={ref}
        className={cn(className)}
        value={value}
        size={SIZE_MAP[size] ?? "medium"}
        selected={isSelected}
        onChange={(event) => {
          onChange?.(event)
          onPressedChange?.(!isSelected)
        }}
        {...props}
      />
    )
  }
)
Toggle.displayName = "Toggle"

export { Toggle, toggleVariants }

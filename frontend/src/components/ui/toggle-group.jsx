"use client"

import * as React from "react"
import MuiToggleButtonGroup from "@mui/material/ToggleButtonGroup"
import MuiToggleButton from "@mui/material/ToggleButton"

import { cn } from "@/lib/utils"
import { toggleVariants } from "@/components/ui/toggle"

// MUI-backed adapters mirroring the shadcn/Radix ToggleGroup API:
// ToggleGroup: `type` ('single'|'multiple') / `value` / `onValueChange` /
//   `variant` / `size` / `disabled`.
// ToggleGroupItem: `value` (rendered as a MUI ToggleButton).
// Variant/size propagate to items via context, like the shadcn original.
const ToggleGroupContext = React.createContext({
  variant: "default",
  size: "default",
})

const SIZE_MAP = { sm: "small", default: "medium", lg: "large" }

const ToggleGroup = React.forwardRef(
  (
    {
      className,
      variant = "default",
      size = "default",
      type = "single",
      value,
      defaultValue,
      onValueChange,
      onChange,
      children,
      ...props
    },
    ref
  ) => {
    const exclusive = type === "single"
    return (
      <MuiToggleButtonGroup
        ref={ref}
        className={cn("flex items-center justify-center gap-1", className)}
        exclusive={exclusive}
        value={value}
        size={SIZE_MAP[size] ?? "medium"}
        onChange={(event, next) => {
          onChange?.(event, next)
          onValueChange?.(next)
        }}
        {...props}
      >
        <ToggleGroupContext.Provider value={{ variant, size }}>
          {children}
        </ToggleGroupContext.Provider>
      </MuiToggleButtonGroup>
    )
  }
)
ToggleGroup.displayName = "ToggleGroup"

const ToggleGroupItem = React.forwardRef(
  ({ className, variant, size, value, children, ...props }, ref) => {
    const context = React.useContext(ToggleGroupContext)
    const resolvedSize = size ?? context.size
    return (
      <MuiToggleButton
        ref={ref}
        className={cn(className)}
        value={value}
        size={SIZE_MAP[resolvedSize] ?? "medium"}
        {...props}
      >
        {children}
      </MuiToggleButton>
    )
  }
)
ToggleGroupItem.displayName = "ToggleGroupItem"

export { ToggleGroup, ToggleGroupItem, toggleVariants }

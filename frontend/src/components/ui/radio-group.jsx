import * as React from "react"
import MuiRadioGroup from "@mui/material/RadioGroup"
import MuiRadio from "@mui/material/Radio"

import { cn } from "@/lib/utils"

// MUI-backed adapters that keep the Radix-shaped API:
// RadioGroup: `value` / `onValueChange(value)` / `defaultValue` / `name`.
// RadioGroupItem: `value` (rendered as a MUI Radio).
// className passthrough preserved so Tailwind layout utilities still win.
const RadioGroup = React.forwardRef(
  ({ className, onValueChange, onChange, ...props }, ref) => {
    return (
      <MuiRadioGroup
        ref={ref}
        className={cn("grid gap-2", className)}
        onChange={(event, value) => {
          onChange?.(event, value)
          onValueChange?.(value)
        }}
        {...props}
      />
    )
  }
)
RadioGroup.displayName = "RadioGroup"

const RadioGroupItem = React.forwardRef(({ className, ...props }, ref) => {
  return (
    <MuiRadio ref={ref} className={cn(className)} size="small" {...props} />
  )
})
RadioGroupItem.displayName = "RadioGroupItem"

export { RadioGroup, RadioGroupItem }

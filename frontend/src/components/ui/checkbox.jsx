"use client"

import * as React from "react"
import MuiCheckbox from "@mui/material/Checkbox"

import { cn } from "@/lib/utils"

// MUI-backed adapter. Preserves the Radix-shaped API consumers depend on:
// `checked` + `onCheckedChange(bool)`, plus `disabled`/`id`/`className`.
// className passthrough is kept so Tailwind layout utilities still win
// (emotion cache prepends MUI styles).
const Checkbox = React.forwardRef(
  ({ className, onCheckedChange, onChange, ...props }, ref) => (
    <MuiCheckbox
      ref={ref}
      className={cn(className)}
      size="small"
      onChange={(event, checked) => {
        onChange?.(event, checked)
        onCheckedChange?.(checked)
      }}
      {...props}
    />
  )
)
Checkbox.displayName = "Checkbox"

export { Checkbox }

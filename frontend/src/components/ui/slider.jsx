"use client"

import * as React from "react"
import MuiSlider from "@mui/material/Slider"

import { cn } from "@/lib/utils"

// MUI-backed adapter. Keeps the Radix-shaped array API consumers depend on:
// `value={[n]}` / `defaultValue={[n]}` / `onValueChange([n])`, plus
// `min`/`max`/`step`/`disabled`. Single-element arrays are unwrapped to a
// scalar for MUI's controlled value and re-wrapped to an array on change, so
// both single-thumb and range usage round-trip identically.
const toMuiValue = (v) =>
  Array.isArray(v) ? (v.length === 1 ? v[0] : v) : v

const toArrayValue = (v) => (Array.isArray(v) ? v : [v])

const Slider = React.forwardRef(
  ({ className, value, defaultValue, onValueChange, onChange, ...props }, ref) => (
    <MuiSlider
      ref={ref}
      className={cn("w-full", className)}
      value={value !== undefined ? toMuiValue(value) : undefined}
      defaultValue={defaultValue !== undefined ? toMuiValue(defaultValue) : undefined}
      onChange={(event, next, activeThumb) => {
        onChange?.(event, next, activeThumb)
        onValueChange?.(toArrayValue(next))
      }}
      {...props}
    />
  )
)
Slider.displayName = "Slider"

export { Slider }

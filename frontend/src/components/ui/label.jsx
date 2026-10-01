import * as React from "react"
import * as LabelPrimitive from "@radix-ui/react-label"
import { cva } from "class-variance-authority";
import MuiFormLabel from "@mui/material/FormLabel"

import { cn } from "@/lib/utils"

const labelVariants = cva(
  "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
)

// Backed by MUI FormLabel (renders a native <label>, so `htmlFor` + native attrs
// pass through unchanged). Visuals come from the cva classes + consumer
// className (emotion cache `prepend:true` → Tailwind wins). FormLabel's own
// theme color is neutralized to `inherit` so the original radix behaviour of
// inheriting the surrounding text color is preserved (consumers that want a
// specific color set it via className, e.g. `text-muted-foreground`).
// displayName is kept byte-identical to the original (radix Root's displayName).
const Label = React.forwardRef(({ className, ...props }, ref) => (
  <MuiFormLabel
    ref={ref}
    component="label"
    className={cn(labelVariants(), className)}
    sx={{
      color: "inherit",
      "&.Mui-focused": { color: "inherit" },
      "&.Mui-error": { color: "inherit" },
    }}
    {...props}
  />
))
Label.displayName = LabelPrimitive.Root.displayName

export { Label }

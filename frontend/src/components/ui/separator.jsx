import * as React from "react"
import MuiDivider from "@mui/material/Divider"

import { cn } from "@/lib/utils"

const Separator = React.forwardRef((
  { className, orientation = "horizontal", decorative = true, ...props },
  ref
) => (
  // Backed by MUI Divider. `decorative` maps to ARIA: a decorative separator is
  // hidden from the a11y tree (role="presentation"); a semantic one keeps
  // role="separator" + aria-orientation. The cva-free utility classes win
  // (emotion prepend:true) so the bg/size match the prior radix version.
  <MuiDivider
    ref={ref}
    orientation={orientation}
    flexItem={orientation === "vertical"}
    role={decorative ? "presentation" : "separator"}
    aria-orientation={decorative ? undefined : orientation}
    aria-hidden={decorative ? true : undefined}
    className={cn(
      "shrink-0 bg-border border-0",
      orientation === "horizontal" ? "h-[1px] w-full" : "h-full w-[1px]",
      className
    )}
    {...props}
  />
))
Separator.displayName = "Separator"

export { Separator }

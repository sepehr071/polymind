import * as React from "react"
import { cva } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  {
    variants: {
      variant: {
        default: "bg-accent/20 text-accent",
        secondary: "bg-background-tertiary text-foreground-secondary border border-border",
        destructive: "bg-destructive/20 text-destructive",
        success: "bg-success/20 text-success",
        warning: "bg-warning/20 text-warning",
        outline: "border border-border text-foreground-secondary",
        accent: "bg-accent text-accent-foreground",
        // Role/auth status tones — reuse the shared --role-* palette so member
        // status chips match RoleBadge without re-implementing the pill.
        roleEditor: "bg-role-editor-bg text-role-editor-fg border border-role-editor-line",
        roleViewer: "bg-role-viewer-bg text-role-viewer-fg border border-role-viewer-line",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

// A static pill — a styled <span>, not MUI Chip (Chip's `label` indirection put
// consumer icon/gap/padding classes on the wrong node). Children render directly
// so inline-flex/gap/icon utilities apply correctly.
function Badge({ className, variant, ...props }) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }

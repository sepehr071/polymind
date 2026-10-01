"use client"

import * as React from "react"
import MuiLinearProgress from "@mui/material/LinearProgress"
import { cva } from "class-variance-authority"

import { cn } from "@/lib/utils"

const progressVariants = cva(
  "relative w-full overflow-hidden rounded-full",
  {
    variants: {
      variant: {
        default: "bg-accent/20",
        success: "bg-success/20",
        warning: "bg-warning/20",
        error: "bg-error/20",
      },
      size: {
        sm: "h-1",
        default: "h-2",
        lg: "h-3",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

const indicatorVariants = cva(
  "h-full w-full flex-1 transition-all duration-300 ease-out",
  {
    variants: {
      variant: {
        default: "bg-accent",
        success: "bg-success",
        warning: "bg-warning",
        error: "bg-error",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

const Progress = React.forwardRef(({ className, value, variant, size, showValue, ...props }, ref) => {
  // Backed by MUI LinearProgress (determinate). RTL is handled by MUI direction
  // + the dir-keyed emotion cache, so no manual translateX flip is needed. The
  // cva track classes (rounded-full + variant bg + size height) win via emotion
  // prepend:true; the bar (indicator) colour comes from indicatorVariants.
  return (
    <div className={cn("relative", showValue && "flex items-center gap-2")}>
      <MuiLinearProgress
        ref={ref}
        variant="determinate"
        value={value || 0}
        className={cn(progressVariants({ variant, size }), className)}
        sx={{
          backgroundColor: "transparent",
          borderRadius: "9999px",
          "& .MuiLinearProgress-bar": {
            transition: "transform 300ms ease-out",
          },
        }}
        classes={{ bar: cn(indicatorVariants({ variant })) }}
        {...props}
      />
      {showValue && (
        <span className="text-xs font-medium text-foreground-secondary min-w-[3ch]">
          {Math.round(value || 0)}%
        </span>
      )}
    </div>
  )
})
Progress.displayName = "Progress"

export { Progress, progressVariants }

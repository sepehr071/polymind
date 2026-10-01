import * as React from "react"
import MuiSkeleton from "@mui/material/Skeleton"

import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }) {
  // Backed by MUI Skeleton. MUI's own wave/pulse + theme bg are disabled so the
  // shared `.animate-shimmer` gradient (over --background-tertiary/secondary
  // tokens, reduce-motion-whitelisted) drives the visual. No `bg-*` here — the
  // gradient is the surface (emotion prepend:true keeps utility classes
  // authoritative).
  return (
    <MuiSkeleton
      variant="rounded"
      animation={false}
      className={cn(
        "animate-shimmer rounded-lg",
        className
      )}
      sx={{ bgcolor: "transparent", transform: "none" }}
      {...props}
    />
  )
}

// Pre-built skeleton variants for common use cases
function SkeletonText({ className, lines = 1, ...props }) {
  return (
    <div className={cn("space-y-2", className)} {...props}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-4", i === lines - 1 && lines > 1 && "w-3/4")}
        />
      ))}
    </div>
  )
}

function SkeletonAvatar({ className, size = "default", ...props }) {
  const sizes = {
    sm: "h-8 w-8",
    default: "h-10 w-10",
    lg: "h-12 w-12",
    xl: "h-16 w-16",
  }

  return (
    <Skeleton
      className={cn("rounded-full", sizes[size], className)}
      {...props}
    />
  )
}

function SkeletonCard({ className, ...props }) {
  return (
    <div className={cn("rounded-xl border border-border p-5 space-y-4", className)} {...props}>
      <div className="flex items-center space-x-4">
        <SkeletonAvatar />
        <div className="space-y-2 flex-1">
          <Skeleton className="h-4 w-1/4" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
      <SkeletonText lines={3} />
    </div>
  )
}

function SkeletonMessage({ className, isUser = false, ...props }) {
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse", className)} {...props}>
      <SkeletonAvatar size="sm" />
      <div className={cn("space-y-2 max-w-[70%]", isUser && "items-end")}>
        <Skeleton className="h-20 w-64 rounded-xl" />
      </div>
    </div>
  )
}

export { Skeleton, SkeletonText, SkeletonAvatar, SkeletonCard, SkeletonMessage }

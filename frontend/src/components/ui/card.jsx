import * as React from "react"
import { cva } from "class-variance-authority"
import MuiCard from "@mui/material/Card"

import { cn } from "@/lib/utils"

// visuals owned by createAppTheme — layout classes only here.
// Kept for API parity (a few consumers import cardVariants). The Card surface
// (border/elevation/radius/background) is driven by the MUI Card theme; this cva
// only carries layout. NOTE: `glass` was removed — content cards are plain
// surfaces (glass belongs to chrome/overlays only). Consumers still passing
// variant="glass" degrade gracefully: it falls through to the default surface.
const cardVariants = cva("text-foreground", {
  variants: {
    variant: {
      default: "",
      elevated: "",
      ghost: "",
      outline: "",
    },
    hover: { true: "cursor-pointer", false: "" },
  },
  defaultVariants: { variant: "default", hover: false },
})

const Card = React.forwardRef(({ className, variant = "default", hover = false, sx, ...props }, ref) => {
  return (
    <MuiCard
      ref={ref}
      elevation={variant === "elevated" ? 3 : 0}
      className={cn(hover && "cursor-pointer", className)}
      sx={{
        backgroundImage: "none",
        ...(variant === "ghost" && { border: "none", backgroundColor: "transparent" }),
        ...(variant === "outline" && { boxShadow: "none", backgroundColor: "transparent" }),
        ...(hover && {
          "&:hover": {
            transform: "translateY(-3px)",
            boxShadow: "0 12px 28px -12px hsl(var(--accent) / 0.45)",
            borderColor: "var(--mui-palette-primary-main)",
          },
        }),
        ...sx,
      }}
      {...props}
    />
  )
})
Card.displayName = "Card"

const CardHeader = React.forwardRef(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col space-y-1.5 p-5", className)}
    {...props}
  />
))
CardHeader.displayName = "CardHeader"

const CardTitle = React.forwardRef(({ className, ...props }, ref) => (
  <h3
    ref={ref}
    className={cn("text-lg font-semibold leading-none tracking-tight text-foreground", className)}
    {...props}
  />
))
CardTitle.displayName = "CardTitle"

const CardDescription = React.forwardRef(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn("text-sm text-foreground-secondary", className)}
    {...props}
  />
))
CardDescription.displayName = "CardDescription"

const CardContent = React.forwardRef(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-5 pt-0", className)} {...props} />
))
CardContent.displayName = "CardContent"

const CardFooter = React.forwardRef(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-5 pt-0", className)}
    {...props}
  />
))
CardFooter.displayName = "CardFooter"

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent, cardVariants }

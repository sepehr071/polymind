import * as React from "react"
import * as AvatarPrimitive from "@radix-ui/react-avatar"
import { cva } from "class-variance-authority"
import MuiAvatar from "@mui/material/Avatar"

import { cn } from "@/lib/utils"
import { avatarColors } from "@/utils/avatarColor"

const avatarVariants = cva(
  "relative flex shrink-0 overflow-hidden",
  {
    variants: {
      size: {
        sm: "h-8 w-8",
        default: "h-10 w-10",
        lg: "h-12 w-12",
        xl: "h-16 w-16",
      },
      shape: {
        circle: "rounded-full",
        square: "rounded-lg",
      },
    },
    defaultVariants: {
      size: "default",
      shape: "circle",
    },
  }
)

// Radix Avatar.Root coordinates the image-load / fallback hand-off (the
// load-bearing behavior consumers rely on: <AvatarImage> renders only when a
// src exists, <AvatarFallback> shows initials/icon otherwise). We render that
// Root surface through MUI's Avatar via radix `asChild` so MUI theming applies
// while radix keeps the load coordination. The cva utility classes win
// (emotion prepend:true) so size/shape tokens stay authoritative.
const Avatar = React.forwardRef(({ className, size, shape, children, ...props }, ref) => (
  <AvatarPrimitive.Root asChild {...props}>
    {/* `children` must be rendered explicitly: an explicit JSX child on MuiAvatar
        clobbers props.children (the <AvatarFallback>), so MUI would fall back to
        its default Person silhouette. Pass them through. */}
    <MuiAvatar
      ref={ref}
      variant={shape === "square" ? "rounded" : "circular"}
      component="span"
      className={cn(avatarVariants({ size, shape }), className)}
      sx={{ bgcolor: "transparent", color: "inherit" }}
    >
      {children}
    </MuiAvatar>
  </AvatarPrimitive.Root>
))
Avatar.displayName = AvatarPrimitive.Root.displayName

const AvatarImage = React.forwardRef(({ className, ...props }, ref) => (
  <AvatarPrimitive.Image
    ref={ref}
    className={cn("aspect-square h-full w-full object-cover", className)}
    {...props}
  />
))
AvatarImage.displayName = AvatarPrimitive.Image.displayName

const AvatarFallback = React.forwardRef(({ className, children, seed, ...props }, ref) => {
  // Hue-tint when we have a usable string to seed from (explicit `seed`, else
  // string children like initials). Icon children with no seed keep the flat
  // accent wash. The inline style wins over the flat utility classes, so we drop
  // those classes in the tinted case to avoid mixed/overridden colors.
  const colorSeed = seed ?? (typeof children === "string" ? children : null)
  const tint = colorSeed ? avatarColors(colorSeed) : null

  return (
    <AvatarPrimitive.Fallback
      ref={ref}
      className={cn(
        "flex h-full w-full items-center justify-center font-medium",
        !tint && "bg-accent/20 text-accent",
        className
      )}
      style={tint ? { backgroundColor: tint.bg, color: tint.fg } : undefined}
      {...props}
    >
      {children}
    </AvatarPrimitive.Fallback>
  )
})
AvatarFallback.displayName = AvatarPrimitive.Fallback.displayName

export { Avatar, AvatarImage, AvatarFallback, avatarVariants }

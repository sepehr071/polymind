import * as React from "react"
import { cva } from "class-variance-authority"
import { styled } from "@mui/material/styles"

import { cn } from "@/lib/utils"


// Material OUTLINED field on a real single <input> DOM node. We keep the native
// element (instead of MUI OutlinedInput) so the ref lands on the input, every
// native attr passes through (id, type, dir, aria-*, autoComplete, step, value,
// onChange, …) and consumer `className` LAYOUT utilities still win (emotion
// cache `prepend:true`). The Material LOOK is driven entirely by the MUI theme
// CSS vars (`--mui-palette-*`) via the `styled` factory — so it inherits the
// app theme, auto dark mode and RTL with no per-instance Tailwind visuals.
//
// `inputVariants` is retained as a public export (and for the `error`/`ghost`
// variants a couple of consumers pass) but now only carries LAYOUT/sizing
// utilities — the colour/border/focus visuals come from the styled element so
// the Material theme shows through.
const inputVariants = cva(
  "flex w-full file:border-0 file:bg-transparent file:text-sm file:font-medium",
  {
    variants: {
      variant: {
        default: "",
        ghost: "",
        error: "",
      },
      size: {
        sm: "text-xs",
        default: "text-sm",
        lg: "text-base",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

// Real <input> styled as a Material outlined field. All colours reference the
// theme palette CSS vars so dark mode + brand accent come for free. `size` is a
// cva variant (NOT a native attr) — destructured out before the spread.
const StyledInput = styled("input", {
  name: "UiInput",
  shouldForwardProp: (prop) => prop !== "uiSize",
})(({ uiSize = "default" }) => ({
  fontFamily: "inherit",
  appearance: "none",
  width: "100%",
  color: "var(--mui-palette-text-primary)",
  // Opaque paper field (match Select) — translucent glass washed out on light cards.
  backgroundColor: "hsl(var(--bg-2))",
  border: "1px solid hsl(var(--line))",
  borderRadius: 12,
  paddingInline: uiSize === "sm" ? 12 : 13,
  // Consistent UI System: canonical field height 42 (sm 34 / lg 48).
  minHeight: uiSize === "sm" ? 34 : uiSize === "lg" ? 48 : 42,
  fontSize: uiSize === "sm" ? "0.8125rem" : uiSize === "lg" ? "1rem" : "0.875rem",
  lineHeight: 1.5,
  outline: "none",
  transition: "border-color .15s ease, box-shadow .15s ease, background-color .15s ease",
  "&::placeholder": { color: "var(--mui-palette-text-disabled)", opacity: 1 },
  "&:hover:not(:disabled):not([aria-invalid='true'])": {
    borderColor: "var(--mui-palette-text-disabled)",
  },
  // Spec focus: 2px accent border + a soft 3px accent halo (accent-soft).
  "&:focus, &:focus-visible": {
    outline: "none",
    borderColor: "var(--mui-palette-primary-main)",
    boxShadow: "0 0 0 3px hsl(var(--accent) / 0.18)",
  },
  // Error state via aria-invalid (consumers set it) or the `error` variant.
  "&[aria-invalid='true']": {
    borderColor: "var(--mui-palette-error-main)",
  },
  "&[aria-invalid='true']:focus": {
    borderColor: "var(--mui-palette-error-main)",
    boxShadow: "inset 0 0 0 1px var(--mui-palette-error-main)",
  },
  "&:disabled": {
    cursor: "not-allowed",
    opacity: 0.5,
    backgroundColor: "var(--mui-palette-action-hover)",
  },
}))

const Input = React.forwardRef(({ className, type, variant, size, "aria-invalid": ariaInvalid, ...props }, ref) => {
  // `variant="error"` is an alternate way to mark invalid (a couple of consumers
  // toggle it from validation state) — fold it into aria-invalid so the styled
  // error look fires either way without surfacing a non-standard attribute.
  const invalid = ariaInvalid ?? (variant === "error" ? true : undefined)
  return (
    <StyledInput
      type={type}
      uiSize={size || "default"}
      aria-invalid={invalid}
      className={cn(inputVariants({ variant, size }), className)}
      ref={ref}
      {...props}
    />
  )
})
Input.displayName = "Input"

export { Input, inputVariants }

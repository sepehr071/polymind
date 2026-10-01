import * as React from "react"
import { styled } from "@mui/material/styles"

import { cn } from "@/lib/utils"


// Material OUTLINED multiline field on a real single <textarea> DOM node. We
// keep the native element so the ref lands on the textarea and every native
// attr passes through (rows, onChange, onKeyDown, placeholder, value, dir, …),
// while consumer `className` LAYOUT utilities still win (emotion `prepend:true`).
// The Material LOOK comes from the MUI theme palette CSS vars (`--mui-palette-*`)
// — so it inherits the app theme, auto dark mode and RTL with no Tailwind visuals.
const StyledTextarea = styled("textarea", { name: "UiTextarea" })({
  fontFamily: "inherit",
  appearance: "none",
  width: "100%",
  minHeight: 80,
  color: "var(--mui-palette-text-primary)",
  // Opaque paper field — glass wash hid text on light cards.
  backgroundColor: "hsl(var(--bg-2))",
  border: "1px solid hsl(var(--line))",
  borderRadius: 12,
  padding: "10px 14px",
  fontSize: "0.875rem",
  lineHeight: 1.5,
  resize: "vertical",
  outline: "none",
  transition: "border-color .15s ease, box-shadow .15s ease, background-color .15s ease",
  "&::placeholder": { color: "var(--mui-palette-text-disabled)", opacity: 1 },
  "&:hover:not(:disabled):not([aria-invalid='true'])": {
    borderColor: "var(--mui-palette-text-disabled)",
  },
  "&:focus, &:focus-visible": {
    outline: "none",
    borderColor: "var(--mui-palette-primary-main)",
    boxShadow: "0 0 0 3px hsl(var(--accent) / 0.18)",
  },
  "&[aria-invalid='true']": { borderColor: "var(--mui-palette-error-main)" },
  "&[aria-invalid='true']:focus": {
    borderColor: "var(--mui-palette-error-main)",
    boxShadow: "inset 0 0 0 1px var(--mui-palette-error-main)",
  },
  "&:disabled": {
    cursor: "not-allowed",
    opacity: 0.5,
    backgroundColor: "var(--mui-palette-action-hover)",
  },
})

const Textarea = React.forwardRef(({ className, ...props }, ref) => {
  return (
    <StyledTextarea className={cn(className)} ref={ref} {...props} />
  )
})
Textarea.displayName = "Textarea"

export { Textarea }

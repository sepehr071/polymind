import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"
import { motion, useReducedMotion } from "motion/react"

import { cn } from "@/lib/utils"

/**
 * Each <Tabs> root broadcasts its current value, a stable layoutId, and the
 * presentation `variant` so <TabsList>/<TabsTrigger> children render the right
 * chrome.
 *
 * Variants:
 *   - 'underline' (DEFAULT) — canonical settings tabs: no container chrome,
 *     active = text-accent + a 2px accent bottom-border (animated via shared
 *     layoutId), inactive = fg-2.
 *   - 'segmented' — segmented filter control: hover-bg container + 1px line +
 *     radius 11 + pad 4; active = surface fill + small shadow, inactive = fg-2.
 */
const TabsCtx = React.createContext({
  activeValue: undefined,
  layoutId: "tab-active",
  variant: "underline",
})

const Tabs = React.forwardRef(
  ({ value, defaultValue, onValueChange, variant = "underline", children, ...props }, ref) => {
    const layoutIdSuffix = React.useId()
    const isControlled = value !== undefined
    const [internalValue, setInternalValue] = React.useState(defaultValue)
    const activeValue = isControlled ? value : internalValue

    const handleValueChange = React.useCallback(
      (next) => {
        if (!isControlled) setInternalValue(next)
        onValueChange?.(next)
      },
      [isControlled, onValueChange]
    )

    const ctx = React.useMemo(
      () => ({ activeValue, layoutId: `tab-active-${layoutIdSuffix}`, variant }),
      [activeValue, layoutIdSuffix, variant]
    )

    return (
      <TabsCtx.Provider value={ctx}>
        <TabsPrimitive.Root
          ref={ref}
          value={value}
          defaultValue={defaultValue}
          onValueChange={handleValueChange}
          {...props}
        >
          {children}
        </TabsPrimitive.Root>
      </TabsCtx.Provider>
    )
  }
)
Tabs.displayName = "Tabs"

const TabsList = React.forwardRef(({ className, ...props }, ref) => {
  const { variant } = React.useContext(TabsCtx)
  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        variant === "segmented"
          ? // segmented filter: hover-bg container + 1px line + radius 11 + pad 4
            "inline-flex h-10 items-center justify-center gap-1 rounded-[11px] border border-border bg-background-tertiary p-1 text-foreground-secondary"
          : // underline settings tabs: bare row, hairline baseline under the row
            "inline-flex h-10 items-center justify-start gap-4 border-b border-border text-foreground-secondary",
        className
      )}
      {...props}
    />
  )
})
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef(({ className, children, value, ...props }, ref) => {
  const { activeValue, layoutId, variant } = React.useContext(TabsCtx)
  const reduce = useReducedMotion()
  const isActive = activeValue !== undefined && activeValue === value
  const segmented = variant === "segmented"

  return (
    <TabsPrimitive.Trigger
      ref={ref}
      value={value}
      className={cn(
        // relative so the motion underline can sit on the bottom edge.
        "relative inline-flex items-center justify-center whitespace-nowrap text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
        segmented
          ? "rounded-lg px-3 py-1 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow"
          : // underline: quiet by default, accent text when active (border drawn by motion bar)
            "-mb-px px-1 pb-2.5 pt-1 hover:text-foreground data-[state=active]:text-accent data-[state=active]:hover:text-accent-hover",
        className
      )}
      {...props}
    >
      <span className="relative z-10 inline-flex items-center gap-2">{children}</span>
      {!segmented && isActive && (
        <motion.span
          aria-hidden="true"
          layoutId={layoutId}
          transition={
            reduce
              ? { duration: 0 }
              : { type: "spring", stiffness: 500, damping: 40, duration: 0.2 }
          }
          className="pointer-events-none absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent"
        />
      )}
    </TabsPrimitive.Trigger>
  )
})
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className
    )}
    {...props} />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }

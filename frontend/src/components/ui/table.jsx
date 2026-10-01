import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Canonical Table primitive (Consistent UI System).
 *
 * - <Table> wraps the <table> in a 1px-hairline container at the surface radius
 *   (16) with overflow-hidden + horizontal scroll, so the header fill + rounded
 *   corners read as a single card.
 * - <TableHeader> fills the header row with the secondary surface (surf2) and a
 *   bottom border; header cells are 12px/700/fg-2 uppercase.
 * - <TableBody>/<TableRow>/<TableCell> carry hairline row dividers + 13px cells.
 *
 * Layout-only utilities flow through `className`; visuals are baked in so every
 * table reads the same.
 */
const Table = React.forwardRef(({ className, containerClassName, bordered = true, ...props }, ref) => (
  <div
    className={cn(
      "overflow-x-auto",
      // bordered=false when the table already sits inside a card (e.g. a
      // <Section>) so we don't double up the hairline + rounded corners.
      bordered && "rounded-2xl border border-line",
      containerClassName,
    )}
  >
    <table
      ref={ref}
      className={cn("w-full border-collapse text-start", className)}
      {...props}
    />
  </div>
))
Table.displayName = "Table"

const TableHeader = React.forwardRef(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn(className)} {...props} />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn(className)} {...props} />
))
TableBody.displayName = "TableBody"

const TableRow = React.forwardRef(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b border-line last:border-0 transition-colors",
      className,
    )}
    {...props}
  />
))
TableRow.displayName = "TableRow"

// Header row: surf2 fill + bottom border so the head reads as a banded cap.
const TableHeadRow = React.forwardRef(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn("border-b border-line bg-bg-2", className)}
    {...props}
  />
))
TableHeadRow.displayName = "TableHeadRow"

const TableHead = React.forwardRef(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "px-4 py-2.5 text-start text-[12px] font-bold text-fg-2",
      className,
    )}
    {...props}
  />
))
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn("px-4 py-3 align-middle text-[13px]", className)}
    {...props}
  />
))
TableCell.displayName = "TableCell"

export {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHeadRow,
  TableHead,
  TableCell,
}

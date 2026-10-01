import { ChevronDown } from 'lucide-react'
import Ptile from '@/components/teams/Ptile'
import { IconTile } from '@/components/ui/icon-tile'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

/**
 * AccessRow — workspace access row used inside ProjectAccessTab.
 *
 * Leading glyph uses the canonical IconTile tone system (sky=work) when given a
 * lucide icon NAME; a project/group brand colour (`iconColor`) falls back to the
 * flat Ptile so user-chosen swatches still render. The role picker is the
 * canonical DropdownMenu (no hand-rolled outside-click + absolute menu).
 *
 * @param {React.ElementType} [iconComponent]  Lucide icon component for the IconTile.
 * @param {string} [iconColor]  Brand colour → renders a Ptile instead of an IconTile.
 * @param {string} [tone]       IconTile tone (default 'sky' for workspace access).
 * @param {React.ReactNode} title
 * @param {React.ReactNode} sub
 * @param {string} value        Right-side dropdown trigger label.
 * @param {string} badge        Optional small "default" tag next to title.
 * @param {Array<{value, label, danger?}>} options  Dropdown options. If omitted,
 *                                                   trigger renders as static.
 * @param {(option) => void} onChange  Fired when an option is picked.
 * @param {boolean} disabled    When true, dropdown is non-interactive.
 * @param {string} className
 */
export default function AccessRow({
  iconComponent,
  iconColor,
  tone = 'sky',
  title,
  sub,
  value,
  badge,
  options,
  onChange,
  disabled = false,
  className,
}) {
  const interactive = !disabled && Array.isArray(options) && options.length > 0

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-xl border border-line bg-bg-2/50 px-3 py-2.5',
        className,
      )}
    >
      {iconColor ? (
        <Ptile size="sm" color={iconColor} icon={iconComponent} />
      ) : (
        <IconTile icon={iconComponent} tone={tone} size="md" />
      )}

      <div className="flex flex-col gap-0.5 min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-fg-0 truncate">{title}</span>
          {badge && (
            <Badge variant="secondary" className="text-[10px] py-0 px-1.5 leading-tight">
              {badge}
            </Badge>
          )}
        </div>
        {sub && <span className="text-[11px] text-fg-3 truncate">{sub}</span>}
      </div>

      <div className="flex-shrink-0">
        {interactive ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                <span>{value}</span>
                <ChevronDown className="h-3 w-3 text-fg-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[160px]">
              {options.map(opt => (
                <DropdownMenuItem
                  key={opt.value}
                  onClick={() => onChange?.(opt)}
                  className={opt.danger ? 'text-error focus:text-error' : undefined}
                >
                  {opt.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-[10px] border border-line bg-bg-2/50 px-3 py-1.5 text-xs text-fg-2 cursor-not-allowed">
            {value}
            <ChevronDown className="h-3 w-3 text-fg-3" />
          </span>
        )}
      </div>
    </div>
  )
}

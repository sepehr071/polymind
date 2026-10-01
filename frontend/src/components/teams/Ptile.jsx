import { DynamicIcon } from 'lucide-react/dynamic'
import { cn } from '@/lib/utils'

const SIZE_CLASSES = {
  sm: 'w-6 h-6 rounded-md text-[11px]',
  md: 'w-8 h-8 rounded-lg text-sm',
  lg: 'w-10 h-10 rounded-xl text-base',
}

const ICON_SIZES = {
  sm: 'h-3 w-3',
  md: 'h-4 w-4',
  lg: 'h-5 w-5',
}

// Design-token aliases that don't kebab-cleanly to a lucide icon id. The only
// short name stored on `group.icon` (see teams/CreateGroupModal ICON_OPTIONS)
// whose label diverges from its lucide id is "message" (→ message-circle).
// Other aliases (cpu, sparkle, flame, shield, …) already equal a valid lucide
// id, so they pass straight through `toKebabIconName` below.
const ICON_NAME_ALIASES = {
  message: 'message-circle',
}

/**
 * Normalize a stored icon token to a lucide kebab-case id for <DynamicIcon>.
 * Accepts PascalCase exports (`MessageSquare`), snake/space/kebab tokens, and
 * the short design aliases above. Returns null for non-string input.
 */
function toKebabIconName(iconName) {
  if (!iconName || typeof iconName !== 'string') return null
  const raw = iconName.trim()
  if (!raw) return null
  const lower = raw.toLowerCase()
  if (ICON_NAME_ALIASES[lower]) return ICON_NAME_ALIASES[lower]
  // PascalCase / camelCase → kebab (insert a dash at lower→Upper and letter→digit
  // boundaries), then collapse any separator runs to single dashes.
  return raw
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/([a-zA-Z])([0-9])/g, '$1-$2')
    .replace(/[-_\s]+/g, '-')
    .toLowerCase()
    .replace(/^-+|-+$/g, '')
}

/**
 * Ptile — colored project tile with letter or icon.
 * Matches design parts/shell.jsx ptile / ptile-sm / ptile-lg styles.
 *
 * @param {string} color  Solid CSS color used as fill.
 * @param {string|React.ComponentType} icon  Lucide icon name (string, e.g. a
 *   DB-stored `project.icon`/`group.icon`) or an already-imported icon component.
 * @param {string} letter  Single character / short label fallback when no icon.
 * @param {'sm'|'md'|'lg'} size
 * @param {boolean} gradient  If true, render a 135deg gradient from color to color+cc.
 * @param {string} className
 */
export default function Ptile({
  color = 'hsl(var(--accent))',
  icon,
  letter,
  size = 'md',
  gradient = false,
  className,
}) {
  const sizeCls = SIZE_CLASSES[size] || SIZE_CLASSES.md
  const iconSizeCls = ICON_SIZES[size] || ICON_SIZES.md

  // A caller may hand us an icon component directly; render it verbatim. A
  // string is resolved lazily via DynamicIcon (each glyph is its own dynamic
  // import) so this eager-path component never bundles the full lucide set.
  const IconComp = typeof icon === 'function' ? icon : null
  const iconName = typeof icon === 'string' ? toKebabIconName(icon) : null

  const background = gradient
    ? `linear-gradient(135deg, ${color}, ${color}cc)`
    : color

  return (
    <span
      className={cn(
        'inline-flex items-center justify-center font-semibold text-white flex-shrink-0',
        sizeCls,
        className,
      )}
      style={{
        background,
        letterSpacing: '-0.02em',
      }}
    >
      {IconComp ? (
        <IconComp className={iconSizeCls} strokeWidth={2} />
      ) : iconName ? (
        <DynamicIcon name={iconName} className={iconSizeCls} strokeWidth={2} />
      ) : (
        letter || ''
      )}
    </span>
  )
}

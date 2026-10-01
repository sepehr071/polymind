import { Shield, ShieldCheck, Pencil, Eye } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

// Roles that are still valid in the current workspace model.
const ROLE_STYLES = {
  owner: {
    labelKey: 'roles.owner',
    Icon: Shield,
    className: 'bg-role-owner-bg text-role-owner-fg border border-role-owner-line',
  },
  admin: {
    labelKey: 'roles.admin',
    Icon: ShieldCheck,
    className: 'bg-role-editor-bg text-role-editor-fg border border-role-editor-line',
  },
  editor: {
    labelKey: 'roles.editor',
    Icon: Pencil,
    className: 'bg-success/15 text-success border border-success/30',
  },
  viewer: {
    labelKey: 'roles.viewer',
    Icon: Eye,
    className: 'bg-role-viewer-bg text-role-viewer-fg border border-role-viewer-line',
  },
}

// Legacy role aliases — mapped to current equivalents.
// Warn once per unknown role to help surface stale data.
const LEGACY_MAP = {
  'billing-admin': 'editor',
  admin: 'owner',
  guest: 'viewer',
}

const WARNED_ROLES = new Set()

function normalize(role) {
  if (ROLE_STYLES[role]) return role
  const mapped = LEGACY_MAP[role]
  if (mapped) {
    if (!WARNED_ROLES.has(role)) {
      WARNED_ROLES.add(role)
      // eslint-disable-next-line no-console
      console.warn(`[RoleBadge] Legacy role "${role}" mapped to "${mapped}". Update source data.`)
    }
    return mapped
  }
  return 'viewer'
}

export default function RoleBadge({ role, className }) {
  const { t } = useTranslation('projects')
  const normalizedRole = normalize(role)
  const style = ROLE_STYLES[normalizedRole]
  const { Icon, labelKey } = style
  const label = t(labelKey)
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium leading-tight',
        style.className,
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  )
}

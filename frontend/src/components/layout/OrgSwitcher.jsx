import { useEffect, useMemo, useState, useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Building2, Check, ChevronDown } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { adminService } from '@/services/adminService'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import { makeSwitchTo } from '@/utils/navHelpers'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import { cn } from '@/utils/cn'

const SEARCH_AFTER = 8

const ROLE_PILL = {
  owner: 'bg-role-owner-bg text-role-owner-fg border border-role-owner-line',
  editor: 'bg-role-editor-bg text-role-editor-fg border border-role-editor-line',
  viewer: 'bg-role-viewer-bg text-role-viewer-fg border border-role-viewer-line',
}

const PILL =
  'inline-flex h-9 min-w-0 max-w-[11rem] items-center gap-1.5 rounded-full border border-border bg-background px-2.5 text-sm leading-none sm:max-w-[16rem]'

function OrgMark() {
  return <Building2 className="h-4 w-4 shrink-0 text-accent" aria-hidden />
}

function RolePill({ role }) {
  const { t } = useTranslation('layout')
  if (!role) return null
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide',
        ROLE_PILL[role] ?? ROLE_PILL.viewer,
      )}
    >
      {t(`workspaceSwitcher.roles.${role}`, { defaultValue: role })}
    </span>
  )
}

/**
 * Header org switcher (visual top-left in RTL, with the theme control).
 * Members see only the orgs they belong to (role pill); a single org renders
 * as a static label. Super-admin lists every company.
 */
export default function OrgSwitcher() {
  const { user } = useAuth()
  const { t } = useTranslation('layout')
  const { workspaces, currentWorkspace, setActiveWorkspace } = useWorkspace()
  const queryClient = useQueryClient()
  const nav = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const isAdmin = user?.role === 'admin'

  const orgs = useMemo(() => workspaces.filter((w) => w.type !== 'personal'), [workspaces])

  const query = useQuery({
    queryKey: ['admin-companies', 30],
    queryFn: () => adminService.listCompanies(30),
    enabled: isAdmin,
    staleTime: 60_000,
  })
  const companies = query.data?.companies || []

  // Backfill the name of a company the admin holds but is not a member of.
  useEffect(() => {
    if (!isAdmin || !currentWorkspace?._id || currentWorkspace.name) return
    const hit = companies.find((c) => c._id === currentWorkspace._id)
    if (!hit) return
    setActiveWorkspace({
      _id: hit._id,
      name: hit.name || hit.slug || '',
      type: 'team',
      plan_tier: hit.plan_tier,
    })
  }, [isAdmin, currentWorkspace, companies, setActiveWorkspace])

  const rawSwitch = useMemo(
    () =>
      makeSwitchTo({
        setActiveWorkspace,
        currentWorkspaceId: currentWorkspace?._id,
        navigate: nav,
        location,
      }),
    [setActiveWorkspace, currentWorkspace?._id, nav, location],
  )
  const switchTo = useCallback(
    (w) => {
      rawSwitch(w)
      queryClient.invalidateQueries({ queryKey: ['usage'] })
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
    [rawSwitch, queryClient],
  )

  const items = useMemo(() => {
    if (isAdmin) {
      const needle = q.trim().toLowerCase()
      return companies
        .filter((c) => !needle || `${c.name || ''} ${c.slug || ''}`.toLowerCase().includes(needle))
        .map((c) => {
          const member = workspaces.find((w) => w._id === c._id)
          return {
            _id: c._id,
            name: c.name || c.slug || '',
            role: member?.member_role,
            target: member || {
              _id: c._id,
              name: c.name || c.slug || '',
              type: 'team',
              plan_tier: c.plan_tier,
            },
          }
        })
    }
    return orgs.map((w) => ({ _id: w._id, name: w.name, role: w.member_role, target: w }))
  }, [isAdmin, companies, workspaces, orgs, q])

  const name = currentWorkspace?.name
  const label = name || t(isAdmin ? 'orgSwitcher.select' : 'workspaceSwitcher.noWorkspace')

  if (!isAdmin && orgs.length <= 1) {
    return (
      <div className={PILL}>
        <OrgMark />
        <span className="truncate font-medium text-fg-0">{label}</span>
      </div>
    )
  }

  const showSearch = isAdmin && companies.length > SEARCH_AFTER

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-label={t('header.openCompanySwitcher')}
          className={cn(PILL, 'transition hover:bg-background-tertiary')}
        >
          <OrgMark />
          <span className="truncate font-medium leading-none text-fg-0">{label}</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-fg-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        className="w-72 overflow-hidden rounded-xl p-0"
        style={solidPanelSx({ radius: RADII.surface })}
      >
        {showSearch && (
          <div className="border-b border-border px-3 py-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('orgSwitcher.search')}
              className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-accent"
            />
          </div>
        )}
        <div className="max-h-80 overflow-y-auto p-1.5">
          {items.length === 0 ? (
            <p className="px-2 py-3 text-center text-xs text-foreground-tertiary">
              {isAdmin && companies.length ? t('orgSwitcher.noMatch') : t('orgSwitcher.empty')}
            </p>
          ) : (
            items.map((item) => {
              const selected = item._id === currentWorkspace?._id
              return (
                <button
                  key={item._id}
                  type="button"
                  onClick={() => {
                    if (!selected) switchTo(item.target)
                    setOpen(false)
                    setQ('')
                  }}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-start text-sm transition-colors',
                    selected ? 'bg-accent/10 text-foreground' : 'text-foreground hover:bg-background-tertiary',
                  )}
                >
                  <OrgMark />
                  <span className="min-w-0 flex-1 truncate">
                    {item.name || t('workspaceSwitcher.noWorkspace')}
                  </span>
                  <RolePill role={item.role} />
                  {selected ? <Check className="h-4 w-4 shrink-0 text-accent" /> : null}
                </button>
              )
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

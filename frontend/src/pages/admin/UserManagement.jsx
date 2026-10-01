import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Search,
  Users,
  Shield,
  Ban,
  CheckCircle,
  MoreVertical,
  Eye,
  Settings,
  Wallet,
  X,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { adminService } from '../../services/adminService'
import { fmtDate } from '../../utils/dateLocale'
import { fmtNumber } from '@/utils/persianLocale'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Checkbox } from '@/components/ui/checkbox'
import { CostValue } from '@/components/ui/CostValue'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import MemberBudgetDialog from '@/components/billing/MemberBudgetDialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import PageShell from '@/components/layout/PageShell'

// Debounce hook — keeps the input responsive while the network query keys off
// the settled value so /admin/users doesn't fire on every keystroke.
function useDebouncedValue(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export default function UserManagement() {
  const { t } = useTranslation('admin')
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const debouncedSearch = useDebouncedValue(searchQuery, 300)
  const [page, setPage] = useState(1)
  const [includeBanned, setIncludeBanned] = useState(true)
  const [selectedUser, setSelectedUser] = useState(null)
  const [showBanModal, setShowBanModal] = useState(false)
  const [showLimitsModal, setShowLimitsModal] = useState(false)
  const [showBudgetModal, setShowBudgetModal] = useState(false)
  // 'all' is a non-empty Select sentinel (Radix rejects '') = no org filter.
  const [orgId, setOrgId] = useState('all')
  // Per-page bulk selection (mirrors ImageGrid's Set-based shape). Keyed by
  // user id; reset whenever the page changes (ids no longer on screen).
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [showBulkBudgetModal, setShowBulkBudgetModal] = useState(false)

  const orgsQ = useQuery({
    queryKey: ['admin-companies', 30],
    queryFn: () => adminService.listCompanies(30),
    staleTime: 60_000,
  })
  const companies = orgsQ.data?.companies || []
  const workspaceId = orgId === 'all' ? null : orgId
  const orgName = companies.find((c) => c._id === workspaceId)?.name || ''

  const { data, isLoading } = useQuery({
    queryKey: ['admin-users', page, includeBanned, debouncedSearch, workspaceId],
    queryFn: () => adminService.getUsers({
      page,
      limit: 20,
      include_banned: includeBanned,
      search: debouncedSearch,
      ...(workspaceId ? { workspace_id: workspaceId } : {}),
    }),
  })

  const users = data?.users || []
  const total = data?.total || 0
  const hasMore = data?.has_more || false

  // The visible rows change on every page turn, so the selection (a set of ids
  // that may no longer be rendered) is meaningless — clear it.
  useEffect(() => {
    setSelectedIds(new Set())
  }, [page, debouncedSearch, includeBanned, workspaceId])

  const allOnPageSelected = users.length > 0 && users.every((u) => selectedIds.has(u._id))
  const someOnPageSelected = users.some((u) => selectedIds.has(u._id))

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = (checked) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      for (const u of users) {
        if (checked) next.add(u._id)
        else next.delete(u._id)
      }
      return next
    })
  }

  const clearSelection = () => setSelectedIds(new Set())

  const budgetMutation = useMutation({
    mutationFn: ({ userId, amountUsd }) =>
      adminService.setMemberBudget(userId, { workspaceId, amountUsd }),
    onSuccess: (_res, vars) => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success(vars.amountUsd == null ? t('users.budgetCleared') : t('users.budgetSaved'))
    },
  })

  const banMutation = useMutation({
    mutationFn: ({ userId, reason }) => adminService.banUser(userId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success(t('users.banSuccess'))
      setShowBanModal(false)
      setSelectedUser(null)
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('users.banFailed'))
    },
  })

  const unbanMutation = useMutation({
    mutationFn: adminService.unbanUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success(t('users.unbanSuccess'))
    },
    onError: () => {
      toast.error(t('users.unbanFailed'))
    },
  })

  return (
    <PageShell width="full">
        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-foreground-tertiary" />
            <Input
              type="text"
              placeholder={t('users.searchPlaceholder')}
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
                setPage(1)
              }}
              className="ps-9"
            />
          </div>
          <Select
            value={orgId}
            onValueChange={(v) => {
              setOrgId(v)
              setPage(1)
            }}
          >
            <SelectTrigger className="w-full sm:w-60" aria-label={t('users.orgFilter')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('users.allOrgs')}</SelectItem>
              {companies.map((c) => (
                <SelectItem key={c._id} value={c._id}>
                  {c.name || c.slug}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant={includeBanned ? "secondary" : "default"}
            onClick={() => {
              setIncludeBanned(!includeBanned)
              setPage(1)
            }}
          >
            <Ban className="h-4 w-4 me-2" />
            {includeBanned ? t('users.hideBanned') : t('users.showBanned')}
          </Button>
        </div>

        {/* Bulk-action toolbar — appears once any row is selected. */}
        {selectedIds.size > 0 && (
          <div className="flex items-center justify-between gap-3 rounded-[12px] border border-accent/30 bg-accent/5 px-4 py-2.5">
            <span className="text-sm font-medium text-foreground">
              {t('users.bulk.selected', { count: selectedIds.size })}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={clearSelection}
              >
                <X className="h-4 w-4 me-1.5" />
                {t('users.bulk.clear')}
              </Button>
              <Button
                size="sm"
                disabled={!workspaceId}
                title={!workspaceId ? t('users.selectOrgHint') : undefined}
                onClick={() => setShowBulkBudgetModal(true)}
              >
                <Wallet className="h-4 w-4 me-1.5" />
                {t('users.bulk.setBudget')}
              </Button>
            </div>
          </div>
        )}

        {/* Users Table */}
        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : users.length === 0 ? (
          <div className="text-center py-12">
            <Users className="h-12 w-12 text-foreground-tertiary mx-auto mb-3" />
            <h3 className="text-lg font-medium text-foreground mb-1">{t('users.noUsersFound')}</h3>
            <p className="text-foreground-secondary">
              {searchQuery ? t('users.noUsersSearch') : t('users.noUsersYet')}
            </p>
          </div>
        ) : (
          <Card className="p-0">
            <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-background-tertiary text-xs uppercase tracking-wide text-foreground-secondary">
                <tr className="border-b border-border">
                  <th className="w-10 px-4 py-3">
                    <Checkbox
                      checked={allOnPageSelected}
                      indeterminate={!allOnPageSelected && someOnPageSelected}
                      onCheckedChange={(checked) => toggleSelectAll(checked)}
                      aria-label={t('users.bulk.selectAll')}
                    />
                  </th>
                  <th className="text-start px-4 py-3 font-bold">{t('users.colUser')}</th>
                  <th className="text-start px-4 py-3 font-bold">{t('users.colRole')}</th>
                  <th className="text-start px-4 py-3 font-bold">{t('users.colStatus')}</th>
                  <th className="text-start px-4 py-3 font-bold">{t('users.colUsage')}</th>
                  <th className="text-end px-4 py-3 font-bold">{t('users.cost')}</th>
                  <th className="text-end px-4 py-3 font-bold">{t('users.colOrgBudget')}</th>
                  <th className="text-start px-4 py-3 font-bold">{t('users.colJoined')}</th>
                  <th className="text-end px-4 py-3 font-bold">{t('users.colActions')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <UserRow
                    key={user._id}
                    user={user}
                    selected={selectedIds.has(user._id)}
                    onSelectToggle={() => toggleSelect(user._id)}
                    onBan={() => {
                      setSelectedUser(user)
                      setShowBanModal(true)
                    }}
                    onUnban={() => unbanMutation.mutate(user._id)}
                    onSetLimits={() => {
                      setSelectedUser(user)
                      setShowLimitsModal(true)
                    }}
                    hasOrg={Boolean(workspaceId)}
                    onSetBudget={() => {
                      setSelectedUser(user)
                      setShowBudgetModal(true)
                    }}
                  />
                ))}
              </tbody>
            </table>
            </div>
          </Card>
        )}

        {/* Pagination */}
        {total > 20 && (
          <div className="flex items-center justify-between">
            <p className="text-sm text-foreground-secondary">
              {t('users.showing', { from: (page - 1) * 20 + 1, to: Math.min(page * 20, total), total })}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => setPage(p => p - 1)}
                disabled={page === 1}
              >
                <ChevronLeft className="h-4 w-4 me-2 rtl:rotate-180" />
                {t('users.previous')}
              </Button>
              <Button
                variant="secondary"
                onClick={() => setPage(p => p + 1)}
                disabled={!hasMore}
              >
                {t('users.next')}
                <ChevronRight className="h-4 w-4 ms-2 rtl:rotate-180" />
              </Button>
            </div>
          </div>
        )}

      {/* Ban Modal */}
      {showBanModal && selectedUser && (
        <BanModal
          user={selectedUser}
          onClose={() => {
            setShowBanModal(false)
            setSelectedUser(null)
          }}
          onBan={(reason) => banMutation.mutate({ userId: selectedUser._id, reason })}
          isLoading={banMutation.isPending}
        />
      )}

      {/* Limits Modal */}
      {showLimitsModal && selectedUser && (
        <LimitsModal
          user={selectedUser}
          onClose={() => {
            setShowLimitsModal(false)
            setSelectedUser(null)
          }}
        />
      )}

      {/* Per-member monthly budget inside the filtered org. */}
      {selectedUser && workspaceId && (
        <MemberBudgetDialog
          open={showBudgetModal}
          onClose={() => {
            setShowBudgetModal(false)
            setSelectedUser(null)
          }}
          orgName={orgName}
          targetName={selectedUser.email}
          initialAmount={selectedUser.org_budget?.amount_usd ?? null}
          onConfirm={(amountUsd) =>
            budgetMutation.mutateAsync({ userId: selectedUser._id, amountUsd })
          }
        />
      )}

      {/* Bulk budget — partial success is reported as applied/failed. */}
      {workspaceId && (
        <MemberBudgetDialog
          open={showBulkBudgetModal}
          onClose={() => setShowBulkBudgetModal(false)}
          orgName={orgName}
          bulkCount={selectedIds.size}
          onConfirm={async (amountUsd) => {
            const res = await adminService.bulkSetMemberBudget({
              workspaceId,
              userIds: Array.from(selectedIds),
              amountUsd,
            })
            queryClient.invalidateQueries({ queryKey: ['admin-users'] })
            toast.success(
              t('users.bulk.success', {
                applied: res?.applied ?? 0,
                failed: res?.failed ?? 0,
              }),
            )
            clearSelection()
          }}
        />
      )}
    </PageShell>
  )
}

function UserRow({ user, selected, onSelectToggle, onBan, onUnban, onSetLimits, onSetBudget, hasOrg }) {
  const { t } = useTranslation('admin')
  const { t: tc } = useTranslation('common')
  const navigate = useNavigate()
  const isBanned = user.status?.is_banned

  return (
    <tr className="border-b border-border hover:bg-background-tertiary/50">
      <td className="px-4 py-3">
        <Checkbox
          checked={selected}
          onCheckedChange={() => onSelectToggle()}
          aria-label={t('users.bulk.selectRow')}
        />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <Avatar size="sm">
            <AvatarFallback seed={user.profile?.display_name || user.email} className="text-sm">
              {user.profile?.display_name?.[0]?.toUpperCase() || user.email?.[0]?.toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <div>
            <p className="font-medium text-foreground">{user.profile?.display_name || t('users.noName')}</p>
            <p className="text-sm text-foreground-secondary">{user.email}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        <Badge
          variant={user.role === 'admin' ? 'default' : 'secondary'}
          className="gap-1"
        >
          {user.role === 'admin' && <Shield className="h-3 w-3" />}
          {t(`users.roleLabels.${user.role}`, user.role)}
        </Badge>
      </td>
      <td className="px-4 py-3">
        {isBanned ? (
          <Badge variant="destructive" className="gap-1">
            <Ban className="h-3 w-3" />
            {t('users.banned')}
          </Badge>
        ) : (
          <Badge variant="success" className="gap-1">
            <CheckCircle className="h-3 w-3" />
            {t('users.active')}
          </Badge>
        )}
      </td>
      <td className="px-4 py-3">
        <div className="text-sm">
          <p className="text-foreground">{t('users.messages', { count: user.usage?.messages_sent || 0 })}</p>
          <p className="text-foreground-secondary tabular-nums">
            {t('users.tokens', { count: fmtNumber(user.usage_tokens ?? 0) })}
          </p>
        </div>
      </td>
      <td className="px-4 py-3 text-end">
        <CostValue usd={user.usage_cost_usd ?? null} className="text-sm text-foreground" />
      </td>
      <td className="px-4 py-3 text-end">
        <OrgBudgetCell budget={hasOrg ? user.org_budget : undefined} />
      </td>
      <td className="px-4 py-3 text-sm text-foreground-secondary">
        {fmtDate(new Date(user.created_at), 'MMM d, yyyy')}
      </td>
      <td className="px-4 py-3 text-end">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              aria-label={tc('aria.rowActions')}
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => navigate(`/admin/users/${user._id}/history`)}>
              <Eye className="h-4 w-4 me-2" />
              {t('users.viewHistory')}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onSetLimits}>
              <Settings className="h-4 w-4 me-2" />
              {t('users.setLimits')}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onSetBudget} disabled={!hasOrg}>
              <Wallet className="h-4 w-4 me-2" />
              {t('users.setBudget')}
            </DropdownMenuItem>
            {user.role !== 'admin' && (
              <>
                <DropdownMenuSeparator />
                {isBanned ? (
                  <DropdownMenuItem onClick={onUnban} className="text-success">
                    <CheckCircle className="h-4 w-4 me-2" />
                    {t('users.unbanUser')}
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onClick={onBan} className="text-error">
                    <Ban className="h-4 w-4 me-2" />
                    {t('users.banUser')}
                  </DropdownMenuItem>
                )}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </td>
    </tr>
  )
}

function OrgBudgetCell({ budget }) {
  const { t } = useTranslation('admin')
  if (budget === undefined) return <span className="text-sm text-foreground-tertiary">—</span>
  if (!budget || budget.amount_usd == null) {
    return <span className="text-sm text-foreground-tertiary">{t('users.noBudget')}</span>
  }
  return (
    <div className="text-sm">
      <CostValue usd={budget.amount_usd} className="font-medium text-foreground" />
      <p className="text-xs text-foreground-secondary">
        <CostValue usd={budget.spent_mtd_usd ?? 0} /> {t('users.budgetSpent')} ·{' '}
        <CostValue usd={budget.remaining_usd ?? null} /> {t('users.budgetRemaining')}
      </p>
    </div>
  )
}

function BanModal({ user, onClose, onBan, isLoading }) {
  const { t } = useTranslation('admin')
  const [reason, setReason] = useState('')

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('users.banModal.title')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-foreground-secondary">
            {t('users.banModal.confirm')} <strong>{user.email}</strong>?
          </p>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-foreground">{t('users.banModal.reason')}</label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t('users.banModal.reasonPlaceholder')}
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            {t('users.banModal.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={() => onBan(reason)}
            disabled={isLoading}
          >
            {isLoading ? t('users.banModal.banning') : t('users.banModal.ban')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function LimitsModal({ user, onClose }) {
  const { t } = useTranslation('admin')
  const queryClient = useQueryClient()
  const [tokensLimit, setTokensLimit] = useState(
    user.usage?.tokens_limit === -1 ? '' : user.usage?.tokens_limit || ''
  )

  const limitsMutation = useMutation({
    mutationFn: (limit) => adminService.setUserLimits(user._id, limit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success(t('users.limitsModal.updateSuccess'))
      onClose()
    },
    onError: () => {
      toast.error(t('users.limitsModal.updateFailed'))
    },
  })

  const handleSave = () => {
    const limit = tokensLimit === '' ? -1 : parseInt(tokensLimit)
    limitsMutation.mutate(limit)
  }

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('users.limitsModal.title')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="block text-sm font-medium text-foreground">{t('users.limitsModal.tokenLimit')}</label>
            <Input
              type="number"
              value={tokensLimit}
              onChange={(e) => setTokensLimit(e.target.value)}
              placeholder={t('users.limitsModal.tokenLimitPlaceholder')}
            />
            <p className="text-xs text-foreground-tertiary">
              {t('users.limitsModal.currentUsage', { tokens: fmtNumber(user.usage?.tokens_used ?? 0) })}
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            {t('users.limitsModal.cancel')}
          </Button>
          <Button
            onClick={handleSave}
            disabled={limitsMutation.isPending}
          >
            {limitsMutation.isPending ? t('users.limitsModal.saving') : t('users.limitsModal.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Gauge, Info, AlertTriangle, Users } from 'lucide-react'

import projectService from '@/services/projectService'

import Section from '@/components/teams/Section'
import StatTile from '@/components/teams/StatTile'
import RoleBadge from '@/components/teams/RoleBadge'
import LimitRow from '@/components/teams/LimitRow'
import { CostValue } from '@/components/ui/CostValue'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import SetBudgetDialog from '@/components/billing/SetBudgetDialog'
import { canSeePrice } from '@/utils/money'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'

function getInitials(name, email) {
  if (name) return name.slice(0, 2).toUpperCase()
  if (email) return email.slice(0, 2).toUpperCase()
  return '??'
}

/**
 * ProjectBillingTab — team-scoped (DB `project`) budget view.
 *
 * Surfaces the server-computed `/projects/{pid}/budget` envelope:
 *   - a team budget card (budget vs MTD spend vs remaining),
 *   - an always-visible attribution caveat (only team-tagged spend counts),
 *   - a per-member table with each member's own ceiling / spend / remaining.
 *
 * Owners can set the team budget and each member's budget via `SetBudgetDialog`;
 * everyone else sees a read-only view. Budgets are advisory ceilings; the 402
 * enforcement lives on the chat/LLM call sites, not here.
 */
export default function ProjectBillingTab({ project, pid, isOwner = false }) {
  const { t } = useTranslation('billing')
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const { workspaces } = useWorkspace()

  // PROFIT GATING: this tab's $ figures were visible to ALL team members. Only
  // department owners (team-workspace owner) + admins may see PRICE. The budget
  // envelope (`amount_usd`/`spend_mtd`/`remaining`) carries NO credits field, so
  // for non-price members there's nothing to convert to credits — hide the $
  // figure (render em-dash) rather than leak it. `isOwner` still drives EDIT
  // controls; it does NOT grant price visibility on its own (a personal-ws owner
  // is not a price viewer).
  const priceVisible = canSeePrice(user, workspaces)
  // Gated money cell — `<CostValue>` for price viewers, em-dash otherwise.
  const Money = ({ usd, className = '' }) =>
    priceVisible ? (
      <CostValue usd={usd} className={className} />
    ) : (
      <span className={`tabular-nums ${className}`.trim()}>—</span>
    )

  // `dialog` holds the open SetBudgetDialog target:
  //   { kind: 'team' } | { kind: 'member', uid, member }
  const [dialog, setDialog] = useState(null)
  const [saving, setSaving] = useState(false)

  const budgetQ = useQuery({
    queryKey: ['project', 'budget', pid],
    queryFn: () => projectService.getBudget(pid),
    enabled: Boolean(pid),
    staleTime: 60_000,
  })

  const data = budgetQ.data
  const teamBudget = data?.team_budget || null
  const teamSpend = Number(data?.spend_mtd) || 0
  const teamRemaining =
    data?.remaining != null ? Number(data.remaining) : null
  const teamCap = teamBudget?.amount_usd != null ? Number(teamBudget.amount_usd) : null
  const teamEnabled = teamBudget?.enabled !== false && teamCap != null
  const members = useMemo(() => data?.per_user || [], [data?.per_user])

  function invalidate() {
    return queryClient.invalidateQueries({ queryKey: ['project', 'budget', pid] })
  }

  async function handleTeamConfirm({ amount_usd, enabled }) {
    setSaving(true)
    try {
      await projectService.setBudget(pid, { amount_usd, enabled })
      toast.success(
        amount_usd == null
          ? t('teamBudget.toastCleared')
          : t('teamBudget.toastSaved'),
      )
      await invalidate()
      setDialog(null)
    } catch (ex) {
      toast.error(ex?.response?.data?.error || t('teamBudget.toastFailed'))
    } finally {
      setSaving(false)
    }
  }

  async function handleMemberConfirm({ amount_usd, enabled }) {
    if (!dialog || dialog.kind !== 'member') return
    setSaving(true)
    try {
      await projectService.setMemberBudget(pid, dialog.uid, { amount_usd, enabled })
      toast.success(
        amount_usd == null
          ? t('teamBudget.toastMemberCleared')
          : t('teamBudget.toastMemberSaved'),
      )
      await invalidate()
      setDialog(null)
    } catch (ex) {
      toast.error(ex?.response?.data?.error || t('teamBudget.toastFailed'))
    } finally {
      setSaving(false)
    }
  }

  // ── Loading / error states (mirror the workspace tab's quiet idioms) ──────
  if (budgetQ.isLoading) {
    return (
      <div className="px-4 py-6 text-sm text-fg-3">{t('teamBudget.loading')}</div>
    )
  }
  if (budgetQ.isError) {
    return (
      <div>
        {/* Error card stays in the form lane — a centered notice doesn't need
            the dense table width. */}
        <Section title={t('teamBudget.title')}>
          <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed border-err/30 bg-err/5 px-4 py-6 text-center">
            <AlertTriangle className="h-5 w-5 text-err" />
            <p className="text-sm text-fg-2">{t('teamBudget.errorTitle')}</p>
            <p className="text-[11px] text-fg-3">{t('teamBudget.errorBody')}</p>
          </div>
        </Section>
      </div>
    )
  }

  const teamSubtitle = project?.name
    ? t('teamBudget.dialogTeamSubtitle', { name: project.name })
    : t('teamBudget.dialogTeamSubtitleGeneric')

  return (
    <div className="space-y-6">
      {/* ── Team budget card ─────────────────────────────────────────────── */}
      <Section
        title={t('teamBudget.title')}
        hint={t('teamBudget.hint')}
        action={
          isOwner ? (
            <Button
              size="sm"
              className="gap-1.5"
              onClick={() => setDialog({ kind: 'team' })}
            >
              <Gauge className="h-3.5 w-3.5" />
              {teamCap != null ? t('teamBudget.editBudget') : t('teamBudget.setBudget')}
            </Button>
          ) : null
        }
      >
        {teamCap == null ? (
          <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed border-line bg-bg-2/40 px-4 py-6 text-center">
            <p className="text-sm text-fg-2">{t('teamBudget.noBudgetTitle')}</p>
            <p className="text-[11px] text-fg-3">
              {isOwner
                ? t('teamBudget.noBudgetHintOwner')
                : t('teamBudget.noBudgetHint')}
            </p>
            {/* Even with no budget, spend MTD is meaningful. */}
            <div className="mt-2 text-xs text-fg-3">
              {t('teamBudget.spendSoFar')}{' '}
              <Money usd={teamSpend} className="font-medium text-fg-1" />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <StatTile
                label={t('teamBudget.budgetLabel')}
                value={<Money usd={teamCap} />}
                hint={
                  teamEnabled
                    ? t('teamBudget.enforcedHint')
                    : t('teamBudget.disabledHint')
                }
              />
              <StatTile
                label={t('teamBudget.spendMtdLabel')}
                value={<Money usd={teamSpend} />}
              />
              <StatTile
                label={t('teamBudget.remainingLabel')}
                value={
                  teamRemaining != null ? (
                    <span className={teamRemaining < 0 ? 'text-err' : 'text-success'}>
                      <Money usd={teamRemaining} />
                    </span>
                  ) : (
                    <Money usd={null} />
                  )
                }
              />
            </div>

            <LimitRow
              label={t('teamBudget.budgetBarLabel')}
              used={teamSpend}
              cap={teamCap}
              over={teamRemaining != null && teamRemaining < 0}
              overBadge={t('teamBudget.overBadge')}
              note={
                teamEnabled
                  ? t('teamBudget.enforcedNote')
                  : t('teamBudget.disabledNote')
              }
              valueFormatter={(n) => <Money usd={n} />}
            />
          </div>
        )}

        {/* ── Always-visible attribution caveat ──────────────────────────── */}
        <div className="mt-4 flex items-start gap-2 rounded-xl border border-line bg-bg-2/40 p-3 text-xs">
          <Info className="mt-px h-4 w-4 shrink-0 text-accent" />
          <p className="text-fg-2">{t('teamBudget.attributionNote')}</p>
        </div>
      </Section>

      {/* ── Per-member budgets ───────────────────────────────────────────── */}
      <Section
        title={t('teamBudget.membersTitle')}
        hint={t('teamBudget.membersHint')}
      >
        {members.length === 0 ? (
          <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed border-line bg-bg-2/40 px-4 py-6 text-center">
            <Users className="h-5 w-5 text-fg-3" />
            <p className="text-sm text-fg-2">{t('teamBudget.membersEmpty')}</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-line">
          <div className="overflow-x-auto">
            <table className="w-full text-start text-[13px]">
              <thead>
                <tr className="border-b border-line bg-bg-2/50 text-[12px] font-bold uppercase tracking-[0.08em] text-fg-2">
                  <th className="px-3 py-2.5 text-start">{t('teamBudget.memberHeaders.member')}</th>
                  <th className="px-3 py-2.5 text-start">{t('teamBudget.memberHeaders.role')}</th>
                  <th className="px-3 py-2.5 text-end">{t('teamBudget.memberHeaders.budget')}</th>
                  <th className="px-3 py-2.5 text-end">{t('teamBudget.memberHeaders.spend')}</th>
                  <th className="px-3 py-2.5 text-end">{t('teamBudget.memberHeaders.remaining')}</th>
                  {isOwner && <th className="px-3 py-2.5 text-end w-px" />}
                </tr>
              </thead>
              <tbody>
                {members.map((m) => {
                  const cap = m.budget?.amount_usd != null ? Number(m.budget.amount_usd) : null
                  const spend = Number(m.spend_mtd) || 0
                  const remaining = m.remaining != null ? Number(m.remaining) : null
                  return (
                    <tr
                      key={m.user_id}
                      className="border-b border-line last:border-0"
                    >
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2.5">
                          <Avatar size="sm">
                            {m.avatar_url && (
                              <AvatarImage
                                src={m.avatar_url}
                                alt={m.display_name || m.email}
                              />
                            )}
                            <AvatarFallback className="text-[10px]">
                              {getInitials(m.display_name, m.email)}
                            </AvatarFallback>
                          </Avatar>
                          <div className="flex min-w-0 flex-col">
                            <span className="text-fg-1">
                              {m.display_name || m.email || t('teamBudget.unknownUser')}
                            </span>
                            {m.display_name && m.email && (
                              <span className="text-[11px] text-fg-3">
                                {m.email}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        {m.role ? (
                          <RoleBadge role={m.role} />
                        ) : (
                          <span className="text-fg-3">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-end font-mono tabular-nums text-fg-1">
                        {cap != null ? <Money usd={cap} /> : <span className="text-fg-3">—</span>}
                      </td>
                      <td className="px-3 py-2.5 text-end font-mono tabular-nums text-fg-2">
                        <Money usd={spend} />
                      </td>
                      <td className="px-3 py-2.5 text-end font-mono tabular-nums">
                        {remaining != null ? (
                          <span className={remaining < 0 ? 'text-err' : 'text-fg-2'}>
                            <Money usd={remaining} />
                          </span>
                        ) : (
                          <span className="text-fg-3">—</span>
                        )}
                      </td>
                      {isOwner && (
                        <td className="px-3 py-2.5 ps-2 text-end">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="gap-1.5"
                            onClick={() =>
                              setDialog({ kind: 'member', uid: m.user_id, member: m })
                            }
                          >
                            <Gauge className="h-3.5 w-3.5" />
                            {cap != null
                              ? t('teamBudget.editBudget')
                              : t('teamBudget.setBudget')}
                          </Button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          </div>
        )}
      </Section>

      {/* ── Set-budget dialogs (team + per-member share the component) ──── */}
      {dialog?.kind === 'team' && (
        <SetBudgetDialog
          open
          onClose={() => (saving ? null : setDialog(null))}
          title={t('teamBudget.dialogTeamTitle')}
          subtitle={teamSubtitle}
          currentAmount={teamCap}
          enabled={teamEnabled}
          busy={saving}
          onConfirm={handleTeamConfirm}
        />
      )}

      {dialog?.kind === 'member' && (
        <SetBudgetDialog
          open
          onClose={() => (saving ? null : setDialog(null))}
          title={t('teamBudget.dialogMemberTitle')}
          subtitle={t('teamBudget.dialogMemberSubtitle', {
            name:
              dialog.member?.display_name ||
              dialog.member?.email ||
              t('teamBudget.unknownUser'),
          })}
          currentAmount={
            dialog.member?.budget?.amount_usd != null
              ? Number(dialog.member.budget.amount_usd)
              : null
          }
          enabled={dialog.member?.budget?.enabled !== false}
          busy={saving}
          onConfirm={handleMemberConfirm}
        />
      )}
    </div>
  )
}

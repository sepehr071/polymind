import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Settings,
  Users,
  AlertTriangle,
  Cpu,
  Star,
  Share2,
  MessageSquare,
  Flame,
  BookOpen,
  Link as LinkIcon,
  Database,
  Wallet,
  ChevronDown,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

import projectService from '@/services/projectService'
import { useProject } from '@/context/ProjectContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useAuth } from '@/context/AuthContext'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'

import PageHeader from '@/components/layout/PageHeader'
import HeaderSlot from '@/components/layout/HeaderSlot'
import Ptile from '@/components/teams/Ptile'
import Section from '@/components/teams/Section'
import DangerZone from '@/components/teams/DangerZone'

import ProjectAccessTab from './components/ProjectAccessTab'
import DefaultsTab from './components/DefaultsTab'
import IntegrationsTab from './components/IntegrationsTab'
import KnowledgeTab from './components/KnowledgeTab'
import ProjectBillingTab from './components/ProjectBillingTab'

import SettingsBreadcrumb from '@/components/settings/SettingsBreadcrumb'

import { cn } from '@/lib/utils'

// User-pickable swatches (product data). The DEFAULT/fallback project colour is a
// theme token (accent/sky), not a hardcoded hex.
const DEFAULT_PROJECT_COLOR = 'hsl(var(--accent))'
const COLORS = ['#5c9aed', '#7c3aed', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#06b6d4', '#84cc16']

const TAB_IDS = ['general', 'access', 'defaults', 'billing', 'knowledge', 'integrations', 'danger']
const CORE_TAB_IDS = new Set(['general', 'access', 'defaults', 'billing'])
const ADVANCED_TAB_IDS = new Set(['knowledge', 'integrations', 'danger'])

// Table-type tabs render dense data tables (member rows, per-member budgets) and
// get the wide "dense" pane lane so columns breathe; everything else is a linear
// settings form and stays in the capped form lane.
const TABLE_TABS = new Set(['access', 'billing'])

// PageShell width lanes by tab — table tabs go dense, form tabs stay in the
// capped form lane (replaces the old magic max-w-[920px]/max-w-[120rem]).
const WIDTH_LANE = { reading: 'max-w-3xl', form: 'max-w-3xl', dense: 'max-w-[120rem]' }

// ---------------------------------------------------------------------------
// General tab — wraps existing settings form in a Section.
// ---------------------------------------------------------------------------
function GeneralTab({ project, onSaved }) {
  const { t } = useTranslation('projects')
  const [name, setName] = useState(project.name)
  const [color, setColor] = useState(project.color || COLORS[0])
  const [description, setDescription] = useState(project.description || '')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setName(project.name)
    setColor(project.color || COLORS[0])
    setDescription(project.description || '')
  }, [project])

  async function handleSave(e) {
    e.preventDefault()
    if (!name.trim()) { toast.error(t('projectSettings.toasts.nameRequired')); return }
    setBusy(true)
    try {
      await projectService.update(project._id, {
        name: name.trim(),
        color,
        description: description.trim() || null,
      })
      toast.success(t('projectSettings.toasts.projectUpdated'))
      await onSaved()
    } catch (ex) {
      toast.error(ex.response?.data?.error || t('projectSettings.toasts.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Section title={t('projectSettings.tabs.general')} hint={t('projectSettings.general.hint')}>
        <form onSubmit={handleSave} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="ps-name">{t('projectSettings.general.nameLabel')}</Label>
            <Input
              id="ps-name"
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={100}
              required
            />
          </div>

          <div className="space-y-2">
            <Label>{t('projectSettings.general.colorLabel')}</Label>
            <div className="flex gap-2 flex-wrap">
              {COLORS.map(c => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={cn(
                    'w-7 h-7 rounded-[10px] border border-line transition-transform hover:scale-110',
                    color === c ? 'ring-2 ring-accent ring-offset-2 ring-offset-bg-2' : '',
                  )}
                  style={{ background: c }}
                  aria-label={t('projectSettings.general.colorAriaLabel', { color: c })}
                />
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ps-desc">{t('projectSettings.general.descriptionLabel')}</Label>
            <textarea
              id="ps-desc"
              value={description}
              onChange={e => setDescription(e.target.value)}
              maxLength={500}
              rows={3}
              className="flex w-full rounded-[10px] border border-line bg-bg-2 px-3 py-2 text-sm text-fg-1 placeholder:text-fg-3 outline-none transition-[border-color,box-shadow] focus:border-accent focus:ring-[3px] focus:ring-accent/[0.18] disabled:cursor-not-allowed disabled:opacity-50 resize-none"
              placeholder={t('projectSettings.general.descriptionPlaceholder')}
            />
          </div>

          <div className="flex items-center justify-between pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              asChild
            >
              <Link to="/knowledge">
                <BookOpen className="h-3.5 w-3.5" />
                {t('projectSettings.general.openKnowledge')}
              </Link>
            </Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? t('projectSettings.general.saving') : t('projectSettings.general.saveChanges')}
            </Button>
          </div>
        </form>
      </Section>
    </div>
  )
}

function ArchiveSection({ project, onSaved }) {
  const { t } = useTranslation('projects')
  const { confirm, confirmDialog } = useConfirmDelete()
  const [busy, setBusy] = useState(false)
  const archived = !!project.archived

  async function handleToggle() {
    const next = !archived
    if (next) {
      const ok = await confirm({
        title: t('projectSettings.general.archiveConfirmTitle'),
        description: t('projectSettings.general.archiveConfirmBody'),
        confirmLabel: t('projectSettings.general.archiveConfirm'),
        destructive: true,
      })
      if (!ok) return
    }
    setBusy(true)
    try {
      await projectService.update(project._id, { archived: next })
      toast.success(t('projectSettings.toasts.projectUpdated'))
      await onSaved()
    } catch (ex) {
      toast.error(ex.response?.data?.error || t('projectSettings.toasts.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section
      title={t('projectSettings.general.archivedLabel')}
      hint={t('projectSettings.general.archivedDesc')}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Switch
            id="ps-archived"
            checked={archived}
            onCheckedChange={() => handleToggle()}
            disabled={busy}
          />
          <Label htmlFor="ps-archived" className="cursor-pointer">
            {t('projectSettings.general.archivedLabel')}
          </Label>
        </div>
      </div>
      {confirmDialog}
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function ProjectSettingsPage() {
  const { t } = useTranslation('projects')
  const { pid } = useParams()
  const nav = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { refresh: refreshProject, setActiveProject } = useProject()
  const { currentWorkspace, workspaces } = useWorkspace()
  const { user } = useAuth()

  const [project, setProject] = useState(null)
  const [memberCount, setMemberCount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showAdvanced, setShowAdvanced] = useState(() => {
    const t0 = searchParams.get('tab')
    return ADVANCED_TAB_IDS.has(t0)
  })

  const initialTab = TAB_IDS.includes(searchParams.get('tab'))
    ? searchParams.get('tab')
    : 'general'
  const [tab, setTab] = useState(initialTab)

  // Sync tab → URL.
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    if (next.get('tab') !== tab) {
      next.set('tab', tab)
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const loadProject = useCallback(async () => {
    try {
      const data = await projectService.get(pid)
      setProject(data)
    } catch (ex) {
      const status = ex.response?.status
      if (status === 403 || status === 404) {
        toast.error(t('projectSettings.toasts.notFoundOrDenied'))
        nav('/projects', { replace: true })
      } else {
        toast.error(t('projectSettings.toasts.loadFailed'))
      }
    } finally {
      setLoading(false)
    }
  }, [pid, nav, t])

  const loadMemberCount = useCallback(async () => {
    try {
      const list = await projectService.listMembers(pid)
      setMemberCount(Array.isArray(list) ? list.length : 0)
    } catch {
      setMemberCount(null)
    }
  }, [pid])

  useEffect(() => {
    loadProject()
    loadMemberCount()
  }, [loadProject, loadMemberCount])

  // Only the team owner (or a global super-admin) may view team settings.
  // Wait for the project to resolve so member_role is known before bouncing.
  useEffect(() => {
    if (!project) return
    if (project.member_role !== 'owner' && user?.role !== 'admin') {
      toast.error(t('projectSettings.toasts.settingsAccessDenied'))
      nav('/dashboard', { replace: true })
    }
  }, [project, user, nav, t])

  // Expand advanced tabs when deep-linked (knowledge / integrations / danger).
  useEffect(() => {
    if (ADVANCED_TAB_IDS.has(tab)) setShowAdvanced(true)
  }, [tab])

  // Resolve workspace doc for header context.
  const workspace = useMemo(() => {
    if (!project?.workspace_id) return null
    if (currentWorkspace?._id === project.workspace_id) return currentWorkspace
    return workspaces.find(w => w._id === project.workspace_id) || null
  }, [project?.workspace_id, currentWorkspace, workspaces])

  async function handleSaved() {
    await loadProject()
    await refreshProject()
  }

  async function handleDelete() {
    await projectService.delete(pid)
    const wid = project.workspace_id
    if (wid) {
      localStorage.removeItem(`active_project_id::${wid}`)
    }
    await refreshProject()
    nav('/projects', { replace: true })
  }

  // Pin toggle with optimistic update + revert.
  async function handleTogglePin() {
    if (!project) return
    const next = !project.pinned
    setProject(p => ({ ...p, pinned: next }))
    try {
      await projectService.setPinned(pid, next)
      await refreshProject()
      toast.success(next ? t('projectSettings.toasts.pinned') : t('projectSettings.toasts.unpinned'))
    } catch (ex) {
      setProject(p => ({ ...p, pinned: !next }))
      toast.error(ex.response?.data?.error || t('projectSettings.toasts.pinFailed'))
    }
  }

  function handleOpenChat() {
    if (project) setActiveProject(project)
    nav('/chat')
  }

  async function handleShare() {
    if (!project?._id) return
    const url = `${window.location.origin}/projects/${project._id}`
    try {
      await navigator.clipboard.writeText(url)
      toast.success(t('projectSettings.toasts.linkCopied'))
    } catch {
      toast.error(t('projectSettings.toasts.copyFailed'))
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  if (!project) return null

  const projectGroup = project.group || project.tags?.[0] || null

  // ----------------------------------------------------------------
  // Header
  // ----------------------------------------------------------------
  const titleNode = (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5 min-w-0">
      <Ptile size="lg" color={project.color || DEFAULT_PROJECT_COLOR} icon={project.icon || 'Folder'} />
      <span className="truncate min-w-0">{project.name}</span>
      {projectGroup && (
        <Badge
          variant="default"
          className="bg-accent/15 text-accent border border-accent/30 gap-1 max-sm:hidden"
        >
          <Flame className="h-3 w-3" />
          {projectGroup}
        </Badge>
      )}
      <Badge
        variant="default"
        className={cn(
          'gap-1 border',
          project.archived
            ? 'bg-warn/15 text-warn border-warn/30'
            : 'bg-success/15 text-success border-success/30',
        )}
      >
        {project.archived ? t('status.archived') : t('status.active')}
      </Badge>
    </span>
  )

  const headerActions = (
    <>
      <Button
        variant={project.pinned ? 'default' : 'outline'}
        size="sm"
        onClick={handleTogglePin}
        className="gap-1.5"
      >
        <Star className={cn('h-3.5 w-3.5', project.pinned && 'fill-current')} />
        {project.pinned ? t('projectSettings.general.unpin') : t('projectSettings.general.pin')}
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5"
        onClick={handleShare}
      >
        <Share2 className="h-3.5 w-3.5" />
        {t('projectSettings.general.share')}
      </Button>
      <Button size="sm" onClick={handleOpenChat} className="gap-1.5">
        <MessageSquare className="h-3.5 w-3.5" />
        {t('projectSettings.general.openChat')}
      </Button>
    </>
  )

  // ----------------------------------------------------------------
  // Tabs config — core always visible; advanced behind "More"
  // ----------------------------------------------------------------
  const coreTabs = [
    { id: 'general',  label: t('projectSettings.tabs.general'),  Icon: Settings },
    { id: 'access',   label: t('projectSettings.tabs.members'),  Icon: Users, count: memberCount ?? undefined },
    { id: 'defaults', label: t('projectSettings.tabs.defaults'), Icon: Cpu },
    { id: 'billing',  label: t('projectSettings.tabs.billing'),  Icon: Wallet },
  ]
  const advancedTabs = [
    { id: 'knowledge',    label: t('projectSettings.tabs.knowledge'),    Icon: Database },
    { id: 'integrations', label: t('projectSettings.tabs.integrations'), Icon: LinkIcon },
    { id: 'danger',       label: t('projectSettings.tabs.danger'),       Icon: AlertTriangle },
  ]
  const tabs = showAdvanced ? [...coreTabs, ...advancedTabs] : coreTabs

  // ----------------------------------------------------------------
  // Tab content
  // ----------------------------------------------------------------
  let body = null
  if (tab === 'general') {
    body = <GeneralTab project={project} onSaved={handleSaved} />
  } else if (tab === 'access') {
    body = <ProjectAccessTab project={project} workspace={workspace} />
  } else if (tab === 'defaults') {
    body = <DefaultsTab project={project} onSaved={handleSaved} />
  } else if (tab === 'billing') {
    body = (
      <ProjectBillingTab
        project={project}
        pid={pid}
        isOwner={project?.member_role === 'owner'}
      />
    )
  } else if (tab === 'knowledge') {
    body = <KnowledgeTab project={project} />
  } else if (tab === 'integrations') {
    body = <IntegrationsTab project={project} />
  } else if (tab === 'danger') {
    body = (
      <div className="space-y-6">
        <ArchiveSection project={project} onSaved={handleSaved} />
        <DangerZone
          title={t('projectSettings.danger.deleteTitle')}
          confirmText={project.name}
          onConfirm={handleDelete}
          description={t('projectSettings.danger.deleteDescription', { name: project.name })}
        />
      </div>
    )
  }

  // Pane width lane (token, not magic number): table tabs go dense, form tabs
  // stay in the capped form lane.
  const laneClass = TABLE_TABS.has(tab) ? WIDTH_LANE.dense : WIDTH_LANE.form

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      {/* Route controls (pin / share / open chat) live in the global top bar —
          no per-page glass header band. */}
      <HeaderSlot side="end">
        <div className="flex items-center gap-2">{headerActions}</div>
      </HeaderSlot>

      <div className={cn(laneClass, 'mx-auto space-y-6')}>
        <SettingsBreadcrumb level="team" name={project.name} pid={pid} />

        <PageHeader
          title={titleNode}
          subtitle={project.description}
        />

        {/* Canonical underline settings tabs (active = accent text + 2px accent
            bottom border; inactive = fg-2). */}
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="w-full overflow-x-auto">
            {tabs.map(({ id, label, Icon, count }) => (
              <TabsTrigger key={id} value={id}>
                <Icon className="h-4 w-4" />
                <span>{label}</span>
                {typeof count === 'number' && (
                  <span className="rounded-full bg-accent/10 px-1.5 text-[11px] font-semibold leading-tight text-accent">
                    {count}
                  </span>
                )}
              </TabsTrigger>
            ))}
            {!showAdvanced && (
              <button
                type="button"
                onClick={() => setShowAdvanced(true)}
                className="inline-flex shrink-0 items-center gap-1.5 px-3 py-1.5 text-sm text-fg-2 transition-colors hover:text-fg-0"
              >
                <ChevronDown className="h-4 w-4" />
                <span>{t('projectSettings.tabs.advanced')}</span>
              </button>
            )}
          </TabsList>
        </Tabs>

        <div>{body}</div>
      </div>
    </div>
  )
}

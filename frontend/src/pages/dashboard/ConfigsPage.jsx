import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Plus,
  Bot,
  Sliders,
  Search,
  MoreVertical,
  Edit2,
  Copy,
  Trash2,
  Globe,
  Lock,
  FolderOpen,
  ImageIcon,
  Sparkles,
} from 'lucide-react'
import { configService } from '../../services/chatService'
import ConfigEditor from '../../components/config/ConfigEditor'
import { useProject } from '../../context/ProjectContext'
import { useAuth } from '../../context/AuthContext'
import { cn } from '../../utils/cn'
import toast from 'react-hot-toast'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { IconTile } from '@/components/ui/icon-tile'
import { Segmented } from '@/components/ui/segmented'
import { StaggerContainer, StaggerItem } from '@/components/ui/animated-container'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export default function ConfigsPage() {
  const { t } = useTranslation('dashboard')
  const queryClient = useQueryClient()
  const { currentProject } = useProject()
  const { user } = useAuth()
  const projectId = currentProject?._id || null
  const currentUserId = user?.id || user?._id || null

  const [searchQuery, setSearchQuery] = useState('')
  const [isEditorOpen, setIsEditorOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState(null)
  const [scopeFilter, setScopeFilter] = useState(projectId ? 'project' : 'mine')

  const { data, isLoading } = useQuery({
    queryKey: ['configs', { projectId }],
    queryFn: () => configService.getConfigs(projectId ? { project_id: projectId } : undefined),
  })

  const deleteMutation = useMutation({
    mutationFn: configService.deleteConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['configs'] })
      toast.success(t('configs.assistantDeleted'))
    },
    onError: () => {
      toast.error(t('configs.failedToDelete'))
    },
  })

  const configs = data?.configs || []

  const filteredConfigs = useMemo(() => {
    const q = searchQuery.toLowerCase()
    const isOwned = (config) => {
      const owner = config.owner_id || config.owner_user_id
      return currentUserId != null && owner != null && String(owner) === String(currentUserId)
    }
    return configs.filter((config) => {
      if (scopeFilter === 'project') {
        if (!projectId || config.project_id !== projectId) return false
      } else if (scopeFilter === 'mine') {
        // "Mine" = everything the caller owns, regardless of visibility,
        // excluding configs scoped to the active project (those live under "Project").
        if (projectId && config.project_id === projectId) return false
        if (!isOwned(config)) return false
      } else if (scopeFilter === 'public') {
        if (config.visibility !== 'public') return false
      }
      if (!q) return true
      return (
        config.name.toLowerCase().includes(q) ||
        config.description?.toLowerCase().includes(q)
      )
    })
  }, [configs, scopeFilter, searchQuery, projectId, currentUserId])

  const handleCreate = () => {
    setEditingConfig(null)
    setIsEditorOpen(true)
  }

  const handleEdit = (config) => {
    setEditingConfig(config)
    setIsEditorOpen(true)
  }

  const handleDelete = async (configId) => {
    deleteMutation.mutate(configId)
  }

  const scopeItems = [
    { value: 'all', label: t('configs.scopeAll') },
    { value: 'mine', label: t('configs.scopeMine'), icon: <Lock className="h-3.5 w-3.5" /> },
    ...(projectId
      ? [{
          value: 'project',
          label: t('configs.scopeProject'),
          icon: <FolderOpen className="h-3.5 w-3.5" />,
          suffix: currentProject && (
            <span className="opacity-70 truncate max-w-[100px]">· {currentProject.name}</span>
          ),
        }]
      : []),
    { value: 'public', label: t('configs.scopePublic'), icon: <Globe className="h-3.5 w-3.5" /> },
  ]

  return (
    <PageShell width="standard">
        <PageHeader
          title={t('configs.title')}
          subtitle={t('configs.subtitle')}
          icon={Sliders}
          tone="emerald"
          actions={
            <Button onClick={handleCreate}>
              <Plus className="h-4 w-4" />
              {t('configs.createAssistant')}
            </Button>
          }
        />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative max-w-md flex-1">
            <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none z-10" />
            <Input
              type="text"
              placeholder={t('configs.searchPlaceholder')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="ps-9"
            />
          </div>

          <Segmented
            ariaLabel={t('configs.title')}
            value={scopeFilter}
            onChange={setScopeFilter}
            items={scopeItems}
            className="self-start sm:self-auto"
          />
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="p-5">
                  <div className="flex items-start gap-3 mb-3">
                    <Skeleton className="h-10 w-10 rounded-[10px]" />
                    <div className="min-w-0 flex-1 space-y-2">
                      <Skeleton className="h-4 w-3/4" />
                      <Skeleton className="h-3 w-1/3 rounded-full" />
                    </div>
                  </div>
                  <Skeleton className="h-3.5 w-full mb-1.5" />
                  <Skeleton className="h-3.5 w-5/6 mb-4" />
                  <div className="flex items-center justify-between border-t border-border pt-3">
                    <Skeleton className="h-3.5 w-20" />
                    <div className="flex items-center gap-1.5">
                      <Skeleton className="h-8 w-8 rounded-lg" />
                      <Skeleton className="h-8 w-8 rounded-lg" />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : filteredConfigs.length === 0 ? (
          <div className="text-center py-12">
            <Bot className="h-12 w-12 text-foreground-tertiary mx-auto mb-3" />
            <h3 className="text-lg font-medium text-foreground mb-1">
              {searchQuery ? t('configs.noMatchesFound') : t('configs.noAssistantsYet')}
            </h3>
            <p className="text-foreground-secondary mb-4">
              {searchQuery
                ? t('configs.tryDifferentTerm')
                : t('configs.createFirstAssistant')}
            </p>
            {!searchQuery && (
              <Button onClick={handleCreate}>
                <Plus className="h-4 w-4" />
                {t('configs.createAssistant')}
              </Button>
            )}
          </div>
        ) : (
          <StaggerContainer className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredConfigs.map((config) => (
              <StaggerItem key={config._id}>
                <ConfigCard
                  config={config}
                  onEdit={() => handleEdit(config)}
                  onDelete={() => handleDelete(config._id)}
                />
              </StaggerItem>
            ))}
          </StaggerContainer>
        )}

      {isEditorOpen && (
        <ConfigEditor
          config={editingConfig}
          onClose={() => {
            setIsEditorOpen(false)
            setEditingConfig(null)
          }}
          onSave={() => {
            setIsEditorOpen(false)
            setEditingConfig(null)
            queryClient.invalidateQueries({ queryKey: ['configs'] })
          }}
        />
      )}
    </PageShell>
  )
}

function ConfigCard({ config, onEdit, onDelete }) {
  const { t } = useTranslation('dashboard')
  const navigate = useNavigate()
  const { confirm, confirmDialog } = useConfirmDelete()
  const queryClient = useQueryClient()

  const isImage = config.parameters?.kind === 'image'

  const handleDelete = async () => {
    const ok = await confirm({
      title: t('configs.deleteAssistant.title'),
      description: t('configs.deleteAssistant.message', { name: config.name }),
      confirmLabel: t('configs.deleteAssistant.confirm'),
      cancelLabel: t('configs.deleteAssistant.cancel'),
      destructive: true,
    })
    if (!ok) return
    onDelete()
  }

  const toggleVisibility = async () => {
    try {
      if (config.visibility === 'public') {
        await configService.unpublishConfig(config._id)
        toast.success(t('configs.nowPrivate'))
      } else {
        await configService.publishConfig(config._id)
        toast.success(t('configs.nowPublic'))
      }
      queryClient.invalidateQueries({ queryKey: ['configs'] })
    } catch (error) {
      toast.error(t('configs.failedToUpdateVisibility'))
    }
  }

  const duplicateConfig = async () => {
    try {
      await configService.duplicateConfig(config._id)
      queryClient.invalidateQueries({ queryKey: ['configs'] })
      toast.success(t('configs.duplicated'))
    } catch (error) {
      toast.error(t('configs.failedToDuplicate'))
    }
  }

  const isPublic = config.visibility === 'public'
  const usesCount = config.stats?.uses_count || 0
  const isEmoji = config.avatar?.type === 'emoji'

  return (
    <Card hover className="group flex h-full flex-col transition-shadow">
      <CardContent className="flex flex-1 flex-col p-5">
        <div className="mb-3 flex items-start gap-3">
          {isEmoji ? (
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-emerald-500/10 text-xl ring-1 ring-inset ring-emerald-500/20 dark:bg-emerald-400/10 dark:ring-emerald-400/20">
              {config.avatar.value}
            </span>
          ) : (
            <IconTile
              icon={isImage ? ImageIcon : Bot}
              tone={isImage ? 'amber' : 'emerald'}
              size="xl"
            />
          )}

          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[14.5px] font-bold text-foreground">{config.name}</h3>
            <span className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-background-secondary px-2 py-0.5 text-[11px] font-semibold text-foreground-secondary">
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  isPublic ? 'bg-emerald-500' : 'bg-foreground-tertiary',
                )}
                aria-hidden="true"
              />
              {isPublic ? t('configs.public') : t('configs.private')}
            </span>
          </div>
        </div>

        <p className="mb-4 line-clamp-2 flex-1 text-sm text-muted-foreground">
          {config.description || t('configs.noDescription')}
        </p>

        <div className="flex items-center justify-between border-t border-border pt-3">
          <span className="truncate text-xs text-muted-foreground">
            {usesCount > 0 ? t('configs.usedTimes', { count: usesCount }) : '—'}
          </span>

          <div className="flex items-center gap-1">
            {isImage ? (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => navigate(`/image-studio?assistant=${config._id}`)}
                aria-label={t('common:config.open_in_studio')}
                className="h-8 w-8 rounded-lg"
              >
                <Sparkles className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="icon"
                onClick={onEdit}
                aria-label={t('configs.edit')}
                className="h-8 w-8 rounded-lg"
              >
                <Edit2 className="h-4 w-4" />
              </Button>
            )}

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t('configs.cardActions')}
                  className="h-8 w-8 rounded-lg"
                >
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuItem onClick={onEdit}>
                  <Edit2 className="h-4 w-4 me-2" />
                  {t('configs.edit')}
                </DropdownMenuItem>
                {isImage && (
                  <DropdownMenuItem onClick={() => navigate(`/image-studio?assistant=${config._id}`)}>
                    <Sparkles className="h-4 w-4 me-2" />
                    {t('common:config.open_in_studio')}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={duplicateConfig}>
                  <Copy className="h-4 w-4 me-2" />
                  {t('configs.duplicate')}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={toggleVisibility}>
                  {isPublic ? (
                    <>
                      <Lock className="h-4 w-4 me-2" />
                      {t('configs.makePrivate')}
                    </>
                  ) : (
                    <>
                      <Globe className="h-4 w-4 me-2" />
                      {t('configs.makePublic')}
                    </>
                  )}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleDelete}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="h-4 w-4 me-2" />
                  {t('configs.delete')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {confirmDialog}
      </CardContent>
    </Card>
  )
}

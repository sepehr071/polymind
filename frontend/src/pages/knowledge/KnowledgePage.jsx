import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Search, BookMarked, Star, Grid3X3, List, ChevronLeft, ChevronRight, Tag, X, Loader2, FolderInput, FolderTree } from 'lucide-react'
import { knowledgeService } from '../../services/knowledgeService'
import { knowledgeFolderService } from '../../services/knowledgeFolderService'
import { useProject } from '../../context/ProjectContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import KnowledgeCard from '../../components/knowledge/KnowledgeCard'
import KnowledgeEditModal from '../../components/knowledge/KnowledgeEditModal'
import KnowledgeDetailModal from '../../components/knowledge/KnowledgeDetailModal'
import KnowledgeFolderSidebar from '../../components/knowledge/KnowledgeFolderSidebar'
import CreateFolderModal from '../../components/knowledge/CreateFolderModal'
import MoveToFolderModal from '../../components/knowledge/MoveToFolderModal'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import EmptyState from '@/components/ui/empty-state'
import PageHeader from '@/components/layout/PageHeader'
import PageShell from '@/components/layout/PageShell'
import { StaggerContainer, StaggerItem } from '@/components/ui/animated-container'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { cn } from '../../utils/cn'
import { fmtNumber } from '../../utils/persianLocale'
import toast from 'react-hot-toast'

// Debounce hook
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return debouncedValue
}

export default function KnowledgePage() {
  const { t } = useTranslation('knowledge')
  const { t: tc } = useTranslation('common')
  const queryClient = useQueryClient()
  const { currentWorkspace } = useWorkspace()
  const { currentProject } = useProject()
  const projectId = currentProject?._id || null
  // 'null' (literal string) is the unfiled-scope sentinel the backend expects
  // when caller wants items not pinned to any project. Omit entirely when
  // there's no workspace at all (legacy behavior).
  const projectScopeParam = currentWorkspace
    ? (projectId ?? 'null')
    : undefined

  // UI state
  const [searchInput, setSearchInput] = useState('')
  const [selectedTag, setSelectedTag] = useState(null)
  const [selectedFolder, setSelectedFolder] = useState(null) // null = all, 'root' = unfiled, or folder_id
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [viewMode, setViewMode] = useState('grid')
  const [page, setPage] = useState(1)
  const [editItem, setEditItem] = useState(null)
  const [viewingItem, setViewingItem] = useState(null)
  // Mobile folders/tags drawer (the desktop aside is hidden below md).
  const [showOrgSheet, setShowOrgSheet] = useState(false)

  // Folder modal state
  const [showCreateFolderModal, setShowCreateFolderModal] = useState(false)
  const [editingFolder, setEditingFolder] = useState(null)

  // Move modal state
  const [moveItem, setMoveItem] = useState(null)

  // Debounced search
  const debouncedSearch = useDebounce(searchInput, 300)

  // Reset page when filters change
  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, selectedTag, favoritesOnly, selectedFolder])

  // Fetch folders (scoped to active project; 'null' sentinel = unfiled)
  const { data: foldersData, isLoading: isLoadingFolders } = useQuery({
    queryKey: ['knowledge-folders', { projectScope: projectScopeParam }],
    queryFn: () => knowledgeFolderService.list(
      projectScopeParam !== undefined ? { project_id: projectScopeParam } : {}
    )
  })

  // Fetch knowledge items
  const { data, isLoading, error } = useQuery({
    queryKey: ['knowledge', { page, search: debouncedSearch, tag: selectedTag, favoritesOnly, folder: selectedFolder, projectScope: projectScopeParam }],
    queryFn: () => knowledgeService.list({
      page,
      limit: 20,
      search: debouncedSearch || undefined,
      tag: selectedTag || undefined,
      favorite: favoritesOnly || undefined,
      folder_id: selectedFolder === null ? undefined : selectedFolder,
      ...(projectScopeParam !== undefined ? { project_id: projectScopeParam } : {})
    })
  })

  // Fetch tags. Shared ['knowledge-tags'] cache (also used by
  // SaveToKnowledgeButton); generous staleTime so the two consumers reuse one
  // fetch instead of each refetching on mount/focus.
  const { data: tagsData } = useQuery({
    queryKey: ['knowledge-tags'],
    queryFn: knowledgeService.getTags,
    staleTime: 5 * 60 * 1000
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: knowledgeService.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-tags'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-folders'] })
      toast.success(t('toast_deleted'))
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('toast_delete_fail'))
    }
  })

  // Toggle favorite mutation
  const toggleFavoriteMutation = useMutation({
    mutationFn: ({ id, currentValue }) => knowledgeService.toggleFavorite(id, currentValue),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('toast_fav_fail'))
    }
  })

  // Create folder mutation — pin to active project (null when in Unfiled view)
  const createFolderMutation = useMutation({
    mutationFn: (data) => knowledgeFolderService.create({
      ...data,
      project_id: projectId,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-folders'] })
      setShowCreateFolderModal(false)
      toast.success(t('toast_folder_created'))
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('toast_folder_fail_create'))
    }
  })

  // Update folder mutation
  const updateFolderMutation = useMutation({
    mutationFn: ({ id, data }) => knowledgeFolderService.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-folders'] })
      setEditingFolder(null)
      setShowCreateFolderModal(false)
      toast.success(t('toast_folder_updated'))
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('toast_folder_fail_update'))
    }
  })

  // Delete folder mutation
  const deleteFolderMutation = useMutation({
    mutationFn: knowledgeFolderService.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-folders'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      if (selectedFolder && selectedFolder !== 'root') {
        setSelectedFolder(null)
      }
      toast.success(t('toast_folder_deleted'))
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('toast_folder_fail_delete'))
    }
  })

  // Move to folder mutation
  const moveMutation = useMutation({
    mutationFn: ({ itemIds, folderId }) => knowledgeService.moveToFolder(itemIds, folderId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-folders'] })
      setMoveItem(null)
      toast.success(t('toast_moved'))
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('toast_move_fail'))
    }
  })

  const handleDelete = useCallback((id) => {
    deleteMutation.mutate(id)
  }, [deleteMutation])

  const handleToggleFavorite = useCallback((id, currentValue) => {
    toggleFavoriteMutation.mutate({ id, currentValue })
  }, [toggleFavoriteMutation])

  const handleEdit = useCallback((item) => {
    setEditItem(item)
  }, [])

  const handleTagClick = useCallback((tag) => {
    setSelectedTag(selectedTag === tag ? null : tag)
  }, [selectedTag])

  const handleMoveToFolder = useCallback((item) => {
    setMoveItem(item)
  }, [])

  const handleFolderSubmit = (data) => {
    if (editingFolder) {
      updateFolderMutation.mutate({ id: editingFolder._id, data })
    } else {
      createFolderMutation.mutate(data)
    }
  }

  const handleEditFolder = (folderId) => {
    const folder = folders.find(f => f._id === folderId)
    if (folder) {
      setEditingFolder(folder)
      setShowCreateFolderModal(true)
    }
  }

  const handleDeleteFolder = (folderId) => {
    deleteFolderMutation.mutate(folderId)
  }

  const handleMoveSubmit = (folderId) => {
    if (moveItem) {
      moveMutation.mutate({ itemIds: [moveItem._id], folderId })
    }
  }

  const clearFilters = () => {
    setSearchInput('')
    setSelectedTag(null)
    setFavoritesOnly(false)
    setSelectedFolder(null)
    setPage(1)
  }

  const items = data?.items || []
  const totalPages = data?.total_pages || 1
  const total = data?.total || 0
  const tags = tagsData?.tags || []
  const folders = foldersData?.folders || []
  const unfiledCount = foldersData?.unfiled_count || 0

  // selectedFolder participates so the toolbar "Clear all" and the filtered
  // empty-state reset both acknowledge an active folder selection (the folder
  // chip still offers its own targeted X to clear only the folder).
  const hasActiveFilters = !!(searchInput || selectedTag || favoritesOnly || selectedFolder)

  // Get folder name for display
  const getFolderName = () => {
    if (selectedFolder === null) return null
    if (selectedFolder === 'root') return t('unfiled')
    const folder = folders.find(f => f._id === selectedFolder)
    return folder?.name
  }

  // Folders + tags organization panel — shared between the desktop aside and
  // the mobile sheet. `onAfterSelect` lets the mobile sheet dismiss after a
  // pick so the user lands back on the list. `fadeFrom` matches the host
  // surface (aside = page bg, sheet = elevated) so the overflow fade blends.
  const renderOrgPanel = (onAfterSelect, fadeFrom = 'from-background') => (
    <>
      <KnowledgeFolderSidebar
        folders={folders}
        unfiledCount={unfiledCount}
        selectedFolder={selectedFolder}
        onSelectFolder={(f) => {
          setSelectedFolder(f)
          onAfterSelect?.()
        }}
        onCreateFolder={() => {
          setEditingFolder(null)
          setShowCreateFolderModal(true)
          onAfterSelect?.()
        }}
        onEditFolder={(id) => {
          handleEditFolder(id)
          onAfterSelect?.()
        }}
        onDeleteFolder={handleDeleteFolder}
        isLoading={isLoadingFolders}
      />

      {/* Tags section */}
      <div className="border-t border-border p-3">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold text-foreground-tertiary uppercase tracking-wider">
            {t('tags_heading')}
          </h3>
          {tags.length > 0 && (
            <span className="text-xs text-foreground-tertiary tabular-nums">
              {fmtNumber(tags.length)}
            </span>
          )}
        </div>
        {/* Scrollable tag list with a bottom fade hinting at overflow. */}
        <div className="relative">
          <div className="space-y-0.5 max-h-40 overflow-y-auto">
            {tags.map((tag) => (
              <Button
                key={tag}
                variant={selectedTag === tag ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => {
                  setSelectedTag(selectedTag === tag ? null : tag)
                  onAfterSelect?.()
                }}
                className={cn(
                  'w-full justify-start px-2 h-7 text-sm truncate',
                  selectedTag === tag && 'bg-accent/10 text-accent hover:bg-accent/20 hover:text-accent'
                )}
              >
                #{tag}
              </Button>
            ))}
            {tags.length === 0 && (
              <p className="text-xs text-foreground-tertiary py-2">
                {t('no_tags')}
              </p>
            )}
          </div>
          {tags.length > 8 && (
            <div
              aria-hidden="true"
              className={cn(
                'pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t to-transparent',
                fadeFrom
              )}
            />
          )}
        </div>
      </div>
    </>
  )

  // Search field — lives in the PageHeader actions slot (end side).
  const searchField = (
    <div className="relative w-full sm:w-72">
      <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-foreground-tertiary" />
      <Input
        type="text"
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        placeholder={t('search_placeholder')}
        className="w-full ps-10 pe-9"
      />
      {searchInput && (
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setSearchInput('')}
          className="absolute end-1 top-1/2 -translate-y-1/2 h-7 w-7"
        >
          <X className="h-4 w-4" />
        </Button>
      )}
    </div>
  )

  return (
    <div className="h-full flex flex-col">
      {/* Main content area — flush rail + content lane */}
      <div className="flex-1 overflow-hidden flex">
        {/* Folders sidebar (desktop only) — flush full-height surf2 column */}
        <aside className="hidden md:flex flex-col w-60 flex-shrink-0 bg-background-secondary border-e border-border overflow-hidden">
          {renderOrgPanel(undefined, 'from-background-secondary')}
        </aside>

        {/* Content lane — canonical PageShell width="wide" */}
        <PageShell width="wide" className="min-w-0">
          <PageHeader
            title={t('title')}
            subtitle={
              currentWorkspace
                ? t('subtitle.workspace', {
                    workspace: currentWorkspace.name,
                    project: currentProject?.name || t('unfiled'),
                  })
                : t('subtitle.personal')
            }
            icon={BookMarked}
            tone="emerald"
            backTo="/dashboard"
            backLabel={tc('actions.back')}
            actions={searchField}
          />

          {/* Filter bar */}
          <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Mobile folders/tags trigger (desktop uses the aside) */}
            <Sheet open={showOrgSheet} onOpenChange={setShowOrgSheet}>
              <SheetTrigger asChild>
                <Button variant="secondary" size="sm" className="gap-1.5 md:hidden">
                  <FolderTree className="h-4 w-4" />
                  {t('organize')}
                </Button>
              </SheetTrigger>
              <SheetContent side="start" className="w-72 p-0 flex flex-col">
                <SheetHeader className="px-4 py-3 border-b border-border text-start">
                  <SheetTitle>{t('organize')}</SheetTitle>
                </SheetHeader>
                <div className="flex-1 overflow-y-auto flex flex-col">
                  {renderOrgPanel(() => setShowOrgSheet(false), 'from-background-elevated')}
                </div>
              </SheetContent>
            </Sheet>

            {/* Favorites toggle — accent-soft active (no bespoke warning tone) */}
            <Button
              variant={favoritesOnly ? "default" : "secondary"}
              size="sm"
              onClick={() => setFavoritesOnly(!favoritesOnly)}
              className={cn(
                'gap-1.5',
                favoritesOnly && 'bg-accent/10 border-accent/30 text-accent hover:bg-accent/20 hover:text-accent'
              )}
            >
              <Star className={cn('h-4 w-4', favoritesOnly && 'fill-current')} />
              {t('favorites')}
            </Button>

            {/* Current folder chip */}
            {getFolderName() && (
              <Badge variant="secondary" className="gap-1.5 ps-2 pe-1 bg-accent/10 border-accent/30 text-accent hover:bg-accent/10">
                <FolderInput className="h-3.5 w-3.5" />
                {getFolderName()}
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setSelectedFolder(null)}
                  className="h-4 w-4 p-0 hover:bg-accent/20"
                >
                  <X className="h-3 w-3" />
                </Button>
              </Badge>
            )}

            {/* Selected tag chip */}
            {selectedTag && (
              <Badge variant="secondary" className="gap-1.5 ps-2 pe-1 bg-accent/10 border-accent/30 text-accent hover:bg-accent/10">
                <Tag className="h-3.5 w-3.5" />
                #{selectedTag}
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setSelectedTag(null)}
                  className="h-4 w-4 p-0 hover:bg-accent/20"
                >
                  <X className="h-3 w-3" />
                </Button>
              </Badge>
            )}

            {/* Clear filters */}
            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={clearFilters}
                className="text-foreground-tertiary hover:text-foreground-secondary"
              >
                {t('clear_all')}
              </Button>
            )}
          </div>

          {/* View mode toggle — canonical segmented filter */}
          <div className="flex items-center gap-1 rounded-[11px] border border-border bg-background-secondary p-1">
            {[
              { mode: 'grid', Icon: Grid3X3, label: t('grid_view') },
              { mode: 'list', Icon: List, label: t('list_view') },
            ].map(({ mode, Icon, label }) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                title={label}
                aria-label={label}
                aria-pressed={viewMode === mode}
                className={cn(
                  'grid h-8 w-8 place-items-center rounded-lg transition-colors',
                  viewMode === mode
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-foreground-secondary hover:text-foreground'
                )}
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
        </div>

          {/* Loading state */}
          {isLoading && (
            <div className="flex items-center justify-center py-16">
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="h-8 w-8 animate-spin text-accent" />
                <span className="text-foreground-secondary">{t('loading')}</span>
              </div>
            </div>
          )}

          {/* Error state */}
          {error && !isLoading && (
            <div className="flex items-center justify-center py-16">
              <div className="text-center">
                <p className="text-foreground-secondary mb-2">{t('error_load')}</p>
                <Button
                  variant="link"
                  onClick={() => queryClient.refetchQueries({ queryKey: ['knowledge'] })}
                  className="text-accent hover:underline"
                >
                  {t('try_again')}
                </Button>
              </div>
            </div>
          )}

          {/* Empty state */}
          {!isLoading && !error && items.length === 0 && (
            hasActiveFilters ? (
              <EmptyState
                icon={BookMarked}
                title={t('empty_filtered')}
                description={t('empty_hint_filtered')}
                primaryCta={{
                  label: t('clear_filters'),
                  onClick: clearFilters,
                }}
              />
            ) : (
              <EmptyState
                icon={BookMarked}
                icon3d="/icons/3d/book.png"
                title={t('emptyState.title')}
                description={t('emptyState.description')}
              />
            )
          )}

          {/* Knowledge cards */}
          {!isLoading && !error && items.length > 0 && (
            <>
              <StaggerContainer
                className={cn(
                  viewMode === 'grid'
                    ? 'grid gap-4 grid-cols-1 sm:grid-cols-2'
                    : 'space-y-3'
                )}
              >
                {items.map((item) => (
                  <StaggerItem key={item._id}>
                    <KnowledgeCard
                      item={item}
                      folders={folders}
                      onEdit={handleEdit}
                      onDelete={handleDelete}
                      onToggleFavorite={handleToggleFavorite}
                      onTagClick={handleTagClick}
                      onMoveToFolder={handleMoveToFolder}
                      onViewDetail={setViewingItem}
                    />
                  </StaggerItem>
                ))}
              </StaggerContainer>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 mt-6">
                  <Button
                    variant="secondary"
                    size="icon"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="text-sm text-foreground-secondary px-4">
                    {t('page_of', { page, total: totalPages })}
                  </span>
                  <Button
                    variant="secondary"
                    size="icon"
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              )}

              {/* Total count */}
              <div className="mt-4 text-sm text-foreground-tertiary text-center">
                {t('items_count', { count: total })}
              </div>
            </>
          )}
        </PageShell>
      </div>

      {/* Edit modal */}
      {editItem && (
        <KnowledgeEditModal
          item={editItem}
          folders={folders}
          onClose={() => setEditItem(null)}
        />
      )}

      {/* Detail modal */}
      {viewingItem && (
        <KnowledgeDetailModal
          item={viewingItem}
          folders={folders}
          onClose={() => setViewingItem(null)}
          onEdit={(item) => {
            setViewingItem(null)
            setEditItem(item)
          }}
        />
      )}

      {/* Create/Edit folder modal */}
      <CreateFolderModal
        isOpen={showCreateFolderModal}
        onClose={() => {
          setShowCreateFolderModal(false)
          setEditingFolder(null)
        }}
        onSubmit={handleFolderSubmit}
        isLoading={createFolderMutation.isPending || updateFolderMutation.isPending}
        editFolder={editingFolder}
      />

      {/* Move to folder modal */}
      <MoveToFolderModal
        isOpen={!!moveItem}
        onClose={() => setMoveItem(null)}
        onMove={handleMoveSubmit}
        folders={folders}
        itemCount={1}
        isLoading={moveMutation.isPending}
      />
    </div>
  )
}

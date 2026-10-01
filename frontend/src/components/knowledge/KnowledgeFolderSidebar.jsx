import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Folder, FolderPlus, MoreVertical, Pencil, Trash2, FileText } from 'lucide-react'
import { cn } from '../../utils/cn'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'

// Plan note: KnowledgeFolderSidebar receives folders + handlers from
// KnowledgePage. The actual project_id-aware fetch happens there (see
// KnowledgePage). We keep the sidebar a pure presentational component so it
// stays in sync with whichever project the parent is scoped to.

export default function KnowledgeFolderSidebar({
  folders = [],
  unfiledCount = 0,
  selectedFolder,
  onSelectFolder,
  onCreateFolder,
  onEditFolder,
  onDeleteFolder,
  isLoading
}) {
  const { t } = useTranslation('knowledge')
  // Folder pending delete-confirmation in the AlertDialog ({ id, name } | null).
  const [folderToDelete, setFolderToDelete] = useState(null)

  // Canonical rail-item recipe (Consistent UI System): radius9, ~9px pad, fg2
  // default text; ACTIVE = accent-soft bg + inset accent-line ring + accent text.
  const railItem = (active) =>
    cn(
      'w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-start transition-colors',
      active
        ? 'bg-accent/10 text-accent ring-1 ring-inset ring-accent/25'
        : 'text-foreground-secondary hover:text-foreground hover:bg-background-tertiary',
    )

  const confirmDelete = () => {
    if (folderToDelete) {
      onDeleteFolder?.(folderToDelete.id)
      setFolderToDelete(null)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-3 border-b border-border">
        <h3 className="mb-2 text-[11px] font-bold text-foreground-tertiary uppercase tracking-wider">
          {t('sidebar.folders_heading')}
        </h3>
        <Button
          onClick={onCreateFolder}
          size="sm"
          className="w-full gap-2"
          title={t('sidebar.create_folder')}
        >
          <FolderPlus className="h-4 w-4" />
          {t('sidebar.create_folder')}
        </Button>
      </div>

      {/* Folder list */}
      <div className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {/* All items */}
        <button
          onClick={() => onSelectFolder(null)}
          className={railItem(selectedFolder === null)}
        >
          <FileText className="h-4 w-4 flex-shrink-0" />
          <span className="flex-1 truncate">{t('sidebar.all_items')}</span>
        </button>

        {/* Unfiled items */}
        <button
          onClick={() => onSelectFolder('root')}
          className={railItem(selectedFolder === 'root')}
        >
          <FileText className="h-4 w-4 flex-shrink-0 opacity-50" />
          <span className="flex-1 truncate">{t('sidebar.unfiled')}</span>
          {unfiledCount > 0 && (
            <span className="text-xs text-foreground-tertiary">{unfiledCount}</span>
          )}
        </button>

        {/* Divider */}
        {folders.length > 0 && (
          <div className="border-t border-border my-2" />
        )}

        {/* Folders. Row is a div (not a button) so the kebab trigger can be a
            real <button> sibling without nesting interactive elements. */}
        {folders.map((folder) => (
          <div
            key={folder._id}
            className={cn(
              railItem(selectedFolder === folder._id),
              'group gap-1 pe-1',
            )}
          >
            <button
              onClick={() => onSelectFolder(folder._id)}
              className="flex-1 min-w-0 flex items-center gap-2 text-start"
            >
              <Folder
                className="h-4 w-4 flex-shrink-0"
                style={{ color: folder.color }}
              />
              <span className="flex-1 truncate">{folder.name}</span>
              {folder.item_count > 0 && (
                <span className="text-xs text-foreground-tertiary">{folder.item_count}</span>
              )}
            </button>

            {/* Always-visible kebab — primary affordance (touch-safe, no
                off-screen RTL placement). side/align chosen so it opens
                in-bounds within the narrow sidebar. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 flex-shrink-0 text-foreground-tertiary hover:text-foreground"
                  title={t('sidebar.folder_actions')}
                  aria-label={t('sidebar.folder_actions')}
                >
                  <MoreVertical className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" side="bottom" className="min-w-[10rem]">
                <DropdownMenuItem onSelect={() => onEditFolder?.(folder._id)}>
                  <Pencil className="h-3.5 w-3.5" />
                  {t('sidebar.rename')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => setFolderToDelete({ id: folder._id, name: folder.name })}
                  className="text-error focus:text-error focus:bg-error/10"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t('sidebar.delete')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ))}

        {/* Empty state */}
        {!isLoading && folders.length === 0 && (
          <p className="text-xs text-foreground-tertiary text-center py-4 px-2">
            {t('sidebar.no_folders')}
          </p>
        )}
      </div>

      {/* Destructive delete confirmation (triggered by the kebab menu). */}
      <AlertDialog open={!!folderToDelete} onOpenChange={(open) => !open && setFolderToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('sidebar.delete_title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('sidebar.confirm_delete', { name: folderToDelete?.name || '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('sidebar.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} variant="destructive">
              {t('sidebar.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Folder, FileText, Loader2, Check } from 'lucide-react'
import { cn } from '../../utils/cn'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'

export default function MoveToFolderModal({
  isOpen,
  onClose,
  onMove,
  folders = [],
  itemCount = 1,
  isLoading
}) {
  const { t } = useTranslation('knowledge')
  const [selectedFolder, setSelectedFolder] = useState(null) // null = root/unfiled

  const handleMove = () => {
    onMove(selectedFolder)
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {itemCount > 1 ? t('move.title_other', { count: itemCount }) : t('move.title_one')}
          </DialogTitle>
        </DialogHeader>

        <ScrollArea className="max-h-64">
          <div className="space-y-1 pe-4">
            {/* Root/Unfiled option */}
            <button
              onClick={() => setSelectedFolder(null)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors text-start',
                selectedFolder === null
                  ? 'bg-accent/10 text-accent'
                  : 'text-foreground-secondary hover:text-foreground hover:bg-background-tertiary'
              )}
            >
              <FileText className="h-5 w-5 flex-shrink-0 opacity-50" />
              <span className="flex-1">{t('move.unfiled')}</span>
              {selectedFolder === null && (
                <Check className="h-4 w-4" />
              )}
            </button>

            {/* Folders */}
            {folders.map((folder) => (
              <button
                key={folder._id}
                onClick={() => setSelectedFolder(folder._id)}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors text-start',
                  selectedFolder === folder._id
                    ? 'bg-accent/10 text-accent'
                    : 'text-foreground-secondary hover:text-foreground hover:bg-background-tertiary'
                )}
              >
                <Folder
                  className="h-5 w-5 flex-shrink-0"
                  style={{ color: folder.color }}
                />
                <span className="flex-1 truncate">{folder.name}</span>
                {selectedFolder === folder._id && (
                  <Check className="h-4 w-4" />
                )}
              </button>
            ))}

            {/* Empty state */}
            {folders.length === 0 && (
              <p className="text-sm text-foreground-tertiary text-center py-4">
                {t('move.no_folders')}
              </p>
            )}
          </div>
        </ScrollArea>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={onClose}
          >
            {t('move.cancel')}
          </Button>
          <Button
            onClick={handleMove}
            disabled={isLoading}
          >
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin me-2" />
                {t('move.moving')}
              </>
            ) : (
              t('move.move')
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

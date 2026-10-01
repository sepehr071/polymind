import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Plus, Save, Loader2, Folder } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { knowledgeService } from '../../services/knowledgeService'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export default function KnowledgeEditModal({ item, folders = [], onClose }) {
  const { t } = useTranslation('knowledge')
  const [title, setTitle] = useState(item?.title || '')
  const [content, setContent] = useState(item?.content || item?.content_preview || '')
  const [tags, setTags] = useState(item?.tags || [])
  const [folderId, setFolderId] = useState(item?.folder_id || '')
  const [newTag, setNewTag] = useState('')
  const queryClient = useQueryClient()

  // List rows carry only a truncated ``content_preview``; the editor's
  // read-only content panel needs the real content, so fetch the full item by
  // id on open (preview shows meanwhile).
  const { data: full } = useQuery({
    queryKey: ['knowledge', item?._id],
    queryFn: () => knowledgeService.get(item._id),
    enabled: !!item?._id,
    staleTime: 60_000,
  })

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => knowledgeService.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-tags'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-folders'] })
      toast.success(t('edit.toast_updated'))
      onClose()
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('edit.toast_fail'))
    }
  })

  // Reset form when item changes
  useEffect(() => {
    if (item) {
      setTitle(item.title || '')
      setContent(item.content || item.content_preview || '')
      setTags(item.tags || [])
      setFolderId(item.folder_id || '')
    }
  }, [item])

  // Upgrade the read-only content panel from preview to full once fetched.
  useEffect(() => {
    if (full?.item?.content != null) {
      setContent(full.item.content)
    }
  }, [full])

  const handleAddTag = () => {
    // Allow Unicode letters/numbers (Persian, etc.), collapse runs of
    // separators (spaces/disallowed chars) into a single hyphen, then trim
    // hyphens. Lowercase folds Latin without touching scripts that have no case.
    const tag = newTag
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}-]+/gu, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 30)
    if (tag && !tags.includes(tag)) {
      setTags([...tags, tag])
    }
    setNewTag('')
  }

  const handleRemoveTag = (tagToRemove) => {
    setTags(tags.filter(t => t !== tagToRemove))
  }

  const handleSave = () => {
    if (!title.trim()) {
      toast.error(t('edit.toast_title_required'))
      return
    }

    updateMutation.mutate({
      id: item._id,
      data: {
        title: title.trim(),
        tags,
        folder_id: folderId || null
      }
    })
  }

  if (!item) return null

  return (
    <Dialog open={!!item} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('edit.title')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 overflow-y-auto flex-1 py-4">
          {/* Title input */}
          <div className="space-y-2">
            <Label htmlFor="title">{t('edit.title_label')}</Label>
            <Input
              id="title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('edit.title_placeholder')}
              maxLength={200}
            />
          </div>

          {/* Folder selection */}
          <div className="space-y-2">
            <Label htmlFor="folder">{t('edit.folder_label')}</Label>
            <Select value={folderId || '__none__'} onValueChange={(v) => setFolderId(v === '__none__' ? '' : v)}>
              <SelectTrigger id="folder" className="w-full">
                <div className="flex items-center gap-2">
                  <Folder className="h-4 w-4 text-muted-foreground" />
                  <SelectValue placeholder={t('edit.no_folder')} />
                </div>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">{t('edit.no_folder')}</SelectItem>
                {folders.map((folder) => (
                  <SelectItem key={folder._id} value={folder._id}>
                    {folder.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Content preview (read-only) */}
          <div className="space-y-2">
            <Label>{t('edit.content_label')}</Label>
            <div className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-muted-foreground text-sm max-h-40 overflow-y-auto whitespace-pre-wrap">
              {content}
            </div>
          </div>

          {/* Tags input */}
          <div className="space-y-2">
            <Label htmlFor="tags">{t('edit.tags_label')}</Label>
            <div className="flex gap-2">
              <Input
                id="tags"
                type="text"
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleAddTag()
                  }
                }}
                placeholder={t('edit.tag_placeholder')}
                maxLength={30}
                className="flex-1"
              />
              <Button
                onClick={handleAddTag}
                disabled={!newTag.trim()}
                size="icon"
                variant="default"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>

            {/* Selected tags */}
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {tags.map((tag) => (
                  <Badge key={tag} variant="secondary" className="gap-1">
                    #{tag}
                    <button
                      onClick={() => handleRemoveTag(tag)}
                      className="p-0.5 hover:bg-accent/20 rounded-full"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={onClose}
          >
            {t('edit.cancel')}
          </Button>
          <Button
            onClick={handleSave}
            disabled={updateMutation.isPending || !title.trim()}
          >
            {updateMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin me-2" />
                {t('edit.saving')}
              </>
            ) : (
              <>
                <Save className="h-4 w-4 me-2" />
                {t('edit.save')}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

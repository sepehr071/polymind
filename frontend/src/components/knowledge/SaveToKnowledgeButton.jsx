import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Bookmark, X, Plus, Loader2 } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { knowledgeService } from '../../services/knowledgeService'
import toast from 'react-hot-toast'
import { cn } from '../../utils/cn'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'

export default function SaveToKnowledgeButton({
  message,
  conversationId,
  sourceType = 'chat',
  className
}) {
  const { t } = useTranslation('knowledge')
  const [isOpen, setIsOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [tags, setTags] = useState([])
  const [newTag, setNewTag] = useState('')
  const queryClient = useQueryClient()

  // Fetch existing tags for suggestions. Shares the ['knowledge-tags'] cache
  // with KnowledgePage; a generous staleTime keeps the suggestions warm so
  // reopening the dialog (or opening it across multiple chat messages) reuses
  // the cached list instead of refetching on every mount.
  const { data: tagsData } = useQuery({
    queryKey: ['knowledge-tags'],
    queryFn: knowledgeService.getTags,
    enabled: isOpen, // Only fetch when modal is open
    staleTime: 5 * 60 * 1000, // 5 min — shared with KnowledgePage
    gcTime: 10 * 60 * 1000
  })

  // Create mutation
  const createMutation = useMutation({
    mutationFn: knowledgeService.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-tags'] })
      toast.success(t('save_button.toast_saved'))
      handleClose()
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('save_button.toast_fail'))
    }
  })

  // Generate a default title from the content
  useEffect(() => {
    if (isOpen && !title && message?.content) {
      // Use first line or first 50 chars as default title
      const firstLine = message.content.split('\n')[0]
      const defaultTitle = firstLine.length > 50
        ? firstLine.substring(0, 50) + '...'
        : firstLine
      setTitle(defaultTitle)
    }
  }, [isOpen, message?.content, title])

  const handleClose = () => {
    setIsOpen(false)
    setTitle('')
    setTags([])
    setNewTag('')
  }

  const handleAddTag = () => {
    const tag = newTag.trim().toLowerCase().replace(/[^a-z0-9-]/g, '')
    if (tag && !tags.includes(tag)) {
      setTags([...tags, tag])
    }
    setNewTag('')
  }

  const handleRemoveTag = (tagToRemove) => {
    setTags(tags.filter(t => t !== tagToRemove))
  }

  const handleSelectSuggestedTag = (tag) => {
    if (!tags.includes(tag)) {
      setTags([...tags, tag])
    }
  }

  const handleSave = () => {
    if (!title.trim()) {
      toast.error(t('save_button.toast_title_required'))
      return
    }

    createMutation.mutate({
      source_type: sourceType,
      source_id: conversationId,
      message_id: message._id,
      content: message.content,
      title: title.trim(),
      tags
    })
  }

  const existingTags = tagsData?.tags || []
  const suggestedTags = existingTags.filter(t => !tags.includes(t)).slice(0, 8)

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className={cn(
          'p-1.5 rounded-md text-foreground-tertiary hover:text-foreground hover:bg-background-tertiary transition-colors',
          className
        )}
        title={t('save_button.title')}
      >
        <Bookmark className="h-3.5 w-3.5" />
      </button>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('save_button.dialog_title')}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Content preview */}
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                {t('save_button.content_preview')}
              </Label>
              <ScrollArea className="h-24 rounded-lg border bg-muted/50 p-3">
                <div
                  dir="auto"
                  className="text-sm text-muted-foreground whitespace-pre-wrap break-words"
                >
                  {message?.content?.substring(0, 300)}
                  {message?.content?.length > 300 && '...'}
                </div>
              </ScrollArea>
            </div>

            {/* Title input */}
            <div className="space-y-2">
              <Label htmlFor="knowledge-title" className="text-xs text-muted-foreground">
                {t('save_button.title_label')}
              </Label>
              <Input
                id="knowledge-title"
                dir="auto"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('save_button.title_placeholder')}
                maxLength={200}
              />
            </div>

            {/* Tags input */}
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                {t('save_button.tags_label')}
              </Label>
              <div className="flex gap-2">
                <Input
                  value={newTag}
                  onChange={(e) => setNewTag(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleAddTag()
                    }
                  }}
                  placeholder={t('save_button.tag_placeholder')}
                  className="flex-1"
                  maxLength={30}
                />
                <Button
                  onClick={handleAddTag}
                  disabled={!newTag.trim()}
                  size="icon"
                  variant="secondary"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>

              {/* Selected tags */}
              {tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {tags.map((tag) => (
                    <Badge
                      key={tag}
                      variant="secondary"
                      className="gap-1 pe-1"
                    >
                      #{tag}
                      <button
                        onClick={() => handleRemoveTag(tag)}
                        className="p-0.5 hover:bg-background rounded-full ms-0.5"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              )}

              {/* Suggested tags */}
              {suggestedTags.length > 0 && (
                <div className="mt-2">
                  <span className="text-xs text-muted-foreground">{t('save_button.suggestions')} </span>
                  <div className="inline-flex flex-wrap gap-1 mt-1">
                    {suggestedTags.map((tag) => (
                      <button
                        key={tag}
                        onClick={() => handleSelectSuggestedTag(tag)}
                        className="px-2 py-0.5 bg-muted text-muted-foreground text-xs rounded-full hover:bg-primary/10 hover:text-primary transition-colors"
                      >
                        #{tag}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={handleClose}>
              {t('save_button.cancel')}
            </Button>
            <Button
              onClick={handleSave}
              disabled={createMutation.isPending || !title.trim()}
            >
              {createMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 me-2 animate-spin" />
                  {t('save_button.saving')}
                </>
              ) : (
                <>
                  <Bookmark className="h-4 w-4 me-2" />
                  {t('save_button.save')}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

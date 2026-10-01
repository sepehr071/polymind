import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Folder, Loader2 } from 'lucide-react'
import { cn } from '../../utils/cn'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Badge } from '../ui/badge'

// `key` maps to i18n create_folder.colors.<key> for an accessible color name.
const PRESET_COLORS = [
  { value: '#5c9aed', key: 'blue' }, // default
  { value: '#22c55e', key: 'green' },
  { value: '#eab308', key: 'yellow' },
  { value: '#f97316', key: 'orange' },
  { value: '#ef4444', key: 'red' },
  { value: '#a855f7', key: 'purple' },
  { value: '#ec4899', key: 'pink' },
  { value: '#6b7280', key: 'gray' },
]

export default function CreateFolderModal({
  isOpen,
  onClose,
  onSubmit,
  isLoading,
  editFolder = null,
}) {
  const { t } = useTranslation('knowledge')
  const [name, setName] = useState('')
  const [color, setColor] = useState('#5c9aed')

  // Reset form when modal opens or editFolder changes
  useEffect(() => {
    if (isOpen) {
      if (editFolder) {
        setName(editFolder.name || '')
        setColor(editFolder.color || '#5c9aed')
      } else {
        setName('')
        setColor('#5c9aed')
      }
    }
  }, [isOpen, editFolder])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!name.trim()) return

    onSubmit({
      name: name.trim(),
      color
    })
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {editFolder ? t('create_folder.title_edit') : t('create_folder.title_create')}
          </DialogTitle>
          <DialogDescription>
            {editFolder ? t('create_folder.desc_edit') : t('create_folder.desc_create')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name input */}
          <div className="space-y-2">
            <Label htmlFor="folder-name">{t('create_folder.name_label')}</Label>
            <Input
              id="folder-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('create_folder.name_placeholder')}
              maxLength={100}
              autoFocus
            />
          </div>

          {/* Color picker */}
          <div className="space-y-2" role="radiogroup" aria-label={t('create_folder.color_label')}>
            <Label>{t('create_folder.color_label')}</Label>
            <div className="flex items-center gap-2 flex-wrap">
              {PRESET_COLORS.map((presetColor) => {
                const isSelected = color === presetColor.value
                const colorName = t(`create_folder.colors.${presetColor.key}`)
                return (
                  <button
                    key={presetColor.value}
                    type="button"
                    role="radio"
                    aria-checked={isSelected}
                    aria-label={colorName}
                    onClick={() => setColor(presetColor.value)}
                    className={cn(
                      'w-8 h-8 rounded-full transition-all hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                      isSelected && 'ring-2 ring-offset-2 ring-offset-background ring-foreground scale-110'
                    )}
                    style={{ backgroundColor: presetColor.value }}
                    title={colorName}
                  />
                )
              })}
            </div>
          </div>

          {/* Preview */}
          <div className="space-y-2">
            <Label>{t('create_folder.preview_label')}</Label>
            <Badge variant="secondary" className="px-3 py-2 h-auto gap-2">
              <Folder className="h-4 w-4" style={{ color }} />
              <span className="text-foreground">{name || t('create_folder.folder_name_placeholder')}</span>
            </Badge>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('create_folder.cancel')}
            </Button>
            <Button type="submit" disabled={isLoading || !name.trim()}>
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin me-2" />
                  {editFolder ? t('create_folder.saving') : t('create_folder.creating')}
                </>
              ) : (
                <>
                  <Folder className="h-4 w-4 me-2" />
                  {editFolder ? t('create_folder.save') : t('create_folder.create')}
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { promptTemplateService } from '../../services/promptTemplateService'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'

// Stable i18n slug from a template name; MUST match the keys in common.json's
// image.templates.* exactly. (Shared shape with TemplateGallery.)
const slugify = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')

/**
 * Fill-in dialog for templates carrying `{{variable}}` placeholders. Substitutes
 * the user's values into the localized body and reports the result via `onApply`.
 * Records the usage_count side-effect (promptTemplateService.useTemplate) at the
 * moment of apply — same trigger point as the pre-split TemplateSelector.
 *
 * Props:
 *   template      template object (has `_id`, `name`, `variables`, `template_text`)
 *   open          boolean — dialog open state.
 *   onOpenChange  (next: boolean) => void
 *   onApply       (filledText: string, template) => void — fired on successful apply.
 */
export default function TemplateFillDialog({ template, open, onOpenChange, onApply }) {
  const { t } = useTranslation('common')
  const [variables, setVariables] = useState({})

  // Reset the field values whenever a fresh template is opened.
  useEffect(() => {
    if (open && template?.variables) {
      const initial = {}
      template.variables.forEach((v) => { initial[v] = '' })
      setVariables(initial)
    }
  }, [open, template])

  if (!template) return null

  const handleApply = () => {
    // Require every variable filled.
    const emptyVars = template.variables.filter((v) => !variables[v] || !variables[v].trim())
    if (emptyVars.length > 0) {
      toast.error(t('image.fill_in', { fields: emptyVars.join(', ') }))
      return
    }

    // Substitute into the localized body (falls back to raw English).
    let finalText = t('image.templates.' + slugify(template.name) + '.body', { defaultValue: template.template_text })
    Object.keys(variables).forEach((varName) => {
      const regex = new RegExp(`{{${varName}}}`, 'g')
      finalText = finalText.replace(regex, variables[varName])
    })

    // Record usage (fire-and-forget) exactly where the old dialog did.
    promptTemplateService.useTemplate(template._id).catch((err) => {
      console.error('Failed to record template usage:', err)
    })

    onApply(finalText, template)
    onOpenChange(false)
    toast.success(t('image.template_applied'))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('image.fill_variables')}</DialogTitle>
          <div className="text-sm text-muted-foreground">
            {t('image.templates.' + slugify(template.name) + '.title', { defaultValue: template.name })}
          </div>
        </DialogHeader>

        <div className="space-y-3">
          {template.variables.map((varName) => (
            <div key={varName}>
              <label className="block text-sm font-medium mb-1 capitalize">
                {t('image.variables.' + varName, { defaultValue: varName.replace(/_/g, ' ') })}
              </label>
              <Input
                type="text"
                value={variables[varName] || ''}
                onChange={(e) => setVariables({ ...variables, [varName]: e.target.value })}
                placeholder={t('image.variables.' + varName, { defaultValue: varName.replace(/_/g, ' ') })}
              />
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('image.cancel')}
          </Button>
          <Button onClick={handleApply}>
            {t('image.apply_template')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

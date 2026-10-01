import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Plus, Edit, Trash2, Loader2, Save, X, Wand2 } from 'lucide-react'
import { promptTemplateService } from '../../services/promptTemplateService'
import toast from 'react-hot-toast'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'

const CATEGORY_KEYS = [
  'product_photography',
  'advertisement',
  'social_media',
  'lifestyle',
  'hero_banner',
  'tech_saas',
  'food_restaurant',
  'fashion_apparel',
]

export default function PromptTemplatesPage() {
  const { t } = useTranslation('admin')
  const queryClient = useQueryClient()
  const { confirm, confirmDialog } = useConfirmDelete()
  const [showForm, setShowForm] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState(null)
  const [formData, setFormData] = useState({
    name: '',
    category: '',
    template_text: '',
    description: '',
    variables: '',
  })

  const { data: templatesData, isLoading } = useQuery({
    queryKey: ['adminPromptTemplates'],
    queryFn: () => promptTemplateService.getTemplates(),
  })

  const createMutation = useMutation({
    mutationFn: promptTemplateService.createTemplate,
    onSuccess: () => {
      queryClient.invalidateQueries(['adminPromptTemplates'])
      toast.success(t('promptTemplates.createSuccess'))
      resetForm()
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('promptTemplates.createFailed'))
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => promptTemplateService.updateTemplate(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['adminPromptTemplates'])
      toast.success(t('promptTemplates.updateSuccess'))
      resetForm()
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('promptTemplates.updateFailed'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: promptTemplateService.deleteTemplate,
    onSuccess: () => {
      queryClient.invalidateQueries(['adminPromptTemplates'])
      toast.success(t('promptTemplates.deleteSuccess'))
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || t('promptTemplates.deleteFailed'))
    },
  })

  const resetForm = () => {
    setFormData({ name: '', category: '', template_text: '', description: '', variables: '' })
    setEditingTemplate(null)
    setShowForm(false)
  }

  const handleEdit = (template) => {
    setEditingTemplate(template)
    setFormData({
      name: template.name,
      category: template.category,
      template_text: template.template_text,
      description: template.description || '',
      variables: template.variables?.join(', ') || '',
    })
    setShowForm(true)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const templateData = {
      name: formData.name.trim(),
      category: formData.category,
      template_text: formData.template_text.trim(),
      description: formData.description.trim(),
      variables: formData.variables
        ? formData.variables.split(',').map(v => v.trim()).filter(Boolean)
        : [],
    }
    if (editingTemplate) {
      updateMutation.mutate({ id: editingTemplate._id, data: templateData })
    } else {
      createMutation.mutate(templateData)
    }
  }

  const handleDelete = async (template) => {
    const ok = await confirm({
      title: t('promptTemplates.deleteTitle'),
      description: t('templates.deleteConfirmDesc', { name: template.name }),
      confirmLabel: t('templates.delete'),
      cancelLabel: t('promptTemplates.cancel'),
      destructive: true,
    })
    if (!ok) return
    deleteMutation.mutate(template._id)
  }

  const templates = templatesData?.templates || []

  return (
    <PageShell width="wide">
        {/* Header */}
        <PageHeader
          icon={Wand2}
          tone="sky"
          title={t('promptTemplates.title')}
          subtitle={t('promptTemplates.subtitle')}
          actions={
            <Button onClick={() => setShowForm(!showForm)}>
              <Plus className="w-5 h-5 me-2" />
              {t('promptTemplates.newTemplate')}
            </Button>
          }
        />

        {/* Form */}
        {showForm && (
          <Card>
            <CardContent className="pt-6">
              <h2 className="text-lg font-semibold text-foreground mb-4">
                {editingTemplate ? t('promptTemplates.editTitle') : t('promptTemplates.newTitle')}
              </h2>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="name">{t('promptTemplates.nameRequired')}</Label>
                    <Input
                      id="name"
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      required
                    />
                  </div>

                  <div>
                    <Label htmlFor="category">{t('promptTemplates.categoryRequired')}</Label>
                    <Select
                      value={formData.category}
                      onValueChange={(value) => setFormData({ ...formData, category: value })}
                      required
                    >
                      <SelectTrigger id="category">
                        <SelectValue placeholder={t('promptTemplates.categoryPlaceholder')} />
                      </SelectTrigger>
                      <SelectContent>
                        {CATEGORY_KEYS.map((key) => (
                          <SelectItem key={key} value={key}>
                            {t(`promptTemplates.categories.${key}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div>
                  <Label htmlFor="template_text">{t('promptTemplates.templateTextRequired')}</Label>
                  <Textarea
                    id="template_text"
                    value={formData.template_text}
                    onChange={(e) => setFormData({ ...formData, template_text: e.target.value })}
                    rows={4}
                    placeholder={t('promptTemplates.templateTextPlaceholder')}
                    required
                  />
                  <p className="text-xs text-foreground-tertiary mt-1">
                    {t('promptTemplates.templateTextHint')}
                  </p>
                </div>

                <div>
                  <Label htmlFor="description">{t('promptTemplates.description')}</Label>
                  <Textarea
                    id="description"
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={2}
                    placeholder={t('promptTemplates.descriptionPlaceholder')}
                  />
                </div>

                <div>
                  <Label htmlFor="variables">{t('promptTemplates.variables')}</Label>
                  <Input
                    id="variables"
                    type="text"
                    value={formData.variables}
                    onChange={(e) => setFormData({ ...formData, variables: e.target.value })}
                    placeholder={t('promptTemplates.variablesPlaceholder')}
                  />
                  <p className="text-xs text-foreground-tertiary mt-1">
                    {t('promptTemplates.variablesHint')}
                  </p>
                </div>

                <div className="flex gap-2 justify-end">
                  <Button type="button" variant="outline" onClick={resetForm}>
                    <X className="w-4 h-4 me-2" />
                    {t('promptTemplates.cancel')}
                  </Button>
                  <Button
                    type="submit"
                    disabled={createMutation.isPending || updateMutation.isPending}
                  >
                    {(createMutation.isPending || updateMutation.isPending) ? (
                      <>
                        <Loader2 className="w-4 h-4 me-2 animate-spin" />
                        {t('promptTemplates.saving')}
                      </>
                    ) : (
                      <>
                        <Save className="w-4 h-4 me-2" />
                        {editingTemplate ? t('promptTemplates.update') : t('promptTemplates.create')}
                      </>
                    )}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        {/* Templates List */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-accent" />
          </div>
        ) : templates.length === 0 ? (
          <div className="text-center py-12 text-foreground-tertiary">
            <p>{t('promptTemplates.noTemplates')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {templates.map((template) => (
              <Card key={template._id}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <h3 className="font-semibold text-foreground">{template.name}</h3>
                        <Badge variant="secondary">
                          {t(`promptTemplates.categories.${template.category}`, { defaultValue: template.category.replace(/_/g, ' ') })}
                        </Badge>
                        {template.usage_count > 0 && (
                          <span className="text-xs text-foreground-tertiary">
                            {t('promptTemplates.usedCount', { count: template.usage_count })}
                          </span>
                        )}
                      </div>
                      {template.description && (
                        <p className="text-sm text-foreground-secondary mb-2">
                          {template.description}
                        </p>
                      )}
                      <p className="text-sm text-foreground-tertiary line-clamp-2">
                        {template.template_text}
                      </p>
                      {template.variables && template.variables.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {template.variables.map(v => (
                            <Badge key={v} variant="outline">{v}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2 ms-4">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleEdit(template)}
                        aria-label={t('common:actions.edit', { defaultValue: 'Edit' })}
                      >
                        <Edit className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(template)}
                        disabled={deleteMutation.isPending}
                        aria-label={t('common:actions.delete', { defaultValue: 'Delete' })}
                      >
                        <Trash2 className="w-4 h-4 text-error" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

      {confirmDialog}
    </PageShell>
  )
}

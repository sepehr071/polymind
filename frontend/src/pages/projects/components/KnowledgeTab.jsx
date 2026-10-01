import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Database, Folder as FolderIcon, ExternalLink } from 'lucide-react'
import Section from '@/components/teams/Section'
import Ptile from '@/components/teams/Ptile'
import { Button } from '@/components/ui/button'
import { knowledgeFolderService } from '@/services/knowledgeFolderService'

/**
 * KnowledgeTab — read-only summary of folders scoped to this project.
 * Deep-links to the Knowledge Vault filtered by project.
 */
export default function KnowledgeTab({ project }) {
  const { t } = useTranslation('projects')
  const nav = useNavigate()
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await knowledgeFolderService.list({
          project_id: project._id,
        })
        const list = Array.isArray(data) ? data : data?.folders || []
        if (alive) setFolders(list)
      } catch (err) {
        if (alive) setError(err.response?.data?.error || t('projectSettings.knowledge.loadFailed'))
      } finally {
        if (alive) setLoading(false)
      }
    }
    if (project?._id) load()
    return () => {
      alive = false
    }
  }, [project?._id, t])

  return (
    <div className="space-y-4">
      <Section
        title={t('projectSettings.knowledge.title')}
        hint={t('projectSettings.knowledge.hint')}
        action={
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={() => nav(`/knowledge?project=${project._id}`)}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t('projectSettings.knowledge.openVault')}
          </Button>
        }
      >
        {loading ? (
          <div className="px-2 py-6 text-sm text-fg-3">{t('projectSettings.knowledge.loading')}</div>
        ) : error ? (
          <div className="px-2 py-6 text-sm text-err">{error}</div>
        ) : folders.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
            <Database className="h-6 w-6 text-fg-3" />
            <p className="text-sm text-fg-2">{t('projectSettings.knowledge.empty')}</p>
            <p className="text-[11.5px] text-fg-3 max-w-md">
              {t('projectSettings.knowledge.emptyHint')}
            </p>
          </div>
        ) : (
          <ul className="flex flex-col">
            {folders.map((f) => {
              const itemCount =
                typeof f.item_count === 'number'
                  ? f.item_count
                  : Array.isArray(f.items)
                    ? f.items.length
                    : null
              return (
                <li
                  key={f._id}
                  className="flex items-center gap-3 py-2 border-b border-line last:border-0"
                >
                  <Ptile
                    color={f.color || 'hsl(var(--accent))'}
                    icon={FolderIcon}
                    size="sm"
                    gradient
                  />
                  <span className="grow truncate text-[13px] text-fg-1">
                    {f.name || t('projectSettings.knowledge.untitledFolder')}
                  </span>
                  {itemCount != null && (
                    <span className="text-[11px] text-fg-3 font-mono">
                      {t('projectSettings.knowledge.itemCount', { count: itemCount })}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Section>
    </div>
  )
}

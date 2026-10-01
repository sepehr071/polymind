import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Loader2, ArrowLeft, FileWarning, BookmarkPlus, Camera } from 'lucide-react'
import { shareService } from '../../services/shareService'
import SharedChatView from '../../components/chat/SharedChatView'
import { Button } from '../../components/ui/button'

/**
 * SharedChatPage — the /share/:token destination. Any logged-in user can view a
 * FROZEN snapshot and **save their own copy** to keep or continue. The copy is
 * fully independent of the original (it survives the original being deleted, and
 * the original owner's later messages never touch it). Its own minimal shell —
 * read-only preview, no sidebar, no composer.
 */
export default function SharedChatPage() {
  const { token } = useParams()
  const { t } = useTranslation('chat')
  const navigate = useNavigate()
  const [saving, setSaving] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['shared-snapshot', token],
    queryFn: () => shareService.getSnapshot(token),
    enabled: !!token,
    retry: false,
    staleTime: Infinity,
  })

  const saveToMyChats = async () => {
    setSaving(true)
    try {
      const { conversation_id } = await shareService.saveSnapshot(token)
      toast.success(t('sharedView.saved'))
      navigate(`/chat/${conversation_id}`)
    } catch {
      toast.error(t('sharedView.saveError'))
      setSaving(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex min-h-app-dvh items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    )
  }

  const snapshot = data?.snapshot
  if (isError || !snapshot?.messages) {
    return (
      <div className="flex min-h-app-dvh flex-col items-center justify-center gap-4 bg-background px-6 text-center">
        <FileWarning className="h-10 w-10 text-foreground-tertiary" />
        <p className="text-sm text-foreground-secondary">{t('sharedView.notFound')}</p>
        <Link
          to="/chat"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
        >
          <ArrowLeft className="h-4 w-4 rtl:-scale-x-100" />
          {t('sharedView.backToApp')}
        </Link>
      </div>
    )
  }

  const title = snapshot.conversation?.title || t('sharedView.untitled')

  return (
    <div className="min-h-app-dvh bg-background">
      <header className="sticky top-0 z-10 border-b border-border/60 bg-background-secondary">
        <div className="mx-auto flex max-w-[768px] items-center gap-3 px-4 py-3">
          <Link
            to="/chat"
            className="inline-flex items-center gap-1.5 text-sm text-foreground-secondary hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4 rtl:-scale-x-100" />
            <span className="hidden sm:inline">{t('sharedView.backToApp')}</span>
          </Link>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-foreground" title={title}>
              {title}
            </h1>
            <p className="flex items-center gap-1 text-xs text-foreground-tertiary">
              <Camera className="h-3 w-3" />
              {t('sharedView.snapshotBadge')}
            </p>
          </div>
          <Button onClick={saveToMyChats} disabled={saving} size="sm" className="shrink-0 gap-1.5">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <BookmarkPlus className="h-4 w-4" />}
            <span className="hidden sm:inline">{t('sharedView.save')}</span>
          </Button>
        </div>
      </header>

      <SharedChatView messages={snapshot.messages} />

      {/* Footer CTA — restate that this is a snapshot they can make their own. */}
      <div className="mx-auto max-w-[768px] px-4 pb-10">
        <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-background-secondary/50 px-4 py-6 text-center">
          <p className="text-sm text-foreground-secondary">{t('sharedView.saveCta')}</p>
          <Button onClick={saveToMyChats} disabled={saving} className="gap-1.5">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <BookmarkPlus className="h-4 w-4" />}
            {t('sharedView.save')}
          </Button>
        </div>
      </div>
    </div>
  )
}

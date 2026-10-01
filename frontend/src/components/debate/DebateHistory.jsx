import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2, ChevronRight, Loader2, Scale } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { debateService } from '../../services/debateService'
import { cn } from '../../utils/cn'
import { fmtDate } from '../../utils/dateLocale'
import { Button } from '../ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import toast from 'react-hot-toast'

export default function DebateHistory({ onClose, onLoadSession }) {
  const { t } = useTranslation('debate')
  const queryClient = useQueryClient()
  const [deletingId, setDeletingId] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['debate-sessions'],
    queryFn: () => debateService.listSessions(),
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => debateService.deleteSession(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['debate-sessions'])
      toast.success(t('historyModal.deleteSuccess'))
      setDeletingId(null)
    },
    onError: (error) => {
      toast.error(error.message || t('historyModal.deleteFailed'))
      setDeletingId(null)
    },
  })

  const sessions = data?.sessions || []

  const handleDelete = (e, sessionId) => {
    e.stopPropagation()
    if (deletingId) return
    setDeletingId(sessionId)
    deleteMutation.mutate(sessionId)
  }

  const statusLabel = (status) => {
    if (status === 'completed') return t('historyModal.completed')
    if (status === 'in_progress') return t('historyModal.in_progress')
    return t('historyModal.pending')
  }

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg max-h-[80vh] flex flex-col gap-0 p-0 overflow-hidden">
        {/* Header */}
        <DialogHeader className="flex-row items-center gap-3 space-y-0 px-6 py-4 border-b border-border">
          <Scale className="h-5 w-5 text-accent" />
          <DialogTitle>{t('historyModal.title')}</DialogTitle>
        </DialogHeader>

        {/* Sessions List */}
        <div className="overflow-y-auto max-h-[60vh]">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-accent" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="text-center py-12 px-6">
              <Scale className="h-12 w-12 mx-auto mb-3 text-foreground-tertiary opacity-50" />
              <p className="text-foreground-secondary">{t('historyModal.noDebates')}</p>
              <p className="text-sm text-foreground-tertiary mt-1">
                {t('historyModal.noDebatesDesc')}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {sessions.map((session) => (
                <button
                  key={session._id}
                  onClick={() => onLoadSession(session)}
                  className="w-full flex items-center gap-3 px-6 py-4 text-start hover:bg-background-tertiary transition-colors group"
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-foreground truncate">
                      {session.topic}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-foreground-tertiary">
                        {t('historyModal.debaters', { count: session.debater_count || session.debaters?.length || 0 })}
                      </span>
                      <span className="text-foreground-tertiary">·</span>
                      <span className="text-xs text-foreground-tertiary">
                        {t('historyModal.rounds', { count: session.rounds || 3 })}
                      </span>
                      <span className="text-foreground-tertiary">·</span>
                      <span className={cn(
                        'text-xs px-1.5 py-0.5 rounded',
                        session.status === 'completed'
                          ? 'bg-success/15 text-success'
                          : session.status === 'in_progress'
                            ? 'bg-warning/20 text-warning'
                            : 'bg-background-tertiary text-foreground-tertiary'
                      )}>
                        {statusLabel(session.status || 'pending')}
                      </span>
                    </div>
                    <p className="text-xs text-foreground-tertiary mt-1">
                      {fmtDate(new Date(session.created_at), 'MMM d, yyyy, HH:mm')}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={(e) => handleDelete(e, session._id)}
                    disabled={deletingId === session._id}
                    className="h-9 w-9 text-foreground-tertiary hover:text-destructive hover:bg-destructive/10 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all"
                  >
                    {deletingId === session._id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                  <ChevronRight className="h-4 w-4 text-foreground-tertiary rtl:rotate-180" />
                </button>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

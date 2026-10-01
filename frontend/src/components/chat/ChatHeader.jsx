import { memo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { MoreHorizontal, FileText, FileJson, FileDown, Pencil, FolderInput, Share2, Users } from 'lucide-react'
import { chatService } from '../../services/chatService'
import HeaderSlot from '../layout/HeaderSlot'
import MoveChatToProjectModal from './MoveChatToProjectModal'
import ShareDialog from './ShareDialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../ui/dialog'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import PillBar from './PillBar'
import { PrivacyBadge } from '@/components/privacy/ModelPrivacyCallout'
import { resolvePrivacyMode } from '@/constants/modelPrivacy'
import { getModelIdFromQuick, isQuickModel } from '@/constants/models'

/**
 * ChatHeader — no longer a bar of its own. It portals the chat's controls into
 * the single global Header (ChatGPT-parity): the MODEL pill goes into the
 * inline-start slot, the overflow menu into the inline-end slot. The header
 * center stays empty (the sidebar's active row identifies the open chat).
 *
 * Overflow actions (Share / Export / Move / Rename) all require an existing
 * conversation — a fresh chat shows only the model pill, no overflow trigger.
 * The rename dialog + move modal render alongside the portals (not inside the
 * Header), so they mount as normal Radix portals.
 */
// Memoized: ChatPage re-renders on every streaming token; header props stay
// stable during stream when parent keeps callbacks + conversation ref steady.
function ChatHeader({
  conversation,
  onExportMarkdown,
  onExportJson,
  onExportPdf,
  // Model picker props
  selectedConfig,
  configs = [],
  selectedConfigId,
  onSelectConfig,
  onConversationMoved,
  onConversationRenamed,
}) {
  const { t } = useTranslation('chat')
  const queryClient = useQueryClient()
  const [moveOpen, setMoveOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [renaming, setRenaming] = useState(false)

  const openRename = () => {
    setRenameValue(conversation?.title || '')
    setRenameOpen(true)
  }

  const submitRename = async (e) => {
    e?.preventDefault()
    const next = renameValue.trim()
    if (!next || renaming || !conversation?._id) return
    if (next === (conversation?.title || '')) { setRenameOpen(false); return }
    setRenaming(true)
    try {
      await chatService.updateConversation(conversation._id, { title: next })
      onConversationRenamed?.(next)
      setRenameOpen(false)
    } catch {
      toast.error(t('header.renameError'))
    } finally {
      setRenaming(false)
    }
  }

  // Notify the chat view that shares changed so the header pill + indicators
  // re-derive from a fresh conversation payload.
  const onSharesChanged = () => {
    if (!conversation?._id) return
    queryClient.invalidateQueries({ queryKey: ['conversation', conversation._id] })
    queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }

  const isShared = !!conversation?.share?.is_shared

  // Local AI only when the live picker is on polymind/local-ai; personas without
  // model_id default to cloud (OpenRouter path).
  const modelId = isQuickModel(selectedConfigId)
    ? getModelIdFromQuick(selectedConfigId)
    : (selectedConfig?.model_id || null)
  const privacyMode = resolvePrivacyMode('model', { modelId })

  return (
    <>
      <HeaderSlot side="start">
        <div className="flex items-center gap-2 min-w-0">
          <PillBar
            selectedConfig={selectedConfig}
            configs={configs}
            selectedConfigId={selectedConfigId}
            onSelectConfig={onSelectConfig}
          />
          <PrivacyBadge mode={privacyMode} className="hidden sm:inline-flex shrink-0" />
        </div>
      </HeaderSlot>

      {/* Fresh chat (no conversation) → model pill only, no overflow trigger. */}
      {conversation && (
        <HeaderSlot side="end">
          <div className="flex items-center gap-1">
          {isShared && (
            <button
              type="button"
              onClick={() => setShareOpen(true)}
              title={t('share.sharedTitle')}
              // Canonical CHIP tokens: pill radius99, accent-soft bg, 11px/600.
              className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-1 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/15"
            >
              <Users className="h-3.5 w-3.5" />
              {t('share.sharedBadge')}
            </button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t('input.moreActions')}
                className="h-8 w-8 rounded-[9px]"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem onClick={() => setShareOpen(true)} className="gap-2 cursor-pointer">
                <Share2 className="h-4 w-4" />
                {t('header.share')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onExportMarkdown} className="gap-2 cursor-pointer">
                <FileText className="h-4 w-4" />
                {t('header.exportMarkdown')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onExportJson} className="gap-2 cursor-pointer">
                <FileJson className="h-4 w-4" />
                {t('header.exportJson')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onExportPdf} className="gap-2 cursor-pointer">
                <FileDown className="h-4 w-4" />
                {t('header.exportPdf')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setMoveOpen(true)} className="gap-2 cursor-pointer">
                <FolderInput className="h-4 w-4" />
                {t('header.moveToProject')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={openRename} className="gap-2 cursor-pointer">
                <Pencil className="h-4 w-4" />
                {t('header.renameConversation')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          </div>
        </HeaderSlot>
      )}

      {conversation && (
        <MoveChatToProjectModal
          open={moveOpen}
          onOpenChange={setMoveOpen}
          conversationId={conversation._id}
          currentProjectId={conversation.project_id || null}
          onMoved={(pid) => onConversationMoved?.(pid)}
        />
      )}

      {conversation && (
        <ShareDialog
          open={shareOpen}
          onOpenChange={setShareOpen}
          conversationId={conversation._id}
          onSharesChanged={onSharesChanged}
        />
      )}

      {conversation && (
        <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>{t('header.renameConversation')}</DialogTitle>
            </DialogHeader>
            <form onSubmit={submitRename} className="space-y-4">
              <Input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                placeholder={t('header.renamePlaceholder')}
                maxLength={200}
              />
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => setRenameOpen(false)}>
                  {t('header.renameCancel')}
                </Button>
                <Button type="submit" disabled={!renameValue.trim() || renaming}>
                  {t('header.renameSave')}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}

export default memo(ChatHeader)

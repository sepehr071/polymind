import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import ConversationListSection from '../../../components/layout/sidebar/ConversationListSection'
import { Button } from '../../../components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '../../../components/ui/sheet'

// ---------------------------------------------------------------------------
// ChatRail — the chat route's OWN conversation history rail.
//
// This is NOT the (removed) global Sidebar: no company switcher, no user menu,
// no nav zones. Just New-chat + the self-contained ConversationListSection.
//
// Desktop (>= 768): inline collapsible solid column (w-72, bg-background-secondary).
// Collapse owned + persisted by ChatPage (localStorage['chat-rail-collapsed']).
// When collapsed inline rail renders nothing. Open/collapse TOGGLE lives in
// global top bar (ChatPage HeaderSlot) — rail has no own header band.
//
// Mobile (< 768): NOT inline. ChatPage owns `mobileOpen`/`onMobileOpenChange`
// and we render the rail inside a Sheet anchored to the inline-start edge.
// Selecting a conversation closes the sheet (via onNavClick → onMobileOpenChange
// (false)).
//
// Props:
//   isMobile            boolean — viewport < 768 (drives inline vs Sheet)
//   collapsed           boolean — desktop inline rail hidden (ignored on mobile)
//   mobileOpen          boolean — Sheet open state (mobile only)
//   onMobileOpenChange  (next: boolean) => void — Sheet open setter (mobile only)
// ---------------------------------------------------------------------------

// Shared inner body: New-chat button + the conversation list. `onNavClick`
// fires after a conversation row is tapped (used on mobile to close the sheet).
function RailBody({ onNavClick }) {
  const { t } = useTranslation('layout')
  const navigate = useNavigate()

  const handleNewChat = () => {
    navigate('/chat')
    onNavClick?.()
  }

  return (
    <>
      {/* New chat — full-width accent button (canonical rail new-item). */}
      <div className="p-3">
        <Button onClick={handleNewChat} className="w-full gap-2">
          <Plus className="h-5 w-5" />
          {t('sidebar.newChat')}
        </Button>
      </div>

      {/* Self-contained history surface. Parent gives it height via flex-1. */}
      <ConversationListSection
        showContent
        onNavClick={onNavClick}
        className="flex-1 min-h-0"
      />
    </>
  )
}

// Memoized: ChatPage re-renders on every streaming token; rail props are
// stable (booleans + setState) so we skip ConversationListSection work.
function ChatRail({
  isMobile,
  collapsed,
  mobileOpen,
  onMobileOpenChange,
}) {
  const { t } = useTranslation('layout')

  // ---- Mobile: render the rail inside a left/inline-start Sheet. ----
  if (isMobile) {
    return (
      <Sheet open={mobileOpen} onOpenChange={onMobileOpenChange}>
        <SheetContent
          side="start"
          // Sheet paper = solidPanelSx (theme). Tight flex column fills height.
          className="flex w-[85vw] max-w-[20rem] flex-col gap-0 p-0 pt-[var(--safe-top)] pb-[var(--safe-bottom)]"
        >
          {/* Visually-hidden title keeps the dialog labelled for SR users. */}
          <SheetTitle className="sr-only">{t('chatRail.conversations')}</SheetTitle>
          <RailBody onNavClick={() => onMobileOpenChange?.(false)} />
        </SheetContent>
      </Sheet>
    )
  }

  // ---- Desktop: collapsed → nothing inline (ChatPage shows the reopener). ----
  if (collapsed) return null

  // ---- Desktop: inline FLAT surf2 column with an inline-end hairline. ----
  // Consistent UI System: the rail is a surf2 surface (glass is reserved for
  // the top bar + overlays). No own header band: the open/collapse toggle lives
  // in the global top bar (ChatPage's headerRailToggle), so the rail goes
  // straight to New-chat + list.
  return (
    <aside
      aria-label={t('chatRail.conversations')}
      className="relative flex w-72 min-w-0 flex-col border-e border-border bg-background-secondary"
    >
      <RailBody />
    </aside>
  )
}

export default memo(ChatRail)

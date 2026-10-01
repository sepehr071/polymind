import {
  Sliders,
  LayoutGrid,
  Image,
  GitBranch,
  BookMarked,
  Scale,
  Bot,
  Mic,
  BarChart3,
  Receipt,
  Presentation,
  MessageSquare,
  Sparkles,
  ScanText,
  Mail,
  FileUser,
  Telescope,
  FileSearch,
  ClipboardList,
  ShoppingCart,
} from 'lucide-react'

// SINGLE source of truth for the static feature surfaces in the sidebar (and
// any future nav renderer). Items carry i18n KEYS (resolved via t('layout',
// ...)), NOT raw literals, so every renderer stays byte-identical and localized.
// `feature` (when present) gates the item through hasFeature(user, feature) —
// the consumers MUST apply the same filter so a disabled surface is never shown.
//
// Verb-zones ordered by frequency of use:
//   work    — things you DO daily (arena, debate)
//   studio  — generative production surfaces (image, workflow, automate, meetings)
//   library — things you LOOK UP (saved personas + knowledge; pinned teams append)
// Chat history is NOT a nav zone: the sidebar body renders an always-visible
// conversation list (ConversationListSection) directly below the New-chat
// button (ChatGPT-style), so the old `/chat` nav item is redundant. The full
// archive still lives at /chat-history, reached from that list's footer rather
// than the nav. `/helper` deliberately lives in the UserMenu footer, not nav.
// Each zone carries a `tone` (see components/ui/icon-tile.jsx) — one hue per
// zone for icon wayfinding: work=sky (brand), studio=amber (creative),
// library=emerald (knowledge). Consumers render icons inside an <IconTile>.
export const NAV_SECTIONS = [
  {
    id: 'work',
    labelKey: 'sidebar.work',
    tone: 'sky',
    items: [
      { to: '/agent',  icon: Sparkles,      labelKey: 'sidebar.agent',  feature: 'agent',   descKey: 'hub.toolDesc.agent' },
      { to: '/chat',   icon: MessageSquare, labelKey: 'sidebar.chat',                       descKey: 'hub.toolDesc.chat' },
      { to: '/arena',  icon: LayoutGrid,    labelKey: 'sidebar.arena',  feature: 'arena',   descKey: 'hub.toolDesc.arena' },
      { to: '/debate', icon: Scale,         labelKey: 'sidebar.debate', feature: 'debate',  descKey: 'hub.toolDesc.debate' },
    ],
  },
  {
    id: 'studio',
    labelKey: 'sidebar.studio',
    tone: 'amber',
    items: [
      { to: '/image-studio',   icon: Image,         labelKey: 'sidebar.imageStudio',   feature: 'image_studio',  descKey: 'hub.toolDesc.imageStudio' },
      { to: '/data-analyzer',  icon: BarChart3,     labelKey: 'sidebar.dataAnalyzer',  feature: 'data_analyzer', descKey: 'hub.toolDesc.dataAnalyzer' },
      { to: '/payroll',        icon: Receipt,       labelKey: 'sidebar.payroll',       feature: 'payroll',       descKey: 'hub.toolDesc.payroll' },
      { to: '/presentations',  icon: Presentation,  labelKey: 'sidebar.presentations', feature: 'presentations', descKey: 'hub.toolDesc.presentations' },
      { to: '/ocr',            icon: ScanText,      labelKey: 'sidebar.ocr',           feature: 'ocr_assistant', descKey: 'hub.toolDesc.ocr' },
      { to: '/email-writer',   icon: Mail,          labelKey: 'sidebar.emailWriter',   feature: 'email_writer',  descKey: 'hub.toolDesc.emailWriter' },
      { to: '/cv-checker',     icon: FileUser,      labelKey: 'sidebar.cvChecker',     feature: 'cv_checker',    descKey: 'hub.toolDesc.cvChecker' },
      { to: '/research',       icon: Telescope,     labelKey: 'sidebar.research',      feature: 'research_assistant', descKey: 'hub.toolDesc.research' },
      { to: '/contracts',      icon: FileSearch,    labelKey: 'sidebar.contracts',     feature: 'contract_reviewer', descKey: 'hub.toolDesc.contracts' },
      { to: '/tenders',        icon: ClipboardList, labelKey: 'sidebar.tenders',       feature: 'tender_assistant', descKey: 'hub.toolDesc.tenders' },
      { to: '/shop',           icon: ShoppingCart,  labelKey: 'sidebar.shop',          feature: 'shop_assistant', descKey: 'hub.toolDesc.shop' },
      { to: '/workflow',       icon: GitBranch,     labelKey: 'sidebar.workflow',      feature: 'workflow',      descKey: 'hub.toolDesc.workflow' },
      { to: '/automate-agent', icon: Bot,           labelKey: 'sidebar.automateAgent', feature: 'automate_agent', descKey: 'hub.toolDesc.automateAgent' },
      { to: '/meetings',       icon: Mic,           labelKey: 'sidebar.meetings',      feature: 'meetings',       descKey: 'hub.toolDesc.meetings' },
    ],
  },
  {
    id: 'library',
    labelKey: 'sidebar.library',
    tone: 'emerald',
    items: [
      { to: '/configs',   icon: Sliders,    labelKey: 'sidebar.aiPersonas',                          descKey: 'hub.toolDesc.aiPersonas' },
      { to: '/knowledge', icon: BookMarked, labelKey: 'sidebar.knowledgeVault', feature: 'knowledge', descKey: 'hub.toolDesc.knowledgeVault' },
    ],
  },
]

// Flat list of every nav item (tone inherited from its zone) — feeds
// getToneForPath below.
export const ALL_NAV_ITEMS = [
  ...NAV_SECTIONS.flatMap((s) => s.items.map((i) => ({ ...i, tone: s.tone }))),
]

// Zone tone for an arbitrary pathname (longest matching item route wins, so
// `/workflow/runs` resolves through `/workflow`). Returns null when the path
// belongs to no nav zone — callers pick their own fallback (PageHeader uses
// `accent`).
export function getToneForPath(pathname) {
  if (!pathname) return null
  let best = null
  for (const item of ALL_NAV_ITEMS) {
    if (pathname === item.to || pathname.startsWith(`${item.to}/`)) {
      if (!best || item.to.length > best.to.length) best = item
    }
  }
  return best?.tone ?? null
}

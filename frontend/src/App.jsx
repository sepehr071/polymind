import { Suspense } from 'react'
import { Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import { WorkspaceProvider } from './context/WorkspaceContext'
import { useWorkspace } from './context/WorkspaceContext'
import { ProjectProvider } from './context/ProjectContext'
import ErrorBoundary from './components/common/ErrorBoundary'
import lazyWithRetry from './utils/lazyWithRetry'
import { getRouteSectionKey } from './utils/routeSection'

// Survives stale Vite chunk hashes after redeploy: catches ChunkLoadError /
// "Failed to fetch dynamically imported module" and force-reloads once before
// surfacing the error.
const lazy = lazyWithRetry

// Layouts
import AppShell from './components/layout/AppShell'
import AuthLayout from './components/layout/AuthLayout'

// Auth Pages (not lazy - critical path)
import LoginPage from './pages/auth/LoginPage'
import OperatorLoginPage from './pages/auth/OperatorLoginPage'

// Lazy loaded pages for performance
const ChatPage = lazy(() => import('./pages/chat/ChatPage'))
const DataAnalyzerPage = lazy(() => import('./pages/data-analyzer/DataAnalyzerPage'))
const PayrollPage = lazy(() => import('./pages/payroll/PayrollPage'))
const PresentationsPage = lazy(() => import('./pages/presentations/PresentationsPage'))
const OcrPage = lazy(() => import('./pages/ocr/OcrPage'))
const EmailWriterPage = lazy(() => import('./pages/email-writer/EmailWriterPage'))
const CvCheckerPage = lazy(() => import('./pages/cv-checker/CvCheckerPage'))
const ResearchPage = lazy(() => import('./pages/research/ResearchPage'))
const ContractsPage = lazy(() => import('./pages/contracts/ContractsPage'))
const TendersPage = lazy(() => import('./pages/tenders/TendersPage'))
const ShopPage = lazy(() => import('./pages/shop/ShopPage'))
const AgentPage = lazy(() => import('./pages/agent/AgentPage'))
const DashboardPage = lazy(() => import('./pages/dashboard/DashboardPage'))
const HistoryPage = lazy(() => import('./pages/dashboard/HistoryPage'))
const ConfigsPage = lazy(() => import('./pages/dashboard/ConfigsPage'))
const SettingsPage = lazy(() => import('./pages/dashboard/settings/SettingsPage'))
const ImageStudioPage = lazy(() => import('./pages/dashboard/ImageStudioPage'))
const GalleryPage = lazy(() => import('./pages/gallery/GalleryPage'))
const ArenaPage = lazy(() => import('./pages/arena/ArenaPage'))
const WorkflowPage = lazy(() => import('./pages/workflow/WorkflowPage'))
const AdminLayout = lazy(() => import('./pages/admin/AdminLayout'))
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard'))
const UserManagement = lazy(() => import('./pages/admin/UserManagement'))
const UserHistoryPage = lazy(() => import('./pages/admin/UserHistoryPage'))
const TemplatesPage = lazy(() => import('./pages/admin/TemplatesPage'))
const AuditLogPage = lazy(() => import('./pages/admin/AuditLogPage'))
const CompaniesPage = lazy(() => import('./pages/admin/CompaniesPage'))
const CompanyDetailPage = lazy(() => import('./pages/admin/CompanyDetailPage'))
const TeamDetailPage = lazy(() => import('./pages/admin/TeamDetailPage'))
const UserDetailPage = lazy(() => import('./pages/admin/UserDetailPage'))
const DLPDashboardPage = lazy(() => import('./pages/admin/DLPDashboardPage'))
const AdminFeatureFlagsPage = lazy(() => import('./pages/admin/FeatureFlagsPage'))
const AdminHoldingPage = lazy(() => import('./pages/admin/HoldingPage'))
const AdminProfitPage = lazy(() => import('./pages/admin/ProfitPage'))
const AdminPricingPage = lazy(() => import('./pages/admin/PricingSettingsPage'))

const KnowledgePage = lazy(() => import('./pages/knowledge/KnowledgePage'))
const ProjectsPage = lazy(() => import('./pages/projects/ProjectsPage'))
const DebatePage = lazy(() => import('./pages/debate/DebatePage'))
// LandingPage is kept on disk but no longer routed — the app launches from a
// parent hub straight into KC login, so there is no public marketing landing.
const AutomateAgentPage = lazy(() => import('./pages/automate-agent/AutomateAgentPage'))
const MeetingsPage = lazy(() => import('./pages/meetings/MeetingsPage'))
const MeetingDetailPage = lazy(() => import('./pages/meetings/MeetingDetailPage'))
const SeriesPage = lazy(() => import('./pages/meeting-series/SeriesPage'))
const HelperPage = lazy(() => import('./pages/helper/HelperPage'))
const AssistantsHubPage = lazy(() => import('./pages/assistants/AssistantsHubPage'))
const AcceptInvitePage = lazy(() => import('./pages/auth/AcceptInvitePage'))
const KeycloakCallbackPage = lazy(() => import('./pages/auth/KeycloakCallbackPage'))
const ProjectSettingsPage = lazy(() => import('./pages/projects/ProjectSettingsPage'))
const WorkspaceSettingsPage = lazy(() => import('./pages/workspaces/WorkspaceSettingsPage'))
const WorkspaceOverviewPage = lazy(() => import('./pages/workspaces/WorkspaceOverviewPage'))
const CreateWorkspacePage = lazy(() => import('./pages/workspaces/CreateWorkspacePage'))
const OnboardingWizard = lazy(() => import('./components/onboarding/OnboardingWizard'))
const PromptTemplatesPage = lazy(() => import('./pages/admin/PromptTemplatesPage'))
const FeatureDisabledPage = lazy(() => import('./pages/common/FeatureDisabledPage'))
const NotFoundPage = lazy(() => import('./pages/common/NotFoundPage'))
const SharedChatPage = lazy(() => import('./pages/share/SharedChatPage'))

// Single source of truth for the loading visual. `fullScreen` is for guards
// (auth/workspace bootstrap) that own the entire viewport; bare `LoadingSpinner`
// is used as a Suspense fallback inside MainLayout's content slot.
// Same spinner shape in both modes → the transition from guard → in-content
// fallback looks continuous (no double-flash).
function LoadingSpinner({ fullScreen = false }) {
  const wrapper = fullScreen
    ? 'flex h-app-dvh items-center justify-center bg-background'
    : 'flex h-full items-center justify-center'
  return (
    <div className={wrapper}>
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
    </div>
  )
}

// Legacy `/platform/*` → `/admin/*` redirect. The platform-operator dashboard
// was folded into the super-admin `/admin` shell, so old deep links/bookmarks
// map to their admin equivalent. The generic `/platform`→`/admin` path rewrite
// covers most routes (holding, companies/:wid, features); two pages don't have a
// 1:1 admin path and are special-cased: `users-overview` → `/admin/users`, and
// `/platform/account` (operator profile, no admin twin) → `/admin`.
function PlatformRedirect() {
  const loc = useLocation()
  let target
  if (loc.pathname.includes('users-overview')) {
    target = '/admin/users'
  } else if (loc.pathname.startsWith('/platform/account')) {
    target = '/admin'
  } else {
    target = loc.pathname.replace(/^\/platform/, '/admin')
  }
  return <Navigate to={target + loc.search} replace />
}

function ProtectedRoute({ children, adminOnly = false, managerOrAdmin = false }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) return <LoadingSpinner fullScreen />

  // Capture the attempted path (incl. query) so the user lands back where they
  // were headed after auth, instead of always dumping them on /dashboard. The query
  // param is consumed post-login by PublicRoute (operator email/password). The
  // SSO flow loses the query string across the KC round-trip (redirect URI is a
  // fixed /login/callback), so we ALSO stash it in sessionStorage for the
  // KeycloakCallbackPage to consume (that page is owned by another cluster —
  // see needsOtherCluster).
  if (!user) {
    const from = location.pathname + location.search
    if (from && from.startsWith('/') && !from.startsWith('//') && from !== '/dashboard') {
      try { sessionStorage.setItem('auth_redirect', from) } catch { /* quota/privacy — non-fatal */ }
      return <Navigate to={`/login?redirect=${encodeURIComponent(from)}`} replace />
    }
    return <Navigate to="/login" replace />
  }
  if (adminOnly && user.role !== 'admin') return <Navigate to="/dashboard" replace />
  if (managerOrAdmin && user.role !== 'admin' && user.role !== 'manager') return <Navigate to="/dashboard" replace />
  return children
}

// Disabled-feature flag → friendly page (kept inside MainLayout so the nav
// stays put) instead of a silent <Navigate to="/chat"> that left users
// wondering where the link went.
function FeatureGate({ feature, children }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return null
  if (!user?.features?.[feature]) {
    return (
      <Suspense fallback={<LoadingSpinner />}>
        <FeatureDisabledPage />
      </Suspense>
    )
  }
  return children
}

function PublicRoute({ children }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) return <LoadingSpinner fullScreen />
  if (user) {
    // Honor a `?redirect=` deep link captured pre-login (ProtectedRoute), but
    // only for in-app same-origin paths — never an absolute/protocol-relative
    // URL (open-redirect guard).
    const params = new URLSearchParams(location.search)
    const redirect = params.get('redirect')
    const safeRedirect =
      redirect && redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : null
    const fallback = '/dashboard'
    return <Navigate to={safeRedirect || fallback} replace />
  }
  return children
}

// Root entry — there is NO public landing page. The app launches from a parent
// hub straight into auth: unauthenticated visitors go to the KC login, authed
// users land on the dashboard hub. (LandingPage is kept on disk, just unrouted.)
function RootRedirect() {
  const { user, isLoading } = useAuth()
  if (isLoading) return <LoadingSpinner fullScreen />
  return <Navigate to={user ? '/dashboard' : '/login'} replace />
}

// '/invite/<token>' bypass is handled below via a startsWith() check (it's a
// param route, not a literal path), so it intentionally isn't in this set.
const ONBOARDING_BYPASS_PATHS = new Set(['/onboarding', '/login', '/login/operator', '/login/callback'])

function OnboardingGate() {
  const { user } = useAuth()
  const { workspaces, currentWorkspace, initialized } = useWorkspace()
  const location = useLocation()

  // Block child route mount until workspace bootstrap finishes. Previously
  // children rendered (and their lazy chunks started fetching) during init,
  // then a `<Navigate to="/onboarding">` could fire — cascading remounts +
  // visible flash. `initialized` flips true exactly once per session, so
  // this only gates the very first nav after login.
  if (!initialized) return <LoadingSpinner fullScreen />

  const isManagerOrAdmin = user?.role === 'admin' || user?.role === 'manager'
  const hasTeamWorkspace =
    workspaces.some((w) => w.type === 'team') ||
    currentWorkspace?.type === 'team'
  // Backend stamp (settings.onboarding_seen_at, written when the wizard is
  // first SHOWN) is authoritative — survives browser/device changes. The
  // legacy localStorage key stays as an offline/pre-migration fallback.
  const dismissed =
    Boolean(user?.settings?.onboarding_seen_at) ||
    (user?.id
      ? localStorage.getItem(`onboarding_complete:${user.id}`) === '1'
      : false)
  const bypassPath =
    ONBOARDING_BYPASS_PATHS.has(location.pathname) ||
    location.pathname.startsWith('/invite/')

  if (isManagerOrAdmin && !hasTeamWorkspace && !dismissed && !bypassPath) {
    return <Navigate to="/onboarding" replace />
  }

  return <Outlet />
}

export default function App() {
  const location = useLocation()
  return (
    <WorkspaceProvider>
      <ProjectProvider>
          {/* Single top-level boundary covers every lazy route (incl. those
              without their own inner boundary). Keyed on the route SECTION (not
              full pathname) so it remounts clean on cross-section navigation —
              navigating away from a chunk that threw (lazyWithRetry 2nd failure)
              clears the error automatically instead of stranding a blank screen.
              Section keying (vs full pathname) avoids remounting the subtree on
              param-only nav like /chat → /chat/<id> (would disrupt live streams);
              distinct lazy chunks live under distinct sections, so chunk recovery
              is preserved. Must match PageTransition's key exactly. */}
          <ErrorBoundary key={getRouteSectionKey(location.pathname)}>
          <Routes>
            {/* Public Routes */}
            <Route element={<AuthLayout />}>
              <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
              <Route path="/login/callback" element={<PublicRoute><Suspense fallback={<LoadingSpinner />}><KeycloakCallbackPage /></Suspense></PublicRoute>} />
              <Route path="/login/operator" element={<PublicRoute><OperatorLoginPage /></PublicRoute>} />
            </Route>

            {/* Onboarding — full-page, no MainLayout */}
            <Route
              path="/onboarding"
              element={
                <ProtectedRoute managerOrAdmin>
                  <Suspense fallback={<LoadingSpinner />}><OnboardingWizard /></Suspense>
                </ProtectedRoute>
              }
            />

            {/* Protected Routes — with OnboardingGate */}
            <Route element={<ProtectedRoute><OnboardingGate /></ProtectedRoute>}>
              <Route element={<AppShell />}>
                <Route path="/chat/:conversationId?" element={<ErrorBoundary><Suspense fallback={<LoadingSpinner />}><ChatPage /></Suspense></ErrorBoundary>} />
                {/* Single optional-param route (like /chat) so the post-create
                    /data-analyzer → /data-analyzer/<id> promotion is param-only
                    and never remounts the page (which would kill the first-send
                    stream). Route section key = '/data-analyzer' (first segment),
                    distinct from '/chat'. */}
                <Route path="/data-analyzer/:conversationId?" element={<FeatureGate feature="data_analyzer"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><DataAnalyzerPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/payroll" element={<FeatureGate feature="payroll"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><PayrollPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/presentations" element={<FeatureGate feature="presentations"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><PresentationsPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/ocr" element={<FeatureGate feature="ocr_assistant"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><OcrPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/email-writer" element={<FeatureGate feature="email_writer"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><EmailWriterPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/cv-checker" element={<FeatureGate feature="cv_checker"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><CvCheckerPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/research" element={<FeatureGate feature="research_assistant"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><ResearchPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/contracts" element={<FeatureGate feature="contract_reviewer"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><ContractsPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/tenders" element={<FeatureGate feature="tender_assistant"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><TendersPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/shop" element={<FeatureGate feature="shop_assistant"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><ShopPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/agent/:conversationId?" element={<FeatureGate feature="agent"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><AgentPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/helper" element={<ErrorBoundary><Suspense fallback={<LoadingSpinner />}><HelperPage /></Suspense></ErrorBoundary>} />
                <Route path="/assistants" element={<Suspense fallback={<LoadingSpinner />}><AssistantsHubPage /></Suspense>} />
                <Route path="/dashboard" element={<ErrorBoundary><Suspense fallback={<LoadingSpinner />}><DashboardPage /></Suspense></ErrorBoundary>} />
                <Route path="/chat-history" element={<Suspense fallback={<LoadingSpinner />}><HistoryPage /></Suspense>} />
                <Route path="/gallery" element={<FeatureGate feature="image_studio"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><GalleryPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/image-history" element={<Navigate to="/gallery" replace />} />
                <Route path="/history" element={<Navigate to="/chat-history" replace />} />
                <Route path="/configs" element={<Suspense fallback={<LoadingSpinner />}><ConfigsPage /></Suspense>} />
                <Route path="/settings" element={<Suspense fallback={<LoadingSpinner />}><SettingsPage /></Suspense>} />
                <Route path="/image-studio" element={<FeatureGate feature="image_studio"><Suspense fallback={<LoadingSpinner />}><ImageStudioPage /></Suspense></FeatureGate>} />
                <Route path="/arena" element={<FeatureGate feature="arena"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><ArenaPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/workflow" element={<FeatureGate feature="workflow"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><WorkflowPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/knowledge" element={<FeatureGate feature="knowledge"><Suspense fallback={<LoadingSpinner />}><KnowledgePage /></Suspense></FeatureGate>} />
                <Route path="/projects" element={<Suspense fallback={<LoadingSpinner />}><ProjectsPage /></Suspense>} />
                <Route path="/workspaces/new" element={<ProtectedRoute managerOrAdmin><Suspense fallback={<LoadingSpinner />}><CreateWorkspacePage /></Suspense></ProtectedRoute>} />
                <Route path="/workspaces/:wid/settings" element={<Suspense fallback={<LoadingSpinner />}><WorkspaceSettingsPage /></Suspense>} />
                <Route path="/workspaces/:wid" element={<Suspense fallback={<LoadingSpinner />}><WorkspaceOverviewPage /></Suspense>} />
                <Route path="/debate" element={<FeatureGate feature="debate"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><DebatePage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/automate-agent" element={<FeatureGate feature="automate_agent"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><AutomateAgentPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/projects/:pid/settings" element={<Suspense fallback={<LoadingSpinner />}><ProjectSettingsPage /></Suspense>} />
                <Route path="/meetings" element={<FeatureGate feature="meetings"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><MeetingsPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/meetings/:id" element={<FeatureGate feature="meetings"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><MeetingDetailPage /></Suspense></ErrorBoundary></FeatureGate>} />
                <Route path="/meeting-series" element={<FeatureGate feature="meetings"><ErrorBoundary><Suspense fallback={<LoadingSpinner />}><SeriesPage /></Suspense></ErrorBoundary></FeatureGate>} />
              </Route>
            </Route>

            {/* Admin Routes — adminOnly guard stays ABOVE AdminLayout, which
                provides the persistent /admin/* sub-nav (replaces MainLayout
                here so admin pages get their own consolidated shell). */}
            <Route element={<ProtectedRoute adminOnly><Suspense fallback={<LoadingSpinner fullScreen />}><AdminLayout /></Suspense></ProtectedRoute>}>
              <Route path="/admin" element={<Suspense fallback={<LoadingSpinner />}><AdminDashboard /></Suspense>} />
              {/* /admin/analytics merged into /admin/holding — keep old bookmarks alive. */}
              <Route path="/admin/analytics" element={<Navigate replace to="/admin/holding" />} />
              <Route path="/admin/users" element={<Suspense fallback={<LoadingSpinner />}><UserManagement /></Suspense>} />
              <Route path="/admin/users/:userId/history" element={<Suspense fallback={<LoadingSpinner />}><UserHistoryPage /></Suspense>} />
              <Route path="/admin/templates" element={<Suspense fallback={<LoadingSpinner />}><TemplatesPage /></Suspense>} />
              <Route path="/admin/prompt-templates" element={<Suspense fallback={<LoadingSpinner />}><PromptTemplatesPage /></Suspense>} />
              <Route path="/admin/audit" element={<Suspense fallback={<LoadingSpinner />}><AuditLogPage /></Suspense>} />
              <Route path="/admin/companies" element={<Suspense fallback={<LoadingSpinner />}><CompaniesPage /></Suspense>} />
              <Route path="/admin/companies/:wid" element={<Suspense fallback={<LoadingSpinner />}><CompanyDetailPage /></Suspense>} />
              <Route path="/admin/companies/:wid/teams/:pid" element={<Suspense fallback={<LoadingSpinner />}><TeamDetailPage /></Suspense>} />
              <Route path="/admin/companies/:wid/teams/:pid/users/:uid" element={<Suspense fallback={<LoadingSpinner />}><UserDetailPage /></Suspense>} />
              <Route path="/admin/dlp" element={<Suspense fallback={<LoadingSpinner />}><DLPDashboardPage /></Suspense>} />
              <Route path="/admin/features" element={<Suspense fallback={<LoadingSpinner />}><AdminFeatureFlagsPage /></Suspense>} />
              <Route path="/admin/holding" element={<Suspense fallback={<LoadingSpinner />}><AdminHoldingPage /></Suspense>} />
              <Route path="/admin/profit" element={<Suspense fallback={<LoadingSpinner />}><AdminProfitPage /></Suspense>} />
              <Route path="/admin/pricing" element={<Suspense fallback={<LoadingSpinner />}><AdminPricingPage /></Suspense>} />
            </Route>

            {/* Legacy /platform/* → /admin/* redirects (single catch-all). The
                platform-operator dashboard was merged into the super-admin
                /admin shell; old bookmarks land on the admin equivalent.
                PlatformRedirect rewrites the path (with the two special cases:
                users-overview→users, account→admin). Reachable WITHOUT the admin
                guard so an old bookmark routes through; the destination /admin/*
                route then applies its own adminOnly guard. */}
            <Route path="/platform/*" element={<PlatformRedirect />} />

            {/* Workspace invite acceptance (auth-aware, redirects internally) */}
            <Route path="/invite/:token" element={<Suspense fallback={<LoadingSpinner />}><AcceptInvitePage /></Suspense>} />

            {/* Shared chat snapshot — any logged-in user; own minimal read-only
                shell (NOT MainLayout). Unauth → /login?redirect=/share/<token>. */}
            <Route path="/share/:token" element={<ProtectedRoute><Suspense fallback={<LoadingSpinner />}><SharedChatPage /></Suspense></ProtectedRoute>} />

            {/* Root — no landing page; redirect to login (guests) or hub (authed). */}
            <Route path="/" element={<RootRedirect />} />

            {/* Catch-all — real 404 (preserves the typed URL) instead of a
                silent bounce to /chat that hid dead links + typos. */}
            <Route path="*" element={<Suspense fallback={<LoadingSpinner fullScreen />}><NotFoundPage /></Suspense>} />
          </Routes>
          </ErrorBoundary>
      </ProjectProvider>
    </WorkspaceProvider>
  )
}

import AuroraBackground from '@/components/dashboard/AuroraBackground'
import GreetingHero from '@/components/dashboard/GreetingHero'
import QuickChatComposer from '@/components/dashboard/QuickChatComposer'
import ToolLauncher from '@/components/dashboard/ToolLauncher'
import WorkspaceInvitesPanel from './components/WorkspaceInvitesPanel'

/** Post-login home. Route stays /dashboard. */
export default function DashboardPage() {
  return (
    <div className="relative isolate h-full overflow-hidden">
      <AuroraBackground />
      <div className="relative z-10 h-full overflow-y-auto">
        <div className="mx-auto max-w-6xl px-4 pb-24 pt-10 sm:pt-14">
          <GreetingHero banner={<WorkspaceInvitesPanel />} />
          <QuickChatComposer className="mt-7" />
          <ToolLauncher />
        </div>
      </div>
    </div>
  )
}

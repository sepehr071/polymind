import { Outlet } from 'react-router-dom'
import { Check } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import PolymindLogo from '@/components/brand/PolymindLogo'

export default function AuthLayout() {
  const { t } = useTranslation('layout')

  return (
    <div className="relative min-h-app-dvh bg-background flex overflow-hidden">
      {/* Ambient gradient wash so the frosted auth card reads as glass over
          the backdrop. Pointer-events-none, sits behind everything. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-0"
        style={{
          background:
            'radial-gradient(120% 80% at 15% 0%, hsl(var(--accent) / 0.18), transparent 55%),' +
            'radial-gradient(100% 90% at 100% 100%, hsl(var(--accent) / 0.12), transparent 50%),' +
            'linear-gradient(160deg, hsl(var(--background-secondary)) 0%, hsl(var(--background)) 60%)',
        }}
      />

      {/* Start side - Branding */}
      <div className="relative z-10 hidden lg:flex lg:w-1/2 items-center justify-center p-12">
        <div className="max-w-md space-y-6">
          <h1 className="sr-only">Polymind AI</h1>
          <PolymindLogo
            size={48}
            showWordmark
            wordmarkClassName="text-3xl"
          />
          <p className="text-xl text-foreground-secondary leading-relaxed">
            {t('authLayout.tagline')}
          </p>
          <div className="space-y-4 pt-4">
            <Feature
              title={t('authLayout.customAgentsTitle')}
              description={t('authLayout.customAgentsDesc')}
            />
            <Feature
              title={t('authLayout.multipleModelsTitle')}
              description={t('authLayout.multipleModelsDesc')}
            />
          </div>
        </div>
      </div>

      {/* End side - Auth forms */}
      <div className="relative z-10 flex-1 flex items-start sm:items-center justify-center overflow-y-auto p-6">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center justify-center mb-8">
            <PolymindLogo size={40} showWordmark wordmarkClassName="text-2xl" />
          </div>
          <Outlet />
        </div>
      </div>
    </div>
  )
}

function Feature({ title, description }) {
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-accent/10">
        <Check className="h-3 w-3 text-accent" />
      </div>
      <div>
        <h3 className="font-medium text-foreground">{title}</h3>
        <p className="text-sm text-foreground-secondary">{description}</p>
      </div>
    </div>
  )
}

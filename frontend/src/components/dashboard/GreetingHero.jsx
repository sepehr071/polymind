import { useTranslation } from 'react-i18next'
import { useAuth } from '@/context/AuthContext'
import PolymindLogo from '@/components/brand/PolymindLogo'

function greetingKeyForHour(hour) {
  if (hour >= 5 && hour <= 11) return 'morning'
  if (hour >= 12 && hour <= 16) return 'noon'
  if (hour >= 17 && hour <= 20) return 'afternoon'
  return 'night'
}

/** Centered home mark. Logo stays Latin. Greeting follows the UI language. */
export default function GreetingHero({ banner }) {
  const { t } = useTranslation('dashboard')
  const { user } = useAuth()
  const name = user?.profile?.display_name || user?.email?.split('@')[0] || ''
  const greeting = t(`hub.greeting.${greetingKeyForHour(new Date().getHours())}`)

  return (
    <header className="flex flex-col items-center text-center">
      <PolymindLogo
        size={56}
        showWordmark
        wordmarkClassName="text-4xl font-extrabold tracking-tight sm:text-5xl"
      />
      <p className="mt-4 max-w-xl text-sm text-foreground-secondary">
        {name ? (
          <>
            {greeting}
            {t('hub.greeting.separator')}
            <span className="font-semibold text-foreground">{name}</span>
            {'. '}
          </>
        ) : (
          <>{greeting}. </>
        )}
        {t('hub.homePrompt')}
      </p>
      {banner ? <div className="mt-4 w-full max-w-3xl text-start">{banner}</div> : null}
    </header>
  )
}

import { DirectionProvider } from '@radix-ui/react-direction'
import { useLanguage } from '@/context/LanguageContext'

/**
 * Bridges the app's active language to Radix UI's DirectionProvider so every
 * Radix primitive (Select, Dropdown, Slider, Switch, etc.) mirrors correctly
 * in Persian (RTL). Mounted once in main.jsx above all Radix consumers.
 * Consumers need do nothing — direction flows via Radix context.
 */
export default function AppDirectionProvider({ children }) {
  const { dir } = useLanguage()
  return <DirectionProvider dir={dir === 'rtl' ? 'rtl' : 'ltr'}>{children}</DirectionProvider>
}

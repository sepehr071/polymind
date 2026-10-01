import { User, Palette, DollarSign, Brain } from 'lucide-react'
import ProfileSection from './ProfileSection'
import PreferencesSection from './PreferencesSection'
import AIPreferencesSection from './AIPreferencesSection'
import UsageSection from './UsageSection'

// Single source of truth for the settings section catalogue. Consumed by both
// the standalone /settings page (hash-routed) and the ChatGPT-style settings
// modal (SettingsDialog) so the two surfaces stay in lock-step.
export const SECTIONS = [
  { id: 'profile', icon: User, tKey: 'tabs.profile', Component: ProfileSection },
  { id: 'preferences', icon: Palette, tKey: 'tabs.preferences', Component: PreferencesSection },
  { id: 'ai', icon: Brain, tKey: 'tabs.ai', Component: AIPreferencesSection },
  { id: 'usage', icon: DollarSign, tKey: 'tabs.usage', Component: UsageSection },
]

export const DEFAULT_SECTION = 'profile'

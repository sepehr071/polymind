import { useTranslation } from 'react-i18next'
import { PenLine, FileText, Lightbulb, Code2 } from 'lucide-react'

/* Empty-state suggestion-chip icons, positional — index must line up with the
   `emptyState.suggestions` array in chat.json (draft · summarize · brainstorm ·
   code). Falls back to the first icon if a chip has no match. */
const SUGGESTION_ICONS = [PenLine, FileText, Lightbulb, Code2]

/* ═══════════════════════════════════════════════════════════════════════
   ChatEmptyState — ChatGPT-minimal centered block for a fresh chat.

   A bare greeting on top, the composer in the `{children}` slot, and a 2-col
   grid of prompt cards below it (no hero tile, no description). The whole thing is centered vertically
   by ChatPage's wrapper; after the first send ChatPage swaps to the normal
   docked layout.

   The 768px max-width matches the message/composer column so the composer sits
   in the same horizontal lane it docks to — alignment invariant, do not change
   without matching the message column.
   ═══════════════════════════════════════════════════════════════════════ */
export default function ChatEmptyState({ selectedConfig, children }) {
  const { t } = useTranslation('chat')

  // Custom persona = a saved config, not one of the prefixed quick models.
  const isCustomPersona = !!(selectedConfig && !selectedConfig.isQuickModel)

  const suggestionsRaw = t('emptyState.suggestions', { returnObjects: true })
  const suggestions = (Array.isArray(suggestionsRaw) ? suggestionsRaw : [])
    .slice(0, 4)
    .map((s, i) => ({
      title: s?.title ?? '',
      prompt: s?.prompt ?? '',
      Icon: SUGGESTION_ICONS[i] ?? SUGGESTION_ICONS[0],
    }))

  // Seed the composer with a card's prompt (the ChatInput listens for this
  // window event) rather than sending immediately — the user refines before
  // hitting Send. Verified parity: fill-not-send. Do NOT change to send.
  const insertPrompt = (prompt) => {
    if (!prompt) return
    window.dispatchEvent(
      new CustomEvent('chat:composer-insert', { detail: { text: prompt } }),
    )
  }

  return (
    <div className="relative w-full max-w-[768px] mx-auto my-auto px-4 flex flex-col gap-6">
      {/* Subtle radial sky glow behind the hero (Consistent UI System). Purely
          decorative — pointer-events-none, no animation (reduce-motion safe). */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-48"
        style={{
          background:
            'radial-gradient(60% 100% at 50% 0%, rgba(14,165,233,0.06), transparent 70%)',
        }}
      />
      {/* Greeting — bare, centered. No hero tile, no description (ChatGPT-minimal). */}
      <div className="flex flex-col items-center gap-3 text-center">
        {/* Greeting is ALWAYS the friendly line — never the model/persona name
            (showing a raw model name here was the bug this fixes). */}
        <h2 className="text-2xl font-extrabold text-foreground">
          {t('emptyState.ready')}
        </h2>

        {/* Persona attribution lives on its own muted sub-line so the greeting
            stays generic while still naming the assistant the user picked. */}
        {isCustomPersona && (
          <p className="text-sm text-foreground-tertiary">
            {t('emptyState.personaIntro', { name: selectedConfig.name })}
          </p>
        )}
      </div>

      {/* Composer slot — ChatPage renders the DLP note + ChatInput here. */}
      {children}

      {/* Prompt cards — fill the composer, do not send. */}
      <div className="grid gap-2 sm:grid-cols-2">
        {suggestions.map((s, i) => (
          <button
            key={i}
            type="button"
            onClick={() => insertPrompt(s.prompt)}
            className="flex w-full items-center gap-2 rounded-2xl border border-border bg-background-secondary px-3 py-2.5 text-start text-sm text-foreground-secondary hover:text-foreground hover:border-accent/40"
          >
            <s.Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
            <span>{s.title}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

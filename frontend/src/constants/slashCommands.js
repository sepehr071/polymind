import { PanelRightOpen } from 'lucide-react'

// `icon` is the resolved lucide component (NOT a name string) so consumers
// render `cmd.icon` directly — this keeps the hot chat chunk free of the
// `import * as icons from 'lucide-react'` namespace barrel that pinned all
// ~1000 icon modules into the bundle. Add the matching named import above when
// introducing a new command.
//
// `label`/`placeholder` fall back to literal English; pass `labelKey`/
// `placeholderKey` (i18n keys) when a command must localize. ChatInput resolves
// the key via the `chat` namespace and uses the literal as the fallback.
export const SLASH_COMMANDS = [
  {
    id: 'canvas',
    label: 'Canvas',
    description: 'Build a runnable HTML/CSS/JS artifact and open it in the canvas',
    icon: PanelRightOpen,
    // NO configId: canvas runs on the USER-SELECTED model from the picker.
    // The backend swaps in the Canvas Coder system prompt when intent='canvas'.
    intent: 'canvas',
    placeholder: 'Describe the app or visual you want to build…',
  },
]

// Data Analyzer picks Sonnet (complex) vs Flash (simple) server-side
// (`data_model_router`). Chip is a static label — not a user picker.
export const DATA_ANALYZER_MODEL_LABEL = 'Auto · Sonnet 5 / Flash Lite'

export function getSlashCommand(id) {
  return SLASH_COMMANDS.find((cmd) => cmd.id === id)
}

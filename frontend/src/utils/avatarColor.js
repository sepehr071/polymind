// Shared initials + per-user hue-tinting for avatars. Single source of truth so
// the chrome Avatar fallback (sidebar user menu, etc.) matches the team-member
// AvatarStack pixel-for-pixel: same getInitials, same `hsl(hue, 40%, 32%)` bg
// with white text.

/**
 * First letters of up to the first two words. Latin letters are uppercased and
 * concatenated (`JD`); Persian letters join with a dot (`م.ا`) so they don't
 * read as a word (`ما`).
 * @param {string} name
 * @returns {string}
 */
export function getInitials(name) {
  if (!name) return '??'
  const letters = name.trim().split(/\s+/).slice(0, 2).map((p) => p[0] || '').filter(Boolean)
  if (!letters.length) return '??'
  if (letters.some((c) => /[\u0600-\u06FF]/.test(c))) return letters.join('.')
  return letters.map((c) => c.toUpperCase()).join('')
}

// djb2-ish string hash reused from WorkspaceSwitcher/WorkspaceHeader so the same
// seed always lands on the same hue across the app. `>>> 0` keeps it a positive
// 32-bit int.
function hashString(seed) {
  let h = 0
  const str = String(seed)
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0
  return h
}

/**
 * Stable bg/fg pair for an initials avatar derived from a seed string.
 * `bg` matches AvatarStack's `hsl(hue, 40%, 32%)`; `fg` is white (also matching
 * AvatarStack's `text-white`) which reads cleanly on that fixed-darkness tone.
 * @param {string} seed
 * @returns {{ bg: string, fg: string }}
 */
export function avatarColors(seed) {
  // Null/empty seed → AvatarStack's neutral fallback hue (220).
  const hue = seed == null || seed === '' ? 220 : hashString(seed) % 360
  return { bg: `hsl(${hue}, 40%, 32%)`, fg: '#ffffff' }
}

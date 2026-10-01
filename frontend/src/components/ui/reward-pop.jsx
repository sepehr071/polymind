import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { create } from 'zustand'

// Reward key → self-hosted 3D asset (MIT Fluent 3D PNGs in /public/icons/3d).
// Add a key here to make `fireReward('<key>')` valid from any flow.
const REWARD_ASSETS = {
  trophy: '/icons/3d/trophy.png', // successful workflow run
  rocket: '/icons/3d/rocket.png', // onboarding / setup complete
}

// Tiny global store so any flow can trigger a reward without prop-drilling.
// `<RewardPop>` is mounted ONCE at app root (next to <Toaster> in main.jsx) so
// the pop survives route changes — e.g. onboarding fires it then immediately
// navigates to /chat; an in-page overlay would unmount mid-animation.
const useRewardStore = create((set) => ({
  reward: null, // { key, id } | null
  fire: (key) => set({ reward: { key, id: `${key}-${Date.now()}` } }),
  clear: () => set({ reward: null }),
}))

/**
 * Imperative trigger — call right next to `celebrate()` (confetti) at a genuine
 * milestone. No-op for unknown keys so a typo can never throw in a happy-path.
 *
 * This lives in the LIGHT wrapper module (no `motion/react` import) so call
 * sites like `useWorkflowState.js` can import `fireReward` without dragging
 * framer-motion into their chunk.
 * @param {keyof typeof REWARD_ASSETS} key
 */
export function fireReward(key) {
  if (REWARD_ASSETS[key]) useRewardStore.getState().fire(key)
}

// The motion-bearing overlay (AnimatePresence + spring) is code-split so
// `motion/react` loads only the first time a reward actually fires — not in the
// entry/app-shell chunk. Plain `lazy` (not lazyWithRetry): this overlay is
// decorative, so a one-off chunk hiccup must NOT trigger a full page reload.
const RewardPopImpl = lazy(() => import('./reward-pop-impl'))

/**
 * App-root reward overlay (light wrapper). Mounts the lazy motion component only
 * after the first `fireReward(...)` of the session, so the framer-motion chunk
 * downloads on demand at a rare milestone rather than at startup. Once loaded it
 * stays mounted so subsequent rewards animate without a re-fetch.
 */
export default function RewardPop({ duration = 1700 }) {
  const reward = useRewardStore((s) => s.reward)
  const clear = useRewardStore((s) => s.clear)
  // Latch: once any reward has fired we keep the lazy impl mounted (it owns the
  // exit animation, so it must outlive `reward` going back to null).
  const [armed, setArmed] = useState(false)
  const armedRef = useRef(false)

  useEffect(() => {
    if (reward && !armedRef.current) {
      armedRef.current = true
      setArmed(true)
    }
  }, [reward])

  if (!armed) return null

  const src = reward ? REWARD_ASSETS[reward.key] : null

  return (
    <Suspense fallback={null}>
      <RewardPopImpl reward={reward} src={src} duration={duration} clear={clear} />
    </Suspense>
  )
}

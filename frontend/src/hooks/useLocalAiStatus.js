import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'

/**
 * Whether the free local (Ollama) model is configured/reachable on the backend.
 * Drives the "Local AI" tag on studio assistants (email writer). Long stale —
 * this is infra-level and rarely changes; failures resolve to `false` (no tag).
 */
export function useLocalAiStatus() {
  const q = useQuery({
    queryKey: ['localAiStatus'],
    queryFn: async () => {
      const { data } = await api.get('/models/local-status')
      return !!data?.available
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
  return { available: q.data === true, isLoading: q.isLoading }
}

export default useLocalAiStatus

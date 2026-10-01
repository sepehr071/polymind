import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { modelCatalogService } from '../services/modelCatalogService'
import { QUICK_MODEL_IDS, _FALLBACK_QUICK_MODELS } from '../constants/models'
import {
  _FALLBACK_IMAGE_GEN_MODELS,
  _FALLBACK_AI_AGENT_MODELS,
  _FALLBACK_TTS_MODELS,
  _FALLBACK_VIDEO_GEN_MODELS,
} from '../constants/workflowModels'

export function useModelCatalog() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => modelCatalogService.fetchCatalog({ pageSize: 500 }),
    staleTime: 60 * 60 * 1000, // 1h
    refetchOnWindowFocus: false,
    // Do not throw on error — fall back to static constants
    throwOnError: false,
  })

  const models = data?.data || []
  const isEmpty = models.length === 0

  return useMemo(() => {
    const byId = new Map(models.map(m => [m._id, m]))
    const isImageOut = m => m.architecture?.output_modalities?.includes('image')
    const isVisionIn = m => m.architecture?.input_modalities?.includes('image')
    const isAudioOut = m => m.architecture?.output_modalities?.includes('audio')

    const quickModels = isEmpty
      ? _FALLBACK_QUICK_MODELS
      : QUICK_MODEL_IDS
          .map(id => byId.get(id) || _FALLBACK_QUICK_MODELS.find(f => f.id === id))
          .filter(Boolean)

    const imageGenModels = isEmpty ? _FALLBACK_IMAGE_GEN_MODELS : models.filter(isImageOut)
    const visionModels = isEmpty ? [] : models.filter(isVisionIn)
    const ttsModels = isEmpty ? _FALLBACK_TTS_MODELS : models.filter(isAudioOut)
    // AI agent models are the text-chat quick-model subset
    const aiAgentModels = isEmpty ? _FALLBACK_AI_AGENT_MODELS : quickModels

    return {
      models,
      loading: isLoading,
      error,
      isEmpty,
      quickModels,
      imageGenModels,
      visionModels,
      ttsModels,
      aiAgentModels,
      getById: (id) => byId.get(id),
      isDeprecated: (id) => Boolean(byId.get(id)?.expiration_date),
    }
  }, [models, isLoading, error, isEmpty])
}

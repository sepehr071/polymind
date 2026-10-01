import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Images } from 'lucide-react'
import toast from 'react-hot-toast'
import ImageGrid from '@/components/image/ImageGrid'
import ImageDetailModal from '@/components/image/ImageDetailModal'
import PageHeader from '@/components/layout/PageHeader'
import { imageService } from '@/services/imageService'
import { useImageDownload } from '@/hooks/useImageDownload'

/** Searchable gallery of generated images. The studio stays the generator. */
export default function GalleryPage() {
  const { t } = useTranslation('dashboard')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { download, isDownloading } = useImageDownload()
  const [zoomed, setZoomed] = useState(null)

  const favoriteMutation = useMutation({
    mutationFn: imageService.toggleFavorite,
    onSuccess: (data) => {
      if (zoomed && typeof data?.is_favorite === 'boolean') {
        setZoomed((z) => (z ? { ...z, is_favorite: data.is_favorite } : z))
      }
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: imageService.deleteImage,
    onSuccess: () => {
      toast.success(t('imageHistory.imageDeleted'))
      setZoomed(null)
      queryClient.invalidateQueries({ queryKey: ['imageHistory'] })
    },
    onError: () => toast.error(t('imageHistory.failedToDeleteImage')),
  })

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 pb-24 pt-8">
        <PageHeader
          icon={Images}
          title={t('gallery.title')}
          subtitle={t('gallery.subtitle')}
        />
        <div className="mt-5">
          <ImageGrid variant="cards" onZoom={setZoomed} />
        </div>
      </div>

      <ImageDetailModal
        open={zoomed !== null}
        image={zoomed}
        onClose={() => setZoomed(null)}
        onDownload={(loaded) => zoomed && download(zoomed, loaded)}
        isDownloading={isDownloading}
        onToggleFavorite={() => zoomed && favoriteMutation.mutate(zoomed._id)}
        onDelete={() => zoomed && deleteMutation.mutate(zoomed._id)}
        onContinueEditing={(image) => {
          setZoomed(null)
          navigate('/image-studio', { state: { editImage: image } })
        }}
      />
    </div>
  )
}

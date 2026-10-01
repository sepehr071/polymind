import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { cn } from '@/utils/cn'

const MAX_SIZE_BYTES = 500 * 1024 * 1024

const ACCEPT = {
  'audio/mpeg': ['.mp3'],
  'audio/wav': ['.wav'],
  'audio/x-wav': ['.wav'],
  'audio/x-m4a': ['.m4a'],
  'audio/mp4': ['.m4a', '.mp4'],
  'audio/webm': ['.webm'],
  'audio/ogg': ['.ogg', '.oga'],
  'video/mp4': ['.mp4'],
  'video/webm': ['.webm'],
}

export default function Dropzone({ onFilePicked, disabled, className }) {
  const { t } = useTranslation('meetings')

  const onDrop = useCallback(
    (accepted, rejections) => {
      if (rejections.length > 0) {
        const first = rejections[0]
        const code = first.errors[0]?.code
        if (code === 'file-too-large') {
          toast.error(t('upload.fileTooLarge'))
        } else if (code === 'file-invalid-type') {
          toast.error(t('upload.fileInvalidType'))
        } else {
          toast.error(t('upload.fileRejected'))
        }
        return
      }
      const file = accepted[0]
      if (file) onFilePicked(file)
    },
    [onFilePicked, t]
  )

  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      onDrop,
      accept: ACCEPT,
      maxSize: MAX_SIZE_BYTES,
      maxFiles: 1,
      multiple: false,
      disabled,
    })

  return (
    <div
      {...getRootProps({
        className: cn(
          'group flex h-full min-h-44 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-border bg-background-elevated/40 p-6 text-center transition-all',
          'hover:border-accent/50 hover:bg-accent/5',
          isDragActive && 'border-accent bg-accent/10 ring-[3px] ring-accent/15',
          isDragReject && 'border-error bg-error/5',
          disabled && 'cursor-not-allowed opacity-60',
          className
        ),
      })}
    >
      <input {...getInputProps()} />
      <div className="grid size-12 place-items-center rounded-full bg-background-tertiary text-foreground-secondary transition-colors group-hover:bg-accent/15 group-hover:text-accent">
        <Upload className="size-5" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{t('upload.fileLabel')}</p>
        <p className="text-[11px] text-foreground-secondary">
          {t('upload.fileHint')}
        </p>
      </div>
    </div>
  )
}

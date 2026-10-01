import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Save, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { userService } from '@/services/userService'
import { useAuth } from '@/context/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import keycloakClient from '@/services/keycloakClient'

export default function ProfileSection() {
  const { t } = useTranslation('settings')
  const { user, updateUser } = useAuth()
  const sso = !!user?.sso
  const [accountUrl, setAccountUrl] = useState('')
  const [formData, setFormData] = useState({
    display_name: user?.profile?.display_name || user?.display_name || '',
    bio: user?.profile?.bio || '',
  })

  useEffect(() => {
    if (!sso) return
    let cancelled = false
    ;(async () => {
      try {
        await keycloakClient.init()
        if (!cancelled) setAccountUrl(keycloakClient.accountConsoleUrl())
      } catch {
        // hint still renders without the link
      }
    })()
    return () => { cancelled = true }
  }, [sso])

  const updateMutation = useMutation({
    mutationFn: userService.updateProfile,
    onSuccess: (data) => {
      updateUser({ profile: data.profile })
      toast.success(t('profile.updated'))
    },
    onError: () => toast.error(t('profile.failedToUpdate')),
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    updateMutation.mutate(sso ? { bio: formData.bio } : formData)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-1.5">
        <Label htmlFor="email" className="text-[13px] font-semibold">{t('profile.emailLabel')}</Label>
        <Input id="email" type="email" value={user?.email || ''} disabled className="bg-background-tertiary" />
        <p className="text-xs text-foreground-tertiary">{t('profile.emailHint')}</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="display_name" className="text-[13px] font-semibold">{t('profile.displayNameLabel')}</Label>
        <Input
          id="display_name"
          type="text"
          value={formData.display_name}
          onChange={(e) => setFormData((prev) => ({ ...prev, display_name: e.target.value }))}
          placeholder={t('profile.displayNamePlaceholder')}
          disabled={sso}
          className={sso ? 'bg-background-tertiary' : undefined}
        />
        <p className="text-xs text-foreground-tertiary">
          {sso ? t('profile.ssoManagedHint') : t('profile.displayNameHint')}
          {sso && accountUrl ? (
            <>
              {' '}
              <a
                href={accountUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
                dir="ltr"
              >
                {t('profile.editInKeycloak')}
              </a>
            </>
          ) : null}
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="bio" className="text-[13px] font-semibold">{t('profile.bioLabel')}</Label>
        <Textarea
          id="bio"
          value={formData.bio}
          onChange={(e) => setFormData((prev) => ({ ...prev, bio: e.target.value }))}
          rows={3}
          placeholder={t('profile.bioPlaceholder')}
          maxLength={500}
        />
        <p className="text-xs text-foreground-tertiary text-end">
          {t('profile.bioLimit', { count: formData.bio.length })}
        </p>
      </div>
      <Button type="submit" disabled={updateMutation.isPending}>
        {updateMutation.isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin me-2" />
            {t('profile.saving')}
          </>
        ) : (
          <>
            <Save className="h-4 w-4 me-2" />
            {t('profile.saveChanges')}
          </>
        )}
      </Button>
    </form>
  )
}

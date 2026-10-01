import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Loader2, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { authService } from '@/services/authService'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** SSO users set auth_kind on Keycloak login; operator break-glass does not. */
function isSsoSession() {
  try {
    return localStorage.getItem('auth_kind') === 'keycloak'
  } catch {
    return false
  }
}

export default function SecuritySection() {
  const { t } = useTranslation('settings')
  const sso = useMemo(() => isSsoSession(), [])
  const [formData, setFormData] = useState({ current_password: '', new_password: '', confirm_password: '' })

  const changeMutation = useMutation({
    mutationFn: ({ currentPassword, newPassword }) => authService.changePassword(currentPassword, newPassword),
    onSuccess: () => {
      toast.success(t('security.passwordChanged'))
      setFormData({ current_password: '', new_password: '', confirm_password: '' })
    },
    onError: (error) => toast.error(error.response?.data?.error || t('security.failedToChange')),
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (formData.new_password !== formData.confirm_password) {
      toast.error(t('security.passwordsDoNotMatch'))
      return
    }
    if (formData.new_password.length < 8) {
      toast.error(t('security.passwordTooShort'))
      return
    }
    changeMutation.mutate({ currentPassword: formData.current_password, newPassword: formData.new_password })
  }

  if (sso) {
    return (
      <div className="space-y-3 rounded-[16px] border border-line bg-bg-2/50 p-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div className="min-w-0 space-y-1">
            <p className="text-[13px] font-semibold text-fg-0">{t('security.ssoTitle')}</p>
            <p className="text-xs leading-relaxed text-fg-3">{t('security.ssoBody')}</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-1.5">
        <Label htmlFor="current_password" className="text-[13px] font-semibold">{t('security.currentPassword')}</Label>
        <Input
          id="current_password"
          type="password"
          value={formData.current_password}
          onChange={(e) => setFormData((prev) => ({ ...prev, current_password: e.target.value }))}
          required
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="new_password" className="text-[13px] font-semibold">{t('security.newPassword')}</Label>
        <Input
          id="new_password"
          type="password"
          value={formData.new_password}
          onChange={(e) => setFormData((prev) => ({ ...prev, new_password: e.target.value }))}
          required
          minLength={8}
        />
        <p className="text-xs text-foreground-tertiary">{t('security.newPasswordHint')}</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="confirm_password" className="text-[13px] font-semibold">{t('security.confirmNewPassword')}</Label>
        <Input
          id="confirm_password"
          type="password"
          value={formData.confirm_password}
          onChange={(e) => setFormData((prev) => ({ ...prev, confirm_password: e.target.value }))}
          required
        />
      </div>
      <Button type="submit" disabled={changeMutation.isPending}>
        {changeMutation.isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin me-2" />
            {t('security.changing')}
          </>
        ) : (
          t('security.changePassword')
        )}
      </Button>
    </form>
  )
}

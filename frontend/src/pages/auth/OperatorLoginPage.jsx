import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import Box from '@mui/material/Box'
import { Eye, EyeOff, ArrowRight, Loader2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import { cn } from '@/lib/utils'
import { useTranslation } from 'react-i18next'

export default function OperatorLoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const { t } = useTranslation('auth')

  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [formData, setFormData] = useState({
    email: '',
    password: '',
  })
  const [errors, setErrors] = useState({})

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: '' }))
    }
  }

  const validate = () => {
    const newErrors = {}

    if (!formData.email) {
      newErrors.email = t('login.errors.email_required')
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = t('login.errors.email_invalid')
    }

    if (!formData.password) {
      newErrors.password = t('login.errors.password_required')
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!validate()) return

    setIsLoading(true)
    try {
      await login(formData.email, formData.password)
      navigate('/dashboard')
    } catch (error) {
      // Error is handled by the login function
    } finally {
      setIsLoading(false)
    }
  }

  return (
    // Mount-reveal animations are CSS keyframes (was framer-motion) so this
    // eager auth route keeps `motion/react` out of the entry chunk. The global
    // reduce-motion rule in index.css freezes them automatically.
    <div className="animate-slide-up">
      <Box
        component="div"
        className={cn('relative isolate overflow-hidden rounded-xl p-7 sm:p-8')}
        sx={solidPanelSx({ radius: RADII.surface })}
      >
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-foreground animate-slide-up">
          {t('operator.toggle')}
        </h2>
        <p
          className="text-foreground-secondary mt-2 animate-fade-in"
          style={{ animationDelay: '0.1s', animationFillMode: 'backwards' }}
        >
          {t('operator.description')}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Email field */}
        <div
          className="space-y-2 animate-slide-up"
          style={{ animationDelay: '0.15s', animationFillMode: 'backwards' }}
        >
          <Label htmlFor="email">{t('login.email_label')}</Label>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            dir="ltr"
            value={formData.email}
            onChange={handleChange}
            variant={errors.email ? 'error' : 'default'}
            placeholder={t('login.email_placeholder')}
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={errors.email ? 'email-error' : undefined}
          />
          {errors.email && (
            <p id="email-error" className="text-sm text-error animate-fade-in">
              {errors.email}
            </p>
          )}
        </div>

        {/* Password field */}
        <div
          className="space-y-2 animate-slide-up"
          style={{ animationDelay: '0.2s', animationFillMode: 'backwards' }}
        >
          <Label htmlFor="password">{t('login.password_label')}</Label>
          <div className="relative">
            <Input
              id="password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              value={formData.password}
              onChange={handleChange}
              variant={errors.password ? 'error' : 'default'}
              className="pe-10"
              placeholder={t('login.password_placeholder')}
              aria-invalid={errors.password ? true : undefined}
              aria-describedby={errors.password ? 'password-error' : undefined}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? t('login.hide_password') : t('login.show_password')}
              aria-pressed={showPassword}
              className="absolute end-1 top-1/2 -translate-y-1/2 h-8 w-8"
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </Button>
          </div>
          {errors.password && (
            <p id="password-error" className="text-sm text-error animate-fade-in">
              {errors.password}
            </p>
          )}
        </div>

        {/* Submit button */}
        <div className="animate-slide-up" style={{ animationDelay: '0.25s', animationFillMode: 'backwards' }}>
          <Button
            type="submit"
            disabled={isLoading}
            className="w-full h-11 text-base shadow-lg shadow-accent/25"
          >
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin me-2" />
                {t('login.submitting')}
              </>
            ) : (
              <>
                {t('login.submit')}
                <ArrowRight className="h-4 w-4 ms-2" />
              </>
            )}
          </Button>
        </div>
      </form>

      <div
        className="mt-6 text-center animate-fade-in"
        style={{ animationDelay: '0.3s', animationFillMode: 'backwards' }}
      >
        <Link
          to="/login"
          className="text-sm text-foreground-secondary hover:text-foreground hover:underline"
        >
          {t('sso.backToLogin')}
        </Link>
      </div>
      </Box>
    </div>
  )
}

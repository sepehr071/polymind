import { useTranslation } from 'react-i18next'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Link from '@mui/material/Link'
import MuiButton from '@mui/material/Button'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import Icon3D from '@/components/ui/icon-3d'

/**
 * Canonical empty-state surface used by feature pages.
 *
 * Material: centred column → brand-tinted 48px icon tile (primary palette) →
 * h5 title → secondary description → optional primary MUI Button CTA →
 * optional 2-col suggestion grid of Material outlined buttons/links →
 * optional secondary MUI Link. Colors flow through the MUI palette so the
 * surface auto-flips in dark mode and mirrors in RTL.
 *
 * Interactivity is gated on handler presence: a `primaryCta`/`suggestion`
 * is only rendered as an interactive `<Button>`/link when it actually carries
 * an `onClick` or `href`. Without one it renders as plain non-interactive text
 * (no dead buttons). In DEV a label-without-handler logs a `console.warn` to
 * surface caller misuse.
 *
 * @param {object} props
 * @param {React.ComponentType<{className?: string}>} [props.icon]
 * @param {string} [props.icon3d] Root-absolute path to a self-hosted 3D raster
 *   icon (e.g. `/icons/3d/book.png`). When set it replaces the tinted lucide
 *   tile with a larger 3D hero; `icon` then acts only as the fallback when
 *   `icon3d` is absent. Use on PRIMARY zero-data states, not filtered/error ones.
 * @param {string} props.title
 * @param {React.ReactNode} [props.description]
 * @param {React.ReactNode} [props.hint] Alias for `description` (compat with the
 *   retired meetings EmptyState); used only when `description` is omitted.
 * @param {'muted'|'destructive'} [props.tone='muted'] `'destructive'` tints the
 *   title with the error palette (compat with the retired meetings EmptyState
 *   error states) and defaults the icon tile to the `rose` tone.
 * @param {'sky'|'amber'|'emerald'|'rose'|'accent'|'neutral'} [props.iconTone]
 *   Overrides the IconTile tone (per-zone wayfinding). Defaults to `rose` when
 *   `tone='destructive'`, otherwise `accent`.
 * @param {{label: string, onClick?: () => void, icon?: React.ComponentType<{className?: string}>, href?: string}} [props.primaryCta]
 * @param {Array<{label: string, icon?: React.ComponentType<{className?: string}>, onClick?: () => void, href?: string}>} [props.suggestions]
 * @param {string} [props.secondaryHref]
 * @param {string} [props.secondaryLabel]
 * @param {string} [props.className]
 * @param {React.ReactNode} [props.children]
 */
export default function EmptyState({
  icon: Icon,
  icon3d,
  title,
  description,
  hint,
  tone = 'muted',
  iconTone,
  primaryCta,
  suggestions,
  secondaryHref,
  secondaryLabel,
  className,
  children,
}) {
  const { t } = useTranslation('common')
  const items = (suggestions || []).slice(0, 4)
  const PrimaryIcon = primaryCta?.icon
  const isDestructive = tone === 'destructive'
  const resolvedIconTone = iconTone || (isDestructive ? 'rose' : 'accent')
  // `hint` is a back-compat alias for `description` (meetings consumers); it only
  // applies when no explicit `description` is given.
  const body = description ?? hint

  if (import.meta.env.DEV) {
    if (primaryCta?.label && !primaryCta.onClick && !primaryCta.href) {
      // eslint-disable-next-line no-console
      console.warn(
        `[EmptyState] primaryCta "${primaryCta.label}" has no onClick or href — rendering as non-interactive text. Provide a handler or omit it.`,
      )
    }
    items.forEach((s) => {
      if (s?.label && !s.onClick && !s.href) {
        // eslint-disable-next-line no-console
        console.warn(
          `[EmptyState] suggestion "${s.label}" has no onClick or href — rendering as non-interactive text. Provide a handler or omit it.`,
        )
      }
    })
  }

  return (
    <Box
      className={cn(className)}
      sx={{
        display: 'flex',
        width: '100%',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2.5,
        px: 3,
        py: 8,
        textAlign: 'center',
      }}
    >
      {icon3d ? (
        <Icon3D src={icon3d} size={72} alt="" />
      ) : Icon ? (
        <IconTile icon={Icon} tone={resolvedIconTone} size="xl" />
      ) : null}

      <Box sx={{ display: 'flex', maxWidth: 448, flexDirection: 'column', alignItems: 'center', gap: 1 }}>
        <Typography variant="h5" sx={{ fontWeight: 600, color: isDestructive ? 'error.main' : 'text.primary' }}>
          {title}
        </Typography>
        {body && (
          <Typography variant="body2" sx={{ lineHeight: 1.7, color: 'text.secondary' }}>
            {body}
          </Typography>
        )}
      </Box>

      {primaryCta && primaryCta.label && (
        primaryCta.href ? (
          <Button asChild>
            <a href={primaryCta.href}>
              {PrimaryIcon && <PrimaryIcon className="size-4" />}
              {primaryCta.label}
            </a>
          </Button>
        ) : primaryCta.onClick ? (
          <Button onClick={primaryCta.onClick}>
            {PrimaryIcon && <PrimaryIcon className="size-4" />}
            {primaryCta.label}
          </Button>
        ) : (
          <Typography
            variant="body2"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, fontWeight: 500, color: 'text.primary' }}
          >
            {PrimaryIcon && <PrimaryIcon className="size-4" />}
            {primaryCta.label}
          </Typography>
        )
      )}

      {items.length > 0 && (
        <Box
          sx={{
            display: 'grid',
            width: '100%',
            maxWidth: 576,
            gap: 1,
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
          }}
        >
          {items.map((s, i) => {
            const SIcon = s.icon
            const inner = (
              <>
                {SIcon && (
                  <Box
                    component="span"
                    sx={{
                      display: 'grid',
                      placeItems: 'center',
                      width: 28,
                      height: 28,
                      borderRadius: 1.5,
                      flexShrink: 0,
                      backgroundColor: 'action.hover',
                      color: 'text.secondary',
                    }}
                  >
                    <SIcon className="size-3.5" />
                  </Box>
                )}
                <Box component="span" sx={{ flex: 1, lineHeight: 1.4, textAlign: 'start' }}>
                  {s.label}
                </Box>
              </>
            )

            // Material outlined affordance: ripple + brand focus from the theme.
            const suggestionSx = {
              justifyContent: 'flex-start',
              gap: 1.5,
              px: 2,
              py: 1.5,
              textTransform: 'none',
              fontWeight: 500,
              fontSize: '0.875rem',
              borderRadius: 3,
              borderColor: 'divider',
              color: 'text.primary',
              textAlign: 'start',
              '&:hover': { borderColor: 'text.disabled', backgroundColor: 'action.hover' },
            }

            if (s.href) {
              return (
                <MuiButton key={i} variant="outlined" color="inherit" component="a" href={s.href} sx={suggestionSx}>
                  {inner}
                </MuiButton>
              )
            }

            if (s.onClick) {
              return (
                <MuiButton key={i} variant="outlined" color="inherit" onClick={s.onClick} sx={suggestionSx}>
                  {inner}
                </MuiButton>
              )
            }

            return (
              <Box
                key={i}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1.5,
                  px: 2,
                  py: 1.5,
                  fontSize: '0.875rem',
                  borderRadius: 3,
                  border: '1px solid',
                  borderColor: 'divider',
                  color: 'text.primary',
                }}
              >
                {inner}
              </Box>
            )
          })}
        </Box>
      )}

      {secondaryHref && (
        <Link
          href={secondaryHref}
          underline="hover"
          sx={{ fontSize: '0.75rem', color: 'text.secondary', '&:hover': { color: 'text.primary' } }}
        >
          {secondaryLabel || t('aria.learnMore')}
        </Link>
      )}

      {children}
    </Box>
  )
}

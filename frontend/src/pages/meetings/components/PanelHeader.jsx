/**
 * Section header for meeting-detail panels. This is a SECTION sub-heading, not a
 * page-level header — the meeting detail page already carries page chrome (rail
 * context + top bar). So we render an <h2> (not a second <h1>) and the kicker
 * uses the section tone (amber/studio), never sky.
 *
 * @param {object} props
 * @param {string} props.kicker
 * @param {React.ReactNode} props.title
 * @param {React.ReactNode} [props.subtitle]
 * @param {React.ReactNode} [props.actions]
 */
export default function PanelHeader({ kicker, title, subtitle, actions }) {
  return (
    <header className="mb-6">
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
            {kicker}
          </p>
          <h2 className="mt-1 text-[19px] font-bold leading-tight tracking-[-0.01em] text-foreground">
            {title}
          </h2>
          {subtitle && (
            <p className="mt-1 text-[13px] text-foreground-secondary">
              {subtitle}
            </p>
          )}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
    </header>
  )
}

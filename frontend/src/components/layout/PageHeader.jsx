import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'

/**
 * PageHeader — canonical page header: optional back link, title row, and an
 * optional children slot for custom sub-rows (tabs, meta, filters).
 *
 * Title row is responsive: stacks on mobile, splits start/end on >= sm.
 * Start side carries an optional brand icon + title + subtitle; end side
 * carries actions. i18n-agnostic — callers pass already-translated strings.
 * Extra props such as `tone` are ignored so existing callers keep working.
 *
 * @param {React.ReactNode} title       page title
 * @param {React.ReactNode} [subtitle]  one-line description under the title
 * @param {React.ElementType} [icon]    lucide icon beside the title
 * @param {React.ReactNode} [actions]   end-side controls (buttons, menus)
 * @param {string} [backTo]             react-router path for the back link
 * @param {React.ReactNode} [backLabel] back link text (required for backTo to render)
 * @param {React.ReactNode} [children]  custom sub-rows below the title row
 */
function PageHeader({ title, subtitle, icon: Icon, actions, backTo, backLabel, children }) {
  return (
    <div>
      {backTo && (
        <Link
          to={backTo}
          className="mb-3 inline-flex items-center gap-1.5 text-sm text-foreground-secondary transition-colors hover:text-foreground"
        >
          <ArrowRight className="h-4 w-4 rtl:rotate-180" />
          {backLabel}
        </Link>
      )}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {Icon && <Icon className="h-5 w-5 shrink-0 text-accent" />}
            <h1 className="text-2xl font-extrabold leading-tight tracking-tight text-foreground">
              {title}
            </h1>
          </div>
          {subtitle && <p className="mt-1 text-sm text-foreground-secondary">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2 sm:flex-shrink-0">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

export default PageHeader
export { PageHeader }

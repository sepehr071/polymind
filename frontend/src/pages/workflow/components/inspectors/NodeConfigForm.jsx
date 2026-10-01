import { Label } from '@/components/ui/label';

/**
 * ConfigSection — wraps the Configure tab body with consistent padding and spacing.
 */
export function ConfigSection({ children }) {
  return <div className="space-y-4 p-4">{children}</div>;
}

/**
 * Field — a labelled form field with optional help and error text.
 *
 * Props:
 *   label    {string}     — field label (rendered as <Label>)
 *   help     {string}     — small muted hint below the control
 *   error    {string}     — small destructive error below the control
 *   children {ReactNode}  — the input control(s)
 */
export function Field({ label, help, error, children }) {
  return (
    <div className="space-y-1.5">
      {label && (
        <Label className="text-xs font-semibold uppercase tracking-wide text-foreground-secondary">
          {label}
        </Label>
      )}
      {children}
      {help && <p className="text-[11px] text-foreground-tertiary">{help}</p>}
      {error && <p className="text-[11px] text-destructive">{error}</p>}
    </div>
  );
}

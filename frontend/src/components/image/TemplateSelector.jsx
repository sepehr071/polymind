import TemplateGallery from './TemplateGallery'

/**
 * Thin wrapper kept for the composer [+] popover's external contract. Delegates
 * to the compact TemplateGallery. The popover's `onSelect` takes a single
 * `text` arg, so the gallery's `(text, template)` signature is back-compatible.
 *
 * Props (unchanged): { onSelect, disabled }
 */
export default function TemplateSelector({ onSelect, disabled = false }) {
  return (
    <TemplateGallery
      variant="compact"
      onSelect={(text) => onSelect(text)}
      disabled={disabled}
    />
  )
}

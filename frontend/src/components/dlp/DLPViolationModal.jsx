import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Button } from '@/components/ui/button'
import { SeverityBadge, ActionBadge } from '@/components/dlp/badges'
import DLPExplainer from '@/components/dlp/DLPExplainer'

const SEVERITY_RANK = { critical: 4, high: 3, medium: 2, low: 1 }
const ACTION_RANK = { block: 4, require_confirm: 3, redact: 2, warn: 1 }
/** Max sample snippets kept per rule group (rest collapsed into a count). */
const MAX_SAMPLES = 2

function titleKey(highestAction) {
  // Stale `require_confirm` is a block — there is no confirm dialog.
  if (highestAction === 'block' || highestAction === 'require_confirm') return 'violationModal.titleBlock'
  if (highestAction === 'redact') return 'violationModal.titleRedact'
  return 'violationModal.titleWarn'
}

/**
 * Collapse N raw matches into one row per (source, rule_id, action).
 * Spreadsheet scans often return 60–300 near-identical hits; the modal should
 * show "Employee ID · 60 findings", not 60 cards.
 */
export function groupMatches(matches = []) {
  const map = new Map()
  for (const m of matches) {
    if (!m || typeof m !== 'object') continue
    const action = m.action === 'require_confirm' ? 'block' : (m.action || 'warn')
    const key = `${m.source || 'builtin'}::${m.rule_id || 'unknown'}::${action}`
    const existing = map.get(key)
    if (!existing) {
      map.set(key, {
        rule_id: m.rule_id,
        rule_name: m.rule_name,
        severity: m.severity || 'medium',
        action,
        source: m.source || 'builtin',
        description: m.description || '',
        category: m.category,
        count: 1,
        samples: m.snippet ? [m.snippet] : [],
      })
      continue
    }
    existing.count += 1
    // Prefer higher severity if mixed under same key (shouldn't happen often).
    if ((SEVERITY_RANK[m.severity] || 0) > (SEVERITY_RANK[existing.severity] || 0)) {
      existing.severity = m.severity
    }
    // Prefer non-empty LLM reason.
    if (m.source === 'llm' && m.description && !existing.description) {
      existing.description = m.description
    }
    if (
      m.snippet
      && existing.samples.length < MAX_SAMPLES
      && !existing.samples.includes(m.snippet)
    ) {
      existing.samples.push(m.snippet)
    }
  }

  const groups = Array.from(map.values())
  // Smart-scan first, then by action strength, then count (noisier rules last).
  groups.sort((a, b) => {
    const src = (a.source === 'llm' ? 0 : 1) - (b.source === 'llm' ? 0 : 1)
    if (src !== 0) return src
    const act = (ACTION_RANK[b.action] || 0) - (ACTION_RANK[a.action] || 0)
    if (act !== 0) return act
    const sev = (SEVERITY_RANK[b.severity] || 0) - (SEVERITY_RANK[a.severity] || 0)
    if (sev !== 0) return sev
    return b.count - a.count
  })
  return groups
}

function FindingCard({ group }) {
  const { t } = useTranslation('dlp')
  const [open, setOpen] = useState(false)

  const ruleName = t(`rules.${group.rule_id}.name`, {
    defaultValue: group.rule_name || group.rule_id,
  })
  const reason =
    group.source === 'llm'
      ? (group.description || t(`rules.${group.rule_id}.reason`, { defaultValue: '' }))
      : t(`rules.${group.rule_id}.reason`, {
          defaultValue: group.description || '',
        })

  const extraCount = Math.max(0, group.count - group.samples.length)
  const canExpandSamples =
    group.source !== 'llm' && group.samples.length > 0

  return (
    <div className="bg-background-secondary border-border rounded-lg p-3 space-y-1.5 border text-start">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={group.severity} />
        <ActionBadge action={group.action} />
        <span className="text-[12px] font-medium text-foreground">{ruleName}</span>
        {group.count > 1 && (
          <span className="inline-flex items-center rounded-full border border-border bg-background-tertiary px-2 py-0.5 text-[10.5px] font-medium text-foreground-secondary tabular-nums">
            {t('violationModal.findingCount', { count: group.count })}
          </span>
        )}
      </div>
      {reason && (
        <p className="text-[12px] text-foreground-secondary">{reason}</p>
      )}
      {group.count > 1 && group.source !== 'llm' && (
        <p className="text-[11px] text-foreground-tertiary">
          {t('violationModal.groupedHint', { count: group.count })}
        </p>
      )}
      {canExpandSamples && (
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="group inline-flex items-center gap-1 text-[11px] text-foreground-tertiary transition-colors hover:text-foreground-secondary">
            <ChevronDown
              className="h-3 w-3 transition-transform group-data-[state=open]:rotate-180"
              aria-hidden="true"
            />
            <span className="group-data-[state=open]:hidden">
              {t('violationModal.showSnippet')}
            </span>
            <span className="hidden group-data-[state=open]:inline">
              {t('violationModal.hideSnippet')}
            </span>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="mt-1.5 space-y-1">
              {group.samples.map((snip, i) => (
                <li key={`${group.rule_id}-s-${i}`}>
                  <code
                    dir="ltr"
                    className="inline-block max-w-full break-all rounded bg-background-tertiary px-1.5 py-0.5 font-mono text-[11px]"
                  >
                    {snip}
                  </code>
                </li>
              ))}
            </ul>
            {extraCount > 0 && (
              <p className="mt-1 text-[11px] text-foreground-tertiary">
                {t('violationModal.moreHidden', { count: extraCount })}
              </p>
            )}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

export default function DLPViolationModal({
  isOpen,
  onClose,
  matches = [],
  highestAction = 'warn',
  onModify,
  onRedactSend,
  redactedPreview = null,
  redactable = false,
}) {
  const { t } = useTranslation('dlp')
  const isBlocked = highestAction === 'block' || highestAction === 'require_confirm'

  const groups = useMemo(() => groupMatches(matches), [matches])
  const totalFindings = matches?.length || 0
  const groupCount = groups.length

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose?.() }}>
      <DialogContent
        className="sm:max-w-lg"
        // A block (including a stale require_confirm) announces as an alarm.
        // Redact stays an ordinary dialog.
        role={isBlocked ? 'alertdialog' : 'dialog'}
        aria-modal="true"
        aria-labelledby="dlp-violation-modal-title"
        aria-describedby="dlp-violation-modal-description"
      >
        <DialogHeader>
          <DialogTitle id="dlp-violation-modal-title">{t(titleKey(highestAction))}</DialogTitle>
          <DialogDescription id="dlp-violation-modal-description">
            {t('violationModal.intro')}
            {totalFindings > 1 && groupCount > 0 && (
              <span className="mt-1 block text-foreground-tertiary">
                {t('violationModal.summaryLine', {
                  findings: totalFindings,
                  types: groupCount,
                })}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {/* Cap height tightly: groups are few (rule types), not one row per hit. */}
        <div className="max-h-[min(40vh,280px)] overflow-y-auto space-y-2 py-1">
          {groups.map((g) => (
            <FindingCard
              key={`${g.source}-${g.rule_id}-${g.action}`}
              group={g}
            />
          ))}
        </div>

        {/* On-demand transparency: what we check for, that the message text is
            never stored, and who set this up. Honesty over silence. */}
        <DLPExplainer />

        {/* Redacted preview — shows the scrubbed text with placeholders so the
            user can see exactly what will be sent before opting into redaction. */}
        {redactable && redactedPreview && (
          <div className="space-y-1.5 text-start">
            <p className="text-[11px] font-medium text-foreground-secondary">
              {t('violationModal.redactedPreview')}
            </p>
            <pre
              dir="ltr"
              className="max-h-[120px] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-background-tertiary p-2.5 font-mono text-[11px] text-foreground"
            >
              {redactedPreview}
            </pre>
            <p className="text-[11px] text-foreground-tertiary">
              {t('violationModal.redactHint')}
            </p>
          </div>
        )}

        {isBlocked && (
          <p className="text-[11px] text-foreground-tertiary text-start">
            {t('violationModal.blockHint')}
          </p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onModify}>
            {t('violationModal.modify')}
          </Button>
          {/* Redaction neutralizes a block, so this stays available even when
              the highest action is `block` — as long as the text is redactable. */}
          {redactable && onRedactSend && (
            <Button variant="outline" onClick={onRedactSend}>
              {t('violationModal.redactAndSend')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

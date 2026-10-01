import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  Plus,
  Trash2,
  Sparkles,
  Undo2,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Info,
  ChevronDown,
  Search,
} from 'lucide-react'
import { fmtDate } from '@/utils/dateLocale'
import Section from '@/components/teams/Section'
import StatTile from '@/components/teams/StatTile'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { IconTile } from '@/components/ui/icon-tile'
import { dlpService } from '@/services/dlpService'
import { glassSx, GLASS_CLASS, solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import { cn } from '@/lib/utils'
import { SeverityBadge, ActionBadge, ACTION_TONES } from '@/components/dlp/badges'

const RULE_GROUP_ORDER = ['secrets', 'financial', 'identity', 'pii', 'network', 'other']
const KNOWN_RULE_CATS = new Set(['secrets', 'financial', 'identity', 'pii', 'network'])
const SENSITIVITY_TIERS = ['lenient', 'balanced', 'strict']
const MODE_OPTIONS = ['enforce', 'redact']

function fmtDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return fmtDate(d, 'MMM d, yyyy HH:mm')
}

/** Live actions are warn | block. A saved `require_confirm` displays and saves as block. */
function liveAction(action, fallback) {
  if (action === 'require_confirm') return 'block'
  return action || fallback
}

function emptyPattern() {
  return {
    _clientId: Math.random().toString(36).slice(2),
    name: '',
    match_type: 'text',
    text: '',
    regex: '',
    severity: 'high',
    action: 'block',
    regexError: null,
    _showOptions: false,
  }
}

/** Selectable outcome / carefulness card (nested tier, not glass-on-glass). */
function ChoiceCard({ selected, disabled, onClick, title, description, className }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'rounded-xl border p-3 text-start transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        selected
          ? 'border-accent/50 bg-accent/10 ring-1 ring-inset ring-accent/25'
          : 'border-line bg-bg-2/50 hover:border-fg-3/40 hover:bg-bg-2/80',
        disabled && 'pointer-events-none opacity-60',
        className,
      )}
    >
      <span className={cn('block text-sm font-semibold', selected ? 'text-accent' : 'text-fg-1')}>
        {title}
      </span>
      {description && (
        <span className="mt-1 block text-[11px] leading-snug text-fg-3">{description}</span>
      )}
    </button>
  )
}

/** Nested disclosure (bg tier, not second glass blur). */
function NestedCard({ title, hint, defaultOpen = false, children }) {
  return (
    <div className="rounded-xl border border-line bg-bg-2/50">
      <Accordion type="single" collapsible defaultValue={defaultOpen ? 'item' : undefined}>
        <AccordionItem value="item" className="border-b-0">
          <AccordionTrigger className="px-3 py-2.5 hover:no-underline">
            <span className="flex min-w-0 flex-col gap-0.5 text-start">
              <span className="text-xs font-semibold text-fg-1">{title}</span>
              {hint && (
                <span className="truncate text-[11px] font-normal text-fg-3">{hint}</span>
              )}
            </span>
          </AccordionTrigger>
          <AccordionContent className="border-t border-line px-3 pb-3 pt-3">
            {children}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  )
}

export default function DLPPolicyTab({ wid, isOwner = false }) {
  const { t } = useTranslation('dlp')
  const { t: tAdmin } = useTranslation('admin')
  const [, setSearchParams] = useSearchParams()

  const [ruleCatalog, setRuleCatalog] = useState([])
  const [stats, setStats] = useState(null)
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)

  const [enabled, setEnabled] = useState(false)
  const [mode, setMode] = useState('enforce')
  const [sensitivity, setSensitivity] = useState('balanced')
  const [notifyOwners, setNotifyOwners] = useState(true)
  const [disabledRules, setDisabledRules] = useState(() => new Set())
  const [patterns, setPatterns] = useState([])
  const [llmClassifier, setLlmClassifier] = useState({
    enabled: false,
    guidance_prompt: '',
    action_thresholds: { confidential: 'warn', restricted: 'block' },
  })

  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [showCustomize, setShowCustomize] = useState(false)

  const [testText, setTestText] = useState('')
  const [testResult, setTestResult] = useState(null)
  const [testRunning, setTestRunning] = useState(false)

  const [isEnhancingGuidance, setIsEnhancingGuidance] = useState(false)
  const [guidanceRevert, setGuidanceRevert] = useState(null)
  const [ruleSearch, setRuleSearch] = useState('')
  const [expandedGroups, setExpandedGroups] = useState(() => new Set(['secrets']))

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [policyRes, statsRes, eventsRes] = await Promise.all([
        dlpService.getPolicy(wid),
        dlpService.getStats(wid, 30),
        dlpService.listEvents(wid, { limit: 10 }),
      ])
      const p = policyRes.policy
      setRuleCatalog(policyRes.rule_catalog || [])
      setEnabled(p.enabled ?? false)
      setMode(p.mode || 'enforce')
      setSensitivity(p.sensitivity || 'balanced')
      setNotifyOwners(p.notify_owners ?? true)
      setDisabledRules(new Set(p.disabled_rules || []))
      setPatterns(
        (p.custom_patterns || []).map((cp) => ({
          ...cp,
          match_type: cp.match_type || 'regex',
          text: cp.text || '',
          regex: cp.regex || '',
          action: liveAction(cp.action, 'block'),
          _clientId: cp.id || Math.random().toString(36).slice(2),
          regexError: null,
          _showOptions: false,
        })),
      )
      const lc = p.llm_classifier || {}
      const at = lc.action_thresholds || {}
      setLlmClassifier({
        enabled: lc.enabled ?? false,
        guidance_prompt: lc.guidance_prompt || '',
        action_thresholds: {
          confidential: liveAction(at.confidential, 'warn'),
          restricted: liveAction(at.restricted, 'block'),
        },
      })
      setStats(statsRes)
      setEvents(eventsRes.rows || [])
      setGuidanceRevert(null)
    } catch (err) {
      toast.error(err.response?.data?.error || t('errors.loadFailed'))
    } finally {
      setLoading(false)
      setDirty(false)
    }
  }, [wid, t])

  useEffect(() => {
    load()
  }, [load])

  function markDirty() {
    setDirty(true)
  }

  function handleEnabledChange(val) {
    setEnabled(val)
    markDirty()
  }
  function handleModeChange(val) {
    setMode(val)
    markDirty()
  }
  function handleSensitivityChange(val) {
    setSensitivity(val)
    markDirty()
  }
  function handleNotifyChange(val) {
    setNotifyOwners(val)
    markDirty()
  }

  function toggleRule(ruleId) {
    if (!isOwner) return
    setDisabledRules((prev) => {
      const next = new Set(prev)
      if (next.has(ruleId)) next.delete(ruleId)
      else next.add(ruleId)
      return next
    })
    markDirty()
  }

  function setGroupEnabled(ruleIds, on) {
    if (!isOwner) return
    setDisabledRules((prev) => {
      const next = new Set(prev)
      for (const id of ruleIds) {
        if (on) next.delete(id)
        else next.add(id)
      }
      return next
    })
    markDirty()
  }

  function toggleGroupExpanded(cat) {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  function addPattern() {
    setPatterns((prev) => [...prev, emptyPattern()])
    markDirty()
  }

  function removePattern(clientId) {
    setPatterns((prev) => prev.filter((p) => p._clientId !== clientId))
    markDirty()
  }

  function updatePattern(clientId, field, value, { dirty: mark = true } = {}) {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p._clientId !== clientId) return p
        const updated = { ...p, [field]: value }
        if (field === 'regex' && updated.match_type === 'regex') {
          try {
            // eslint-disable-next-line no-new
            new RegExp(value)
            updated.regexError = null
          } catch {
            updated.regexError = t('errors.invalidRegex')
          }
        }
        return updated
      }),
    )
    if (mark) markDirty()
  }

  function toggleMatchType(clientId) {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p._clientId !== clientId) return p
        return {
          ...p,
          match_type: p.match_type === 'text' ? 'regex' : 'text',
          regexError: null,
        }
      }),
    )
    markDirty()
  }

  function handleLlmChange(field, value) {
    setLlmClassifier((prev) => ({ ...prev, [field]: value }))
    markDirty()
  }

  function handleLlmThresholdChange(category, value) {
    setLlmClassifier((prev) => ({
      ...prev,
      action_thresholds: { ...prev.action_thresholds, [category]: value },
    }))
    markDirty()
  }

  async function handleRunTest() {
    if (!testText.trim() || !llmClassifier.enabled) return
    setTestRunning(true)
    try {
      const res = await dlpService.testClassifier(testText, wid)
      setTestResult(res?.result || null)
    } catch (err) {
      toast.error(err.response?.data?.error || t('errors.saveFailed'))
    } finally {
      setTestRunning(false)
    }
  }

  async function handleSave() {
    const realPatterns = patterns.filter((p) =>
      p.match_type === 'text' ? String(p.text || '').trim() : String(p.regex || '').trim(),
    )
    const hasRegexErrors = realPatterns.some((p) => p.match_type === 'regex' && p.regexError)
    if (hasRegexErrors) {
      toast.error(t('errors.fixRegex'))
      return
    }
    setSaving(true)
    try {
      const cleanPatterns = realPatterns.map((p) => {
        const value = p.match_type === 'text' ? String(p.text).trim() : p.regex
        const name =
          String(p.name || '').trim() || (p.match_type === 'text' ? value : 'Custom rule')
        const base = {
          name,
          match_type: p.match_type,
          severity: p.severity,
          action: liveAction(p.action, 'block'),
        }
        if (p.id) base.id = p.id
        if (p.match_type === 'text') base.text = value
        else base.regex = p.regex
        return base
      })
      const payload = {
        enabled,
        mode,
        sensitivity,
        notify_owners: notifyOwners,
        disabled_rules: Array.from(disabledRules),
        custom_patterns: cleanPatterns,
        llm_classifier: {
          enabled: llmClassifier.enabled,
          guidance_prompt: llmClassifier.guidance_prompt || undefined,
          action_thresholds: {
            confidential: liveAction(llmClassifier.action_thresholds.confidential, 'warn'),
            restricted: liveAction(llmClassifier.action_thresholds.restricted, 'block'),
          },
        },
      }
      await dlpService.updatePolicy(wid, payload)
      toast.success(t('saveSuccess'))
      setDirty(false)
      setGuidanceRevert(null)
    } catch (err) {
      toast.error(err.response?.data?.error || t('errors.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  function goToActivity() {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('tab', 'activity')
      next.delete('sub')
      return next
    })
  }

  const activeCheckCount = useMemo(
    () => ruleCatalog.filter((r) => !disabledRules.has(r.id)).length,
    [ruleCatalog, disabledRules],
  )

  const groupedRules = useMemo(() => {
    const q = ruleSearch.trim().toLowerCase()
    return RULE_GROUP_ORDER.map((cat) => {
      let rules = ruleCatalog.filter(
        (r) => (KNOWN_RULE_CATS.has(r.category) ? r.category : 'other') === cat,
      )
      if (q) {
        rules = rules.filter((r) => {
          const name = t(`rules.${r.id}.name`, { defaultValue: r.name }).toLowerCase()
          const reason = t(`rules.${r.id}.reason`, {
            defaultValue: r.description || '',
          }).toLowerCase()
          return name.includes(q) || reason.includes(q)
        })
      }
      return { cat, rules }
    }).filter((g) => g.rules.length > 0)
  }, [ruleCatalog, ruleSearch, t])

  const statsTotal = stats?.total_events ?? 0
  const statsEmpty = !statsTotal

  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  const heroSummary = enabled
    ? t('hero.summaryOn', {
        sensitivity: t(`sensitivity.${sensitivity}`),
        mode: t(`mode.${mode}`),
        checks: activeCheckCount,
        ai: llmClassifier.enabled ? t('hero.aiOn') : t('hero.aiOff'),
      })
    : t('hero.summaryOff')

  return (
    <div className={cn('relative max-w-3xl space-y-6', dirty && isOwner && 'pb-20')}>
      {!isOwner && (
        <div className="flex items-start gap-2.5 rounded-xl border border-line bg-bg-2/50 px-3 py-2.5 text-start">
          <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-fg-3" />
          <p className="text-xs text-fg-3">{t('readOnlyNotice')}</p>
        </div>
      )}

      {/* ── 1. Status hero ── */}
      <div
        className={cn('rounded-xl')}
        style={solidPanelSx({ radius: RADII.surface })}
      >
        <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <IconTile
              icon={enabled ? ShieldCheck : ShieldOff}
              tone={enabled ? 'sky' : 'neutral'}
              size="xl"
            />
            <div className="min-w-0 space-y-1 text-start">
              <h3 className="text-[15px] font-semibold text-fg-1">{t('hero.title')}</h3>
              <p className="text-xs leading-snug text-fg-3">{heroSummary}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 sm:pt-1">
            <Switch
              id="dlp-enabled"
              checked={enabled}
              onCheckedChange={isOwner ? handleEnabledChange : undefined}
              disabled={!isOwner}
            />
            <Label htmlFor="dlp-enabled" className="text-sm font-medium">
              {enabled ? t('enabledLabel') : t('disabledLabel')}
            </Label>
          </div>
        </div>

        {!enabled && (
          <div className="border-t border-line px-4 py-3">
            <div className="rounded-xl border border-line bg-bg-2/50 p-3 text-start">
              <p className="text-sm font-medium text-fg-1">{t('hero.offTitle')}</p>
              <p className="mt-1 text-xs leading-relaxed text-fg-3">{t('hero.offBody')}</p>
              {isOwner && (
                <Button
                  type="button"
                  size="sm"
                  className="mt-3"
                  onClick={() => handleEnabledChange(true)}
                >
                  <ShieldAlert className="me-1.5 h-3.5 w-3.5" />
                  {t('hero.turnOn')}
                </Button>
              )}
            </div>
          </div>
        )}

        <div className="border-t border-line px-4 py-3">
          <div className="flex items-start gap-2 text-start">
            <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-fg-3" />
            <p className="text-[11px] leading-relaxed text-fg-3">{t('hero.privacyNote')}</p>
          </div>
        </div>
      </div>

      {/* ── 2. Protection choices (only when on — still editable when off so setup is easy) ── */}
      <Section title={t('sections.policy')} hint={t('sections.policyHint')}>
        <div className="space-y-5">
          <div className="space-y-2">
            <div>
              <Label className="text-xs font-medium text-fg-2">{t('choices.carefulTitle')}</Label>
              <p className="mt-0.5 text-[11px] text-fg-3">{t('choices.carefulHint')}</p>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {SENSITIVITY_TIERS.map((tier) => (
                <ChoiceCard
                  key={tier}
                  selected={sensitivity === tier}
                  disabled={!isOwner}
                  onClick={() => handleSensitivityChange(tier)}
                  title={t(`sensitivity.${tier}`)}
                  description={t(`sensitivity.${tier}Desc`)}
                />
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <div>
              <Label className="text-xs font-medium text-fg-2">{t('choices.outcomeTitle')}</Label>
              <p className="mt-0.5 text-[11px] text-fg-3">{t('choices.outcomeHint')}</p>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {MODE_OPTIONS.map((m) => (
                <ChoiceCard
                  key={m}
                  selected={mode === m}
                  disabled={!isOwner}
                  onClick={() => handleModeChange(m)}
                  title={t(`mode.${m}`)}
                  description={t(`mode.${m}Desc`)}
                />
              ))}
            </div>
            {mode === 'redact' && (
              <p className="text-[11px] text-fg-3 text-start">{t('mode.spanDef')}</p>
            )}
          </div>
        </div>
      </Section>

      {/* Customize checks — rules, events, AI checker, advanced (collapsed by default) */}
      <div className="rounded-[16px] border border-line bg-bg-2/40">
        <button
          type="button"
          onClick={() => setShowCustomize((v) => !v)}
          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-start"
          aria-expanded={showCustomize}
        >
          <div>
            <div className="text-[13px] font-semibold text-fg-0">{t('customize.title')}</div>
            <p className="text-[11px] text-fg-3">{t('customize.hint')}</p>
          </div>
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 text-fg-3 transition-transform',
              showCustomize && 'rotate-180',
            )}
          />
        </button>
      {showCustomize && (
      <div className="space-y-6 border-t border-line px-4 py-4">
      {/* ── 3. Activity snapshot ── */}
      <Section title={t('sections.stats')} hint={t('sections.statsHint')}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatTile label={t('stats.total')} value={stats?.total_events ?? '—'} />
          <StatTile label={t('stats.blocked')} value={stats?.by_action?.block ?? 0} />
          <StatTile label={t('stats.warn')} value={stats?.by_action?.warn ?? 0} />
        </div>
        {statsEmpty && (
          <p className="mt-3 text-xs text-fg-3 text-start">{t('sections.statsEmpty')}</p>
        )}
      </Section>

      <Section
        title={t('sections.recentEvents')}
        hint={t('sections.recentEventsHint')}
        action={
          <Button type="button" variant="ghost" size="sm" className="text-xs" onClick={goToActivity}>
            {t('events.viewAll')}
          </Button>
        }
      >
        {events.length === 0 ? (
          <p className="text-xs text-fg-3 text-start">{t('events.empty')}</p>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-bg-2/50">
            {events.map((ev) => {
              const topMatch = ev.matches?.[0]
              const sourceKey = ev.source
                ? `dlp.source${ev.source.charAt(0).toUpperCase()}${ev.source.slice(1)}`
                : null
              const sourceLabel = sourceKey
                ? tAdmin(sourceKey, { defaultValue: ev.source })
                : '—'
              const ruleLabel = topMatch?.rule_id
                ? t(`rules.${topMatch.rule_id}.name`, {
                    defaultValue: topMatch.rule_name || '—',
                  })
                : topMatch?.rule_name || '—'
              const who = ev.user_email || ev.user_name || '—'
              return (
                <li
                  key={ev._id}
                  className="flex flex-col gap-1.5 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3"
                >
                  <div className="min-w-0 flex-1 space-y-0.5 text-start">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <ActionBadge action={ev.highest_action} />
                      <SeverityBadge severity={topMatch?.severity || 'low'} />
                      <span className="truncate text-sm font-medium text-fg-1" title={ruleLabel}>
                        {ruleLabel}
                      </span>
                    </div>
                    <p className="truncate text-[11px] text-fg-3" title={who}>
                      {who}
                      <span className="mx-1 text-fg-3/50">·</span>
                      {sourceLabel}
                    </p>
                  </div>
                  <time className="flex-shrink-0 text-[11px] text-fg-3 whitespace-nowrap">
                    {fmtDateTime(ev.created_at)}
                  </time>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      {/* ── 4. What we check ── */}
      <Section title={t('sections.builtinRules')} hint={t('sections.builtinRulesHint')}>
        <div className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute start-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-3" />
            <Input
              value={ruleSearch}
              onChange={(e) => setRuleSearch(e.target.value)}
              placeholder={t('sections.builtinSearch')}
              className="ps-8"
              size="sm"
            />
          </div>

          {groupedRules.length === 0 ? (
            <p className="text-xs text-fg-3">{t('events.empty')}</p>
          ) : (
            <div className="space-y-2">
              {groupedRules.map((group) => {
                const ids = group.rules.map((r) => r.id)
                const onCount = ids.filter((id) => !disabledRules.has(id)).length
                const allOn = onCount === ids.length
                const expanded = expandedGroups.has(group.cat) || Boolean(ruleSearch.trim())
                return (
                  <div
                    key={group.cat}
                    className="overflow-hidden rounded-xl border border-line bg-bg-2/50"
                  >
                    <div className="flex items-center gap-2 px-3 py-2.5">
                      <button
                        type="button"
                        className="flex min-w-0 flex-1 items-center gap-2 text-start"
                        onClick={() => toggleGroupExpanded(group.cat)}
                        aria-expanded={expanded}
                      >
                        <ChevronDown
                          className={cn(
                            'h-4 w-4 flex-shrink-0 text-fg-3 transition-transform',
                            !expanded && '-rotate-90 rtl:rotate-90',
                          )}
                        />
                        <div className="min-w-0">
                          <span className="text-sm font-medium text-fg-1">
                            {t(`groups.${group.cat}`, { defaultValue: group.cat })}
                          </span>
                          <span className="ms-2 text-[11px] text-fg-3">
                            {t('groups.countOn', { on: onCount, total: ids.length })}
                          </span>
                        </div>
                      </button>
                      <Switch
                        checked={allOn}
                        onCheckedChange={
                          isOwner ? (v) => setGroupEnabled(ids, v) : undefined
                        }
                        disabled={!isOwner}
                        aria-label={t('groups.toggleAll')}
                        className="flex-shrink-0"
                      />
                    </div>
                    {expanded && (
                      <div className="divide-y divide-line border-t border-line">
                        {group.rules.map((rule) => {
                          const on = !disabledRules.has(rule.id)
                          const name = t(`rules.${rule.id}.name`, { defaultValue: rule.name })
                          const reason = t(`rules.${rule.id}.reason`, {
                            defaultValue: rule.description || '',
                          })
                          return (
                            <div
                              key={rule.id}
                              className="flex items-start gap-3 px-3 py-2.5 ps-9"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-sm font-medium text-fg-1">{name}</span>
                                  <span
                                    className={cn(
                                      'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium',
                                      ACTION_TONES[rule.default_action] || ACTION_TONES.warn,
                                    )}
                                  >
                                    {t(`actionChip.${rule.default_action}`, {
                                      defaultValue: rule.default_action,
                                    })}
                                  </span>
                                </div>
                                {reason && (
                                  <p className="mt-0.5 text-[11px] leading-snug text-fg-3 text-start">
                                    {reason}
                                  </p>
                                )}
                              </div>
                              <Switch
                                checked={on}
                                onCheckedChange={
                                  isOwner ? () => toggleRule(rule.id) : undefined
                                }
                                disabled={!isOwner}
                                aria-label={name}
                                className="mt-0.5 flex-shrink-0"
                              />
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </Section>

      {/* ── 5. Company bans ── */}
      <Section title={t('sections.customPatterns')} hint={t('sections.customPatternsHint')}>
        <div className="space-y-3">
          {patterns.length === 0 && (
            <p className="text-xs text-fg-3 text-start">{t('customPatterns.empty')}</p>
          )}
          {patterns.map((pat) => (
            <div
              key={pat._clientId}
              className="space-y-2 rounded-xl border border-line bg-bg-2/50 p-3"
            >
              <div className="flex flex-wrap items-start gap-2">
                <div className="min-w-[140px] flex-1 space-y-1">
                  <Label className="text-[11px] text-fg-3">{t('customPatterns.name')}</Label>
                  <Input
                    size="sm"
                    value={pat.name}
                    onChange={(e) => updatePattern(pat._clientId, 'name', e.target.value)}
                    placeholder={t('customPatterns.namePlaceholder')}
                    disabled={!isOwner}
                  />
                </div>
                <div className="min-w-[200px] flex-[2] space-y-1">
                  <Label className="text-[11px] text-fg-3">
                    {pat.match_type === 'text'
                      ? t('customPatterns.text')
                      : t('customPatterns.regex')}
                  </Label>
                  {pat.match_type === 'text' ? (
                    <Input
                      size="sm"
                      value={pat.text}
                      onChange={(e) => updatePattern(pat._clientId, 'text', e.target.value)}
                      placeholder={t('customPatterns.textPlaceholder')}
                      disabled={!isOwner}
                    />
                  ) : (
                    <>
                      <Input
                        size="sm"
                        value={pat.regex}
                        onChange={(e) => updatePattern(pat._clientId, 'regex', e.target.value)}
                        placeholder={t('customPatterns.regexPlaceholder')}
                        disabled={!isOwner}
                        aria-invalid={pat.regexError ? true : undefined}
                        className="font-mono"
                        dir="ltr"
                      />
                      {pat.regexError && (
                        <p className="text-[10px] text-err">{pat.regexError}</p>
                      )}
                    </>
                  )}
                  {isOwner && (
                    <button
                      type="button"
                      onClick={() => toggleMatchType(pat._clientId)}
                      className="text-[10px] text-fg-3 transition-colors hover:text-fg-1"
                    >
                      {pat.match_type === 'text'
                        ? t('customPatterns.advancedRegex')
                        : t('customPatterns.usePlainText')}
                    </button>
                  )}
                </div>
                {isOwner && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removePattern(pat._clientId)}
                    className="mt-5 flex-shrink-0 text-fg-3 hover:text-err"
                    aria-label={t('customPatterns.remove')}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>

              {(pat._showOptions || !isOwner) && (
                <div className="grid grid-cols-2 gap-2 sm:flex sm:gap-2">
                  <div className="space-y-1">
                    <Label className="text-[11px] text-fg-3">{t('customPatterns.severity')}</Label>
                    <Select
                      value={pat.severity}
                      onValueChange={(v) => updatePattern(pat._clientId, 'severity', v)}
                      disabled={!isOwner}
                    >
                      <SelectTrigger className="w-full sm:w-[110px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {['critical', 'high', 'medium', 'low'].map((s) => (
                          <SelectItem key={s} value={s}>
                            {t(`severity.${s}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[11px] text-fg-3">{t('customPatterns.action')}</Label>
                    <Select
                      value={pat.action}
                      onValueChange={(v) => updatePattern(pat._clientId, 'action', v)}
                      disabled={!isOwner}
                    >
                      <SelectTrigger className="w-full sm:w-[140px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {['block', 'warn'].map((a) => (
                          <SelectItem key={a} value={a}>
                            {t(`action.${a}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              )}
              {isOwner && (
                <button
                  type="button"
                  onClick={() =>
                    updatePattern(pat._clientId, '_showOptions', !pat._showOptions, {
                      dirty: false,
                    })
                  }
                  className="text-[10px] text-fg-3 transition-colors hover:text-fg-1"
                >
                  {pat._showOptions
                    ? t('customPatterns.hideOptions')
                    : t('customPatterns.showOptions')}
                </button>
              )}
            </div>
          ))}
          {isOwner && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addPattern}
              className="gap-1.5"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('customPatterns.add')}
            </Button>
          )}
        </div>
      </Section>

      {/* ── 6. AI checker ── */}
      <Section title={t('sections.llmClassifier')} hint={t('sections.llmClassifierHint')}>
        <div className="space-y-3">
          <p className="text-[11px] text-fg-3 text-start">{t('llm.intro')}</p>
          <div className="flex items-center gap-3">
            <Switch
              id="llm-enabled"
              checked={llmClassifier.enabled}
              onCheckedChange={(v) => isOwner && handleLlmChange('enabled', v)}
              disabled={!isOwner}
            />
            <Label htmlFor="llm-enabled" className="text-sm">
              {t('llm.enabledLabel')}
            </Label>
          </div>

          <div className="space-y-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label className="text-xs text-fg-2">{t('llm.guidancePrompt')}</Label>
              {isOwner && (
                <div className="flex items-center gap-1.5">
                  {guidanceRevert != null && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1 px-2 text-[11px]"
                      disabled={isEnhancingGuidance}
                      onClick={() => {
                        handleLlmChange('guidance_prompt', guidanceRevert)
                        setGuidanceRevert(null)
                        toast.success(t('llm.enhance.reverted'))
                      }}
                    >
                      <Undo2 className="h-3.5 w-3.5" />
                      {t('llm.enhance.revert')}
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1 px-2 text-[11px]"
                    disabled={isEnhancingGuidance || !llmClassifier.guidance_prompt.trim()}
                    onClick={async () => {
                      const original = llmClassifier.guidance_prompt
                      if (!original.trim()) {
                        toast.error(t('llm.enhance.empty'))
                        return
                      }
                      setIsEnhancingGuidance(true)
                      try {
                        const { enhanced_prompt: enhanced } = await dlpService.enhanceGuidance(
                          wid,
                          original,
                        )
                        if (!enhanced || typeof enhanced !== 'string') {
                          throw new Error('empty')
                        }
                        handleLlmChange('guidance_prompt', enhanced.slice(0, 4000))
                        setGuidanceRevert(original)
                        toast.success(t('llm.enhance.success'))
                      } catch (err) {
                        toast.error(err?.response?.data?.error || t('llm.enhance.fail'))
                      } finally {
                        setIsEnhancingGuidance(false)
                      }
                    }}
                  >
                    {isEnhancingGuidance ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    {isEnhancingGuidance ? t('llm.enhance.running') : t('llm.enhance.button')}
                  </Button>
                </div>
              )}
            </div>
            <p className="text-[11px] text-fg-3">{t('llm.guidancePromptHint')}</p>
            <Textarea
              value={llmClassifier.guidance_prompt}
              onChange={(e) => handleLlmChange('guidance_prompt', e.target.value)}
              placeholder={t('llm.guidancePromptPlaceholder')}
              disabled={!isOwner || isEnhancingGuidance}
              rows={5}
              maxLength={4000}
              className="resize-none text-xs"
            />
            <p className="text-[11px] text-fg-3">
              {llmClassifier.guidance_prompt.length}/4000
            </p>
          </div>

          <div className="space-y-2 pt-1">
            <Label className="text-xs text-fg-2">{t('llm.thresholdsLabel')}</Label>
            <p className="text-[11px] text-fg-3">{t('llm.thresholdsHint')}</p>
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-full space-y-1 sm:w-auto">
                <Label className="text-xs text-fg-2">{t('llm.thresholdConfidential')}</Label>
                <p className="max-w-[200px] text-[11px] text-fg-3">
                  {t('llm.thresholdConfidentialDef')}
                </p>
                <Select
                  value={llmClassifier.action_thresholds.confidential}
                  onValueChange={(v) => isOwner && handleLlmThresholdChange('confidential', v)}
                  disabled={!isOwner}
                >
                  <SelectTrigger className="w-full sm:w-[160px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {['warn', 'block'].map((a) => (
                      <SelectItem key={a} value={a}>
                        {t(`action.${a}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="w-full space-y-1 sm:w-auto">
                <Label className="text-xs text-fg-2">{t('llm.thresholdRestricted')}</Label>
                <p className="max-w-[200px] text-[11px] text-fg-3">
                  {t('llm.thresholdRestrictedDef')}
                </p>
                <Select
                  value={llmClassifier.action_thresholds.restricted}
                  onValueChange={(v) => isOwner && handleLlmThresholdChange('restricted', v)}
                  disabled={!isOwner}
                >
                  <SelectTrigger className="w-full sm:w-[160px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {['warn', 'block'].map((a) => (
                      <SelectItem key={a} value={a}>
                        {t(`action.${a}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <NestedCard title={t('llm.test.title')}>
            <div className="space-y-2">
              {!llmClassifier.enabled && (
                <p className="text-[11px] text-fg-3">{t('llm.test.needsEnabled')}</p>
              )}
              <Textarea
                value={testText}
                onChange={(e) => setTestText(e.target.value)}
                placeholder={t('llm.test.placeholder')}
                rows={3}
                className="resize-none text-xs"
              />
              <Button
                type="button"
                size="sm"
                onClick={handleRunTest}
                disabled={!testText.trim() || !llmClassifier.enabled || testRunning}
              >
                {testRunning ? t('llm.test.running') : t('llm.test.run')}
              </Button>
              {testResult && (
                <div className="space-y-2 rounded-md border border-line bg-bg-1 p-2.5">
                  {!testResult.matches || testResult.matches.length === 0 ? (
                    <p className="text-xs text-fg-3">{t('llm.test.noViolations')}</p>
                  ) : (
                    <>
                      <div className="space-y-1.5">
                        {testResult.matches.map((m, idx) => (
                          <div
                            key={`${m.rule_id}-${idx}`}
                            className="flex flex-wrap items-center gap-2"
                          >
                            <SeverityBadge severity={m.severity} />
                            <ActionBadge action={m.action} />
                            <span className="text-xs text-fg-1">
                              {t(`rules.${m.rule_id}.name`, {
                                defaultValue: m.rule_name || m.rule_id,
                              })}
                            </span>
                          </div>
                        ))}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-fg-3">
                        <span>{t('llm.test.highestAction')}:</span>
                        <ActionBadge action={testResult.highest_action} />
                      </div>
                      {testResult.matches.some((m) => m.source === 'llm') && (
                        <div className="space-y-0.5 text-[11px] text-fg-3">
                          <div className="font-medium text-fg-2">{t('llm.test.smartVerdict')}</div>
                          {testResult.matches
                            .filter((m) => m.source === 'llm')
                            .map((m, idx) => (
                              <div key={`smart-${idx}`}>
                                {m.category ? (
                                  <span className="capitalize">{m.category}</span>
                                ) : null}
                                {m.category && m.description ? ' — ' : null}
                                {m.description || null}
                              </div>
                            ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          </NestedCard>
        </div>
      </Section>

      {/* ── 7. More options ── */}
      <NestedCard title={t('advanced.toggle')} hint={t('advanced.hint')}>
        <div className="space-y-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <Switch
                id="dlp-notify-owners"
                checked={notifyOwners}
                onCheckedChange={isOwner ? handleNotifyChange : undefined}
                disabled={!isOwner}
              />
              <Label htmlFor="dlp-notify-owners" className="text-sm">
                {t('settings.notifyOwners')}
              </Label>
            </div>
            <p className="ps-[52px] text-start text-[11px] text-fg-3">
              {t('settings.notifyOwnersDesc')}
            </p>
          </div>

          <div className="space-y-1.5 text-start text-[11px] text-fg-3">
            <p className="text-xs font-medium text-fg-2">{t('transparency.title')}</p>
            <p>{t('transparency.body1')}</p>
            <p>{t('transparency.body2')}</p>
          </div>
        </div>
      </NestedCard>
      </div>
      )}
      </div>

      {/* Sticky save bar — only when owner has unsaved edits */}
      {dirty && isOwner && (
        <div className="pointer-events-none sticky bottom-3 z-20 flex justify-center">
          <div
            className={cn(
              'pointer-events-auto flex items-center gap-3 rounded-full border border-line px-3 py-2 shadow-lg',
              GLASS_CLASS,
            )}
            style={glassSx({ radius: 999, strong: true })}
          >
            <span className="ps-1 text-xs text-fg-2">{t('unsaved')}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 text-xs"
              disabled={saving}
              onClick={() => load()}
            >
              {t('discard')}
            </Button>
            <Button type="button" size="sm" className="h-8" disabled={saving} onClick={handleSave}>
              {saving ? t('saving') : t('save')}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

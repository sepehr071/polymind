import { Fragment, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import {
  MessageSquare,
  GitBranch,
  BookOpen,
  FileText,
  Sparkles,
  Image as ImageIcon,
  GripVertical,
  Search,
} from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useTranslation } from 'react-i18next'
import { useLanguage } from '@/context/LanguageContext'
import { useCoarsePointer } from '@/hooks/useMediaQuery'
import {
  LANDING_SURFACE,
  EYEBROW_EN,
  EYEBROW_FA,
  H2_CLASS,
  easeOutExpo,
  revealVariants,
  viewportOnce,
} from '../lib/landingStyles'

const demoIcons = { chat: MessageSquare, workflows: GitBranch, knowledge: BookOpen }

// Per-tab duotone backdrop behind the live preview. Token-ized: sky + warm +
// teal, never violet/purple. aria-hidden decorative layer, no animation.
const motifBackdrops = {
  chat:
    'radial-gradient(22rem 22rem at 28% 22%, hsl(var(--accent) / 0.16), transparent 62%), ' +
    'radial-gradient(18rem 18rem at 82% 82%, hsl(var(--landing-warm) / 0.10), transparent 62%)',
  workflows:
    'radial-gradient(22rem 22rem at 28% 22%, hsl(var(--teal) / 0.16), transparent 62%), ' +
    'radial-gradient(18rem 18rem at 82% 82%, hsl(var(--accent) / 0.10), transparent 62%)',
  knowledge:
    'radial-gradient(22rem 22rem at 28% 22%, hsl(var(--landing-warm) / 0.16), transparent 62%), ' +
    'radial-gradient(18rem 18rem at 82% 82%, hsl(var(--accent) / 0.10), transparent 62%)',
}

/* ---- shared bits --------------------------------------------------------- */

function Chip({ children, dot = 'bg-accent' }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-foreground-secondary">
      <span className={`size-1.5 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      {children}
    </span>
  )
}

/* ---- per-feature live previews ------------------------------------------- */

// Chat: shared personas, a streamed reply, and a conversation branch fork.
function ChatPreview({ t, coarse }) {
  return (
    <div className="flex w-full max-w-sm flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <Chip>{t('demo.mock.chat.persona_analyst')}</Chip>
        <Chip dot="bg-[hsl(var(--teal))]">{t('demo.mock.chat.persona_writer')}</Chip>
      </div>

      <div className="self-end max-w-[85%] rounded-2xl rounded-ee-md border border-accent/20 bg-accent/15 px-3.5 py-2 text-xs leading-relaxed text-foreground">
        {t('demo.mock.chat.user')}
      </div>

      <div className="self-start max-w-[90%] rounded-2xl rounded-ss-md border border-white/[0.08] bg-white/[0.04] px-3.5 py-2.5 text-xs leading-relaxed text-foreground-secondary">
        <p>{t('demo.mock.chat.assistant')}</p>
        <span
          className={`mt-2 block h-2.5 w-2/3 rounded-full ${coarse ? 'bg-white/[0.06]' : 'animate-shimmer'}`}
          aria-hidden="true"
        />
      </div>

      <div className="flex items-center gap-2 ps-1">
        <span
          className="-mt-3 size-4 shrink-0 rounded-es-lg border-b border-s border-white/15"
          aria-hidden="true"
        />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-foreground-tertiary">
          <GitBranch className="size-3 text-teal" aria-hidden="true" />
          {t('demo.mock.chat.branch')}
        </span>
      </div>
    </div>
  )
}

// Workflows: a 3-node vertical pipeline with grip handles + connectors.
const WF_NODES = [
  { key: 'input', icon: FileText, tone: 'text-accent bg-accent/15' },
  {
    key: 'agent',
    icon: Sparkles,
    tone: 'text-[hsl(var(--landing-warm))] bg-[hsl(var(--landing-warm)/0.15)]',
  },
  { key: 'output', icon: ImageIcon, tone: 'text-teal bg-[hsl(var(--teal)/0.15)]' },
]

function WorkflowPreview({ t }) {
  return (
    <div className="flex flex-col items-center">
      {WF_NODES.map((n, i) => (
        <Fragment key={n.key}>
          <div className="flex w-56 items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 shadow-[0_8px_24px_-16px_rgba(0,0,0,0.8)]">
            <span className={`grid size-8 shrink-0 place-items-center rounded-lg ${n.tone}`}>
              <n.icon className="size-4" aria-hidden="true" />
            </span>
            <span className="flex-1 text-xs font-medium text-foreground">
              {t(`demo.mock.workflows.${n.key}`)}
            </span>
            <GripVertical className="size-4 text-foreground-tertiary/50" aria-hidden="true" />
          </div>
          {i < WF_NODES.length - 1 && (
            <span
              className="my-1 h-6 w-px bg-gradient-to-b from-white/25 to-white/5"
              aria-hidden="true"
            />
          )}
        </Fragment>
      ))}
    </div>
  )
}

// Knowledge: a search field + result rows, the first row active.
const KN_RESULTS = [
  { key: 'result_1', tag: 'tag_team', active: true },
  { key: 'result_2', tag: 'tag_folder' },
  { key: 'result_3', tag: 'tag_team' },
]

function KnowledgePreview({ t }) {
  return (
    <div className="flex w-full max-w-xs flex-col gap-2.5">
      <div className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2">
        <Search className="size-3.5 shrink-0 text-foreground-tertiary" aria-hidden="true" />
        <span className="flex-1 truncate text-xs text-foreground-secondary">
          {t('demo.mock.knowledge.search')}
        </span>
      </div>
      {KN_RESULTS.map((r) => (
        <div
          key={r.key}
          className={`flex items-center gap-2.5 rounded-xl border px-3 py-2 ${
            r.active
              ? 'border-accent/30 bg-accent/10'
              : 'border-white/[0.06] bg-white/[0.02]'
          }`}
        >
          <span
            className={`grid size-7 shrink-0 place-items-center rounded-lg ${
              r.active ? 'bg-accent/20 text-accent' : 'bg-white/[0.05] text-foreground-tertiary'
            }`}
          >
            <FileText className="size-3.5" aria-hidden="true" />
          </span>
          <span className="flex-1 truncate text-xs text-foreground">
            {t(`demo.mock.knowledge.${r.key}`)}
          </span>
          <span className="shrink-0 rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] text-foreground-tertiary">
            {t(`demo.mock.knowledge.${r.tag}`)}
          </span>
        </div>
      ))}
    </div>
  )
}

function FeaturePreview({ id, t, coarse }) {
  if (id === 'chat') return <ChatPreview t={t} coarse={coarse} />
  if (id === 'workflows') return <WorkflowPreview t={t} />
  return <KnowledgePreview t={t} />
}

export default function DemoSection() {
  const [activeTab, setActiveTab] = useState('chat')
  const { t } = useTranslation('landing')
  const { isRTL } = useLanguage()
  const reduceMotion = useReducedMotion()
  const coarse = useCoarsePointer()

  const eyebrowClass = isRTL ? EYEBROW_FA : EYEBROW_EN

  const demos = ['chat', 'workflows', 'knowledge'].map((id) => ({
    id,
    icon: demoIcons[id],
    title: t(`demo.items.${id}.title`),
    description: t(`demo.items.${id}.description`),
    features: t(`demo.items.${id}.features`, { returnObjects: true }),
  }))

  return (
    <section id="demo" className="relative py-[clamp(5rem,12vh,9rem)] px-6 bg-background overflow-hidden">
      <div className="relative max-w-6xl mx-auto">
        {/* Header */}
        <motion.div
          variants={revealVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
          className="text-center mb-14"
        >
          <span className={`${eyebrowClass} block mb-4`}>{t('demo.badge')}</span>
          <h2 className={`${H2_CLASS} font-display text-foreground mb-4`}>
            {t('demo.title')}
          </h2>
          <p className="text-lg font-light text-foreground-secondary max-w-2xl mx-auto leading-relaxed">
            {t('demo.subtitle')}
          </p>
        </motion.div>

        {/* Panel */}
        <motion.div
          variants={revealVariants}
          initial={reduceMotion ? false : 'hidden'}
          whileInView="visible"
          viewport={viewportOnce}
        >
          <Tabs value={activeTab} onValueChange={setActiveTab} variant="segmented" className="w-full">
            <TabsList
              className={`${LANDING_SURFACE} grid w-full max-w-md mx-auto grid-cols-3 mb-8 p-1`}
            >
              {demos.map((demo) => (
                <TabsTrigger
                  key={demo.id}
                  value={demo.id}
                  aria-label={t(`demo.tabs.${demo.id}`)}
                  className="flex items-center justify-center gap-2 rounded-xl text-foreground-secondary transition-colors duration-300 data-[state=active]:bg-accent/10 data-[state=active]:text-accent"
                >
                  <demo.icon className="size-4" aria-hidden="true" />
                  <span className="hidden sm:inline">{t(`demo.tabs.${demo.id}`)}</span>
                </TabsTrigger>
              ))}
            </TabsList>

            {demos.map((demo) => (
              <TabsContent key={demo.id} value={demo.id} className="mt-0">
                <div className={`${LANDING_SURFACE} overflow-hidden`}>
                  <div className="grid lg:grid-cols-2">
                    {/* Content */}
                    <div className="p-8 lg:p-12 flex flex-col justify-center">
                      <motion.h3
                        initial={reduceMotion ? false : { opacity: 0, x: isRTL ? 16 : -16 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.5, ease: easeOutExpo, delay: 0.1 }}
                        className="text-2xl lg:text-3xl font-display font-bold text-foreground mb-4"
                      >
                        {demo.title}
                      </motion.h3>

                      <motion.p
                        initial={reduceMotion ? false : { opacity: 0, x: isRTL ? 16 : -16 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.5, ease: easeOutExpo, delay: 0.18 }}
                        className="text-foreground-secondary font-light mb-6 leading-relaxed"
                      >
                        {demo.description}
                      </motion.p>

                      <ul className="flex flex-col gap-3">
                        {Array.isArray(demo.features) &&
                          demo.features.map((feature, i) => (
                            <motion.li
                              key={feature}
                              initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{
                                type: 'spring',
                                stiffness: 260,
                                damping: 24,
                                delay: reduceMotion ? 0 : 0.25 + i * 0.08,
                              }}
                              className="flex items-center gap-3 text-sm text-foreground-secondary"
                            >
                              <span
                                className="size-1.5 shrink-0 rounded-full bg-accent"
                                aria-hidden="true"
                              />
                              {feature}
                            </motion.li>
                          ))}
                      </ul>
                    </div>

                    {/* Live preview well: inset screen + duotone glow + product mock */}
                    <div className="relative flex items-center justify-center p-6 sm:p-10 min-h-[360px] overflow-hidden border-t lg:border-t-0 lg:border-s border-white/[0.06] bg-black/[0.18]">
                      <div
                        aria-hidden="true"
                        className="absolute inset-0 pointer-events-none"
                        style={{ backgroundImage: motifBackdrops[demo.id] }}
                      />
                      <AnimatePresence mode="wait">
                        <motion.div
                          key={demo.id}
                          initial={reduceMotion ? false : { opacity: 0, y: 12, filter: 'blur(8px)' }}
                          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                          exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -8, filter: 'blur(8px)' }}
                          transition={{ duration: 0.45, ease: easeOutExpo }}
                          className="relative z-10 flex w-full justify-center"
                        >
                          <FeaturePreview id={demo.id} t={t} coarse={coarse} />
                        </motion.div>
                      </AnimatePresence>
                    </div>
                  </div>
                </div>
              </TabsContent>
            ))}
          </Tabs>
        </motion.div>
      </div>
    </section>
  )
}

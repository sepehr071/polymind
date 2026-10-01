import { useRef, useEffect } from 'react'
import { ArrowDownToLine, ArrowDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../../utils/cn'
import { getTextDirection, containsRTL } from '../../utils/rtl'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import DebaterResponse from './DebaterResponse'
import JudgeVerdict from './JudgeVerdict'

export default function DebateArena({
  topic,
  debaters,
  judge,
  rounds,
  currentRound,
  debaterResponses,
  debaterStreaming,
  debaterLoading,
  debaterConcluded = {},
  isInfiniteMode = false,
  judgeContent,
  judgeStreaming,
  judgeLoading,
  isComplete,
  autoScrollEnabled = true,
  onToggleAutoScroll,
}) {
  const { t } = useTranslation('debate')
  const bottomRef = useRef(null)

  const isAnyDebaterStreaming = Object.values(debaterStreaming).some(Boolean)
  const isAnyDebaterLoading = Object.values(debaterLoading).some(Boolean)
  const isActivelyStreaming = isAnyDebaterStreaming || isAnyDebaterLoading || judgeStreaming || judgeLoading

  useEffect(() => {
    if (autoScrollEnabled && bottomRef.current && isActivelyStreaming) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [currentRound, autoScrollEnabled, isActivelyStreaming, judgeContent])

  return (
    <div className="flex flex-col gap-6 pb-20 md:pb-0">
      {/* Topic Banner */}
      <Card className="px-6 py-4">
        <p className="text-xs font-medium text-foreground-tertiary uppercase tracking-wider mb-1">
          {t('arena.debateTopic')}
        </p>
        <p
          className={`text-lg font-medium text-foreground ${containsRTL(topic) ? 'font-persian' : ''}`}
          dir={getTextDirection(topic)}
        >
          {topic}
        </p>
      </Card>

      {/* Rounds */}
      {Array.from({ length: currentRound }, (_, roundIndex) => (
        <div key={roundIndex} className="space-y-4">
          {/* Round Header */}
          <div className="flex items-center gap-4">
            <div className="flex-1 h-px bg-border" />
            <span className="px-4 py-1 rounded-full bg-background-tertiary text-sm font-medium text-foreground-secondary">
              {isInfiniteMode
                ? t('arena.roundInfinite', { round: roundIndex + 1 })
                : t('arena.roundOf', { round: roundIndex + 1, total: rounds })}
            </span>
            <div className="flex-1 h-px bg-border" />
          </div>

          {/* Debater Responses Grid */}
          <div
            className={cn(
              'grid gap-4 md:min-h-[300px]',
              debaters.length === 2 && 'grid-cols-1 md:grid-cols-2',
              debaters.length === 3 && 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3',
              debaters.length === 4 && 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-4',
              debaters.length === 5 && 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5'
            )}
          >
            {debaters.map((debater) => {
              const responseKey = `${roundIndex}_${debater._id}`
              const content = debaterResponses[responseKey] || ''
              const isStreaming = debaterStreaming[responseKey] || false
              const isLoading = debaterLoading[responseKey] || false
              const isConcluded = isInfiniteMode && roundIndex === currentRound - 1 && debaterConcluded[debater._id]

              return (
                <DebaterResponse
                  key={debater._id}
                  config={debater}
                  content={content}
                  isStreaming={isStreaming}
                  isLoading={isLoading}
                  concluded={isConcluded}
                />
              )
            })}
          </div>
        </div>
      ))}

      {/* Judge Verdict Section */}
      <JudgeVerdict
        config={judge}
        content={judgeContent}
        isStreaming={judgeStreaming}
        isLoading={judgeLoading}
        isComplete={isComplete}
      />

      {/* Scroll anchor */}
      <div ref={bottomRef} />

      {/* Auto-scroll toggle button */}
      {onToggleAutoScroll && (
        <div className="fixed bottom-6 end-6 z-50">
          <Button
            onClick={onToggleAutoScroll}
            variant={autoScrollEnabled ? 'default' : 'secondary'}
            className="rounded-full"
            title={autoScrollEnabled ? t('arena.autoScrollEnabled') : t('arena.autoScrollDisabled')}
          >
            {autoScrollEnabled ? (
              <ArrowDownToLine className="h-4 w-4" />
            ) : (
              <ArrowDown className="h-4 w-4" />
            )}
            <span className="hidden sm:inline text-sm font-medium ms-2">
              {autoScrollEnabled ? t('arena.autoScrollOn') : t('arena.autoScrollOff')}
            </span>
          </Button>
        </div>
      )}
    </div>
  )
}

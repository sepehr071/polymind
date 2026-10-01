import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, X, Check, Play, Gavel, Users, Brain, Zap, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { configService } from '../../services/chatService'
import { useProject } from '../../context/ProjectContext'
import { cn } from '../../utils/cn'
import { getTextDirection, containsRTL } from '../../utils/rtl'
import { DEFAULT_MODELS } from '../../constants/models'
import { prettifyModelName } from '@/utils/modelName'
import ModelLogo from '../chat/ModelLogo'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { Fragment } from 'react'
import { Avatar, AvatarFallback } from '../ui/avatar'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'

export default function DebateSetup({ onStart, isLoading: isStarting }) {
  const { t } = useTranslation('debate')
  const [topic, setTopic] = useState('')
  const [debaters, setDebaters] = useState([])
  const [judge, setJudge] = useState(null)
  const [rounds, setRounds] = useState(3)
  const [thinkingType, setThinkingType] = useState('balanced')
  const [responseLength, setResponseLength] = useState('balanced')
  const [showDebaterSelector, setShowDebaterSelector] = useState(false)
  const [showJudgeSelector, setShowJudgeSelector] = useState(false)

  const { currentProject } = useProject()
  const projectId = currentProject?._id || null

  const { data: configsData, isLoading: configsLoading } = useQuery({
    queryKey: ['configs', { projectId }],
    queryFn: () => configService.getConfigs(projectId ? { project_id: projectId } : undefined),
  })

  const configs = configsData?.configs || []

  const toggleDebater = (config) => {
    if (debaters.find(c => c._id === config._id)) {
      setDebaters(debaters.filter(c => c._id !== config._id))
    } else if (debaters.length < 5) {
      setDebaters([...debaters, config])
    }
  }

  const addQuickDebater = (model) => {
    if (debaters.length >= 5) return
    const quickDebater = {
      _id: `quick:${model.id}`,
      name: model.name,
      model_id: model.id,
      model_name: model.name,
      avatar: { type: 'logo', value: model.logo },
      isQuickModel: true
    }
    if (debaters.find(d => d._id === quickDebater._id)) return
    setDebaters([...debaters, quickDebater])
  }

  const setQuickJudge = (model) => {
    const quickJudge = {
      _id: `quick:${model.id}`,
      name: model.name,
      model_id: model.id,
      model_name: model.name,
      avatar: { type: 'logo', value: model.logo },
      isQuickModel: true
    }
    setJudge(quickJudge)
    setShowJudgeSelector(false)
  }

  const selectJudge = (config) => {
    setJudge(config)
    setShowJudgeSelector(false)
  }

  const removeDebater = (configId) => {
    setDebaters(debaters.filter(c => c._id !== configId))
  }

  const handleStart = () => {
    if (!topic.trim() || debaters.length < 2 || !judge) return
    onStart({
      topic: topic.trim(),
      config_ids: debaters.map(d => d._id),
      judge_config_id: judge._id,
      rounds,
      thinking_type: thinkingType,
      response_length: responseLength,
      debaters,
      judge,
    })
  }

  const canStart = topic.trim() && debaters.length >= 2 && judge && !isStarting

  return (
    <Fragment>
    <Card className="space-y-6 p-5 md:p-6">
      {/* Topic Input */}
      <div className="space-y-2">
        <Label htmlFor="topic">{t('setup.topic')}</Label>
        <Input
          id="topic"
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={t('setup.topicPlaceholder')}
          className={containsRTL(topic) ? 'font-persian' : ''}
          dir={getTextDirection(topic) || 'auto'}
          disabled={isStarting}
        />
      </div>

      {/* Debate Settings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Thinking Type */}
        <div className="space-y-2">
          <Label className="flex items-center gap-2">
            <Brain className="h-4 w-4" />
            {t('setup.thinkingType')}
          </Label>
          <div className="flex flex-col sm:flex-row gap-2">
            {[
              { value: 'logical', label: `🧮 ${t('setup.logical')}` },
              { value: 'balanced', label: `⚖️ ${t('setup.balanced')}` },
              { value: 'feeling', label: `💭 ${t('setup.feeling')}` },
            ].map(({ value, label }) => (
              <Button
                key={value}
                type="button"
                variant={thinkingType === value ? 'default' : 'secondary'}
                onClick={() => setThinkingType(value)}
                disabled={isStarting}
                className="flex-1"
              >
                {label}
              </Button>
            ))}
          </div>
          <p className="text-xs text-foreground-tertiary">
            {thinkingType === 'logical' && t('setup.logicalDesc')}
            {thinkingType === 'feeling' && t('setup.feelingDesc')}
            {thinkingType === 'balanced' && t('setup.balancedDesc')}
          </p>
        </div>

        {/* Response Length */}
        <div className="space-y-2">
          <Label className="flex items-center gap-2">
            <Zap className="h-4 w-4" />
            {t('setup.responseLength')}
          </Label>
          <div className="flex flex-col sm:flex-row gap-2">
            {[
              { value: 'short', label: `📝 ${t('setup.short')}` },
              { value: 'balanced', label: `⚖️ ${t('setup.balanced')}` },
              { value: 'long', label: `📜 ${t('setup.long')}` },
            ].map(({ value, label }) => (
              <Button
                key={value}
                type="button"
                variant={responseLength === value ? 'default' : 'secondary'}
                onClick={() => setResponseLength(value)}
                disabled={isStarting}
                className="flex-1"
              >
                {label}
              </Button>
            ))}
          </div>
          <p className="text-xs text-foreground-tertiary">
            {responseLength === 'short' && t('setup.shortDesc')}
            {responseLength === 'balanced' && t('setup.balancedLengthDesc')}
            {responseLength === 'long' && t('setup.longDesc')}
          </p>
        </div>
      </div>

      {/* Quick Models */}
      <div className="space-y-2">
        <Label>{t('setup.quickAddModels')}</Label>
        <div className="flex flex-wrap gap-2">
          {DEFAULT_MODELS.map(model => {
            const isAdded = debaters.some(d => d._id === `quick:${model.id}`)
            return (
              <Button
                key={model.id}
                variant={isAdded ? 'default' : 'secondary'}
                size="sm"
                onClick={() => addQuickDebater(model)}
                disabled={isStarting || debaters.length >= 5 || isAdded}
                className="gap-2"
              >
                <ModelLogo logo={model.logo} modelId={model.id} size={14} />
                <span>{model.name}</span>
                {isAdded && <Check className="h-3 w-3" />}
              </Button>
            )
          })}
        </div>
      </div>

      {/* Debaters Selection */}
      <div className="space-y-2">
        <Label className="flex items-center gap-2">
          <Users className="h-4 w-4" />
          {t('setup.debatersCount', { count: debaters.length })}
        </Label>
        <div className="flex flex-wrap gap-2">
          {debaters.map(config => (
            <Badge
              key={config._id}
              variant="secondary"
              className="px-3 py-1.5 h-auto gap-2"
            >
              {config.avatar?.type === 'logo' || config.model_id ? (
                <ModelLogo logo={config.avatar?.type === 'logo' ? config.avatar.value : undefined} modelId={config.model_id} size={14} />
              ) : (
                <span>{config.avatar?.value || '🤖'}</span>
              )}
              <span>{config.name}</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => removeDebater(config._id)}
                disabled={isStarting}
                className="h-4 w-4 p-0 hover:bg-transparent"
              >
                <X className="h-3 w-3" />
              </Button>
            </Badge>
          ))}
          {debaters.length < 5 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowDebaterSelector(true)}
              disabled={isStarting}
              className="border-dashed gap-2"
            >
              <Plus className="h-4 w-4" />
              {t('setup.addDebater')}
            </Button>
          )}
        </div>
        {debaters.length < 2 && (
          <p className="text-xs text-foreground-tertiary">
            {t('setup.selectAtLeast2')}
          </p>
        )}
      </div>

      {/* Judge Selection */}
      <div className="space-y-2">
        <Label className="flex items-center gap-2">
          <Gavel className="h-4 w-4" />
          {t('setup.judge')}
        </Label>
        {!judge && (
          <div className="flex flex-wrap gap-2 mb-3">
            {DEFAULT_MODELS.map(model => (
              <Button
                key={model.id}
                variant="secondary"
                size="sm"
                onClick={() => setQuickJudge(model)}
                disabled={isStarting}
                className="gap-2"
              >
                <ModelLogo logo={model.logo} modelId={model.id} size={14} />
                <span>{model.name}</span>
              </Button>
            ))}
          </div>
        )}
        {judge ? (
          <div className="flex items-center gap-2">
            <Badge variant="accent" className="px-3 py-1.5 h-auto gap-2">
              {judge.avatar?.type === 'logo' || judge.model_id ? (
                <ModelLogo logo={judge.avatar?.type === 'logo' ? judge.avatar.value : undefined} modelId={judge.model_id} size={14} />
              ) : (
                <span>{judge.avatar?.value || '⚖️'}</span>
              )}
              <span>{judge.name}</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setJudge(null)}
                disabled={isStarting}
                className="h-4 w-4 p-0 hover:bg-transparent"
              >
                <X className="h-3 w-3" />
              </Button>
            </Badge>
            <Button
              variant="link"
              size="sm"
              onClick={() => setShowJudgeSelector(true)}
              disabled={isStarting}
              className="text-accent"
            >
              {t('setup.change')}
            </Button>
          </div>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowJudgeSelector(true)}
            disabled={isStarting}
            className="border-dashed gap-2"
          >
            <Plus className="h-4 w-4" />
            {t('setup.selectJudge')}
          </Button>
        )}
      </div>

      {/* Rounds Selection */}
      <div className="space-y-2">
        <Label>
          {rounds === 0 ? t('setup.roundsInfinite') : t('setup.rounds', { count: rounds })}
        </Label>
        <div className="flex flex-wrap gap-2">
          {[0, 1, 2, 3, 4, 5].map((value) => (
            <Button
              key={value}
              variant={rounds === value ? 'default' : 'secondary'}
              size="sm"
              onClick={() => setRounds(value)}
              disabled={isStarting}
            >
              {value === 0 ? t('setup.infinite') : value}
            </Button>
          ))}
        </div>
        {rounds === 0 && (
          <p className="text-xs text-foreground-tertiary">
            {t('setup.infiniteRoundsDesc')}
          </p>
        )}
      </div>

      {/* Start Button */}
      <Button
        onClick={handleStart}
        disabled={!canStart}
        size="lg"
        className="w-full"
      >
        {isStarting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin me-2" />
            {t('startingDebate')}
          </>
        ) : (
          <>
            <Play className="h-4 w-4 me-2" />
            {t('startDebate')}
          </>
        )}
      </Button>
    </Card>

      {/* Debater Selector Modal */}
      <ConfigSelectorModal
        isOpen={showDebaterSelector}
        title={t('setup.selectDebaters')}
        description={t('setup.selectDebatersDesc', { count: debaters.length })}
        configs={configs}
        selected={debaters}
        onToggle={toggleDebater}
        onClose={() => setShowDebaterSelector(false)}
        maxSelect={5}
        isLoading={configsLoading}
        excludeIds={judge ? [judge._id] : []}
        doneLabel={t('setup.done')}
        cancelLabel={t('setup.cancel')}
        emptyLabel={t('setup.noConfigs')}
        inUseLabel={t('setup.inUse')}
      />

      {/* Judge Selector Modal */}
      <ConfigSelectorModal
        isOpen={showJudgeSelector}
        title={t('setup.selectJudgeTitle')}
        description={t('setup.selectJudgeDesc')}
        configs={configs}
        selected={judge ? [judge] : []}
        onToggle={selectJudge}
        onClose={() => setShowJudgeSelector(false)}
        maxSelect={1}
        singleSelect
        isLoading={configsLoading}
        excludeIds={debaters.map(d => d._id)}
        doneLabel={t('setup.done')}
        cancelLabel={t('setup.cancel')}
        emptyLabel={t('setup.noConfigs')}
        inUseLabel={t('setup.inUse')}
      />
    </Fragment>
  )
}

function ConfigSelectorModal({
  isOpen,
  title,
  description,
  configs,
  selected,
  onToggle,
  onClose,
  maxSelect,
  singleSelect = false,
  isLoading,
  excludeIds = [],
  doneLabel,
  cancelLabel,
  emptyLabel,
  inUseLabel,
}) {
  const selectedIds = selected.map(c => c._id)

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        {/* Config List */}
        <div className="flex-1 overflow-y-auto space-y-2 py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-accent" />
            </div>
          ) : configs.length === 0 ? (
            <p className="text-center text-foreground-secondary py-8">{emptyLabel}</p>
          ) : (
            configs.map((config) => {
              const isSelected = selectedIds.includes(config._id)
              const isExcluded = excludeIds.includes(config._id)
              const isDisabled = isExcluded || (!singleSelect && !isSelected && selected.length >= maxSelect)

              return (
                <button
                  key={config._id}
                  type="button"
                  onClick={() => !isDisabled && onToggle(config)}
                  disabled={isDisabled}
                  className={cn(
                    'w-full flex items-center gap-3 p-3 rounded-[10px] transition-colors text-start',
                    isSelected
                      ? 'bg-accent/10 ring-1 ring-inset ring-accent/40'
                      : 'bg-background-tertiary ring-1 ring-inset ring-transparent hover:ring-border',
                    isDisabled && 'opacity-50 cursor-not-allowed'
                  )}
                >
                  <Avatar shape="square">
                    <AvatarFallback className="text-xl">
                      {config.avatar?.value || '🤖'}
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-foreground truncate">{config.name}</p>
                    <p className="text-xs text-foreground-tertiary truncate">
                      {config.model_name || prettifyModelName(config.model_id)}
                    </p>
                  </div>
                  {isSelected && (
                    <Badge variant="accent" className="h-5 px-1.5">
                      <Check className="h-3 w-3" />
                    </Badge>
                  )}
                  {isExcluded && !isSelected && (
                    <Badge variant="secondary" className="text-xs">{inUseLabel}</Badge>
                  )}
                </button>
              )
            })
          )}
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            {singleSelect ? cancelLabel : doneLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

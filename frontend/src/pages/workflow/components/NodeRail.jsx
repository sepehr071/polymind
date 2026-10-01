import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Type,
  Upload,
  Bot,
  Sparkles,
  Volume2,
  Video,
  Search,
  Users,
  FileSearch,
  Hash,
  Target,
  Boxes,
  Brackets,
  Code2,
  GitBranch,
  Webhook,
  Clock,
  Activity,
  Globe,
  LayoutGrid,
  Megaphone,
  TerminalSquare,
  Zap,
} from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { cn } from '../../../utils/cn';

const CATEGORY_ORDER = ['INPUT', 'AI', 'GEN', 'MARKETING', 'DEV', 'AUTOMATION'];

// Canonical icon-button sizing for the narrow chrome rail (40px square,
// radius 9, standard focus ring via the Button primitive).
const RAIL_ICON_BTN = 'h-10 w-10 rounded-[9px]';

const NODE_ICON_MAP = {
  textInput: Type,
  imageUpload: Upload,
  aiAgent: Bot,
  ttsNode: Volume2,
  imageGen: Sparkles,
  videoGenNode: Video,
  personaBuilderNode: Users,
  seoBriefNode: FileSearch,
  hashtagPackNode: Hash,
  audienceMatchNode: Target,
  apiCallNode: Boxes,
  jsonTransformNode: Brackets,
  codeRunnerNode: Code2,
  gitActionNode: GitBranch,
  webhookTriggerNode: Webhook,
  cronScheduleNode: Clock,
  branchConditionNode: Activity,
  httpRequestNode: Globe,
};

const NODE_HOTKEYS = {
  textInput: 'T',
  imageUpload: 'I',
  aiAgent: 'A',
  ttsNode: 'S',
  imageGen: 'G',
  videoGenNode: 'V',
  personaBuilderNode: 'P',
  seoBriefNode: 'O',
  hashtagPackNode: 'H',
  audienceMatchNode: 'M',
  apiCallNode: 'shift+a',
  jsonTransformNode: 'J',
  codeRunnerNode: 'C',
  gitActionNode: 'shift+g',
  webhookTriggerNode: 'W',
  cronScheduleNode: 'shift+c',
  branchConditionNode: 'B',
  httpRequestNode: 'R',
};

const NODE_CATEGORIES = {
  textInput: 'INPUT',
  imageUpload: 'INPUT',
  aiAgent: 'AI',
  ttsNode: 'AI',
  imageGen: 'GEN',
  videoGenNode: 'GEN',
  personaBuilderNode: 'MARKETING',
  seoBriefNode: 'MARKETING',
  hashtagPackNode: 'MARKETING',
  audienceMatchNode: 'MARKETING',
  apiCallNode: 'DEV',
  jsonTransformNode: 'DEV',
  codeRunnerNode: 'DEV',
  gitActionNode: 'DEV',
  webhookTriggerNode: 'AUTOMATION',
  cronScheduleNode: 'AUTOMATION',
  branchConditionNode: 'AUTOMATION',
  httpRequestNode: 'AUTOMATION',
};

const TABS = [
  { key: 'ALL', icon: LayoutGrid, cats: ['INPUT', 'AI', 'GEN'] },
  { key: 'MARKETING', icon: Megaphone, cats: ['MARKETING'] },
  { key: 'DEV', icon: TerminalSquare, cats: ['DEV'] },
  { key: 'AUTOMATION', icon: Zap, cats: ['AUTOMATION'] },
];

function RailNodeButton({ type, icon: Icon, label, hotkey, description, onAddNode }) {
  const { t } = useTranslation('workflow');
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData('application/reactflow', type);
            e.dataTransfer.effectAllowed = 'move';
          }}
          onClick={() => onAddNode(type)}
          className={RAIL_ICON_BTN}
          aria-label={t('nodeRail.addNode', { label })}
        >
          <Icon className="w-4 h-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-[160px]">
        <div className="font-medium">{label} · {hotkey}</div>
        <div className="text-[10px] text-foreground-secondary mt-0.5">{description}</div>
      </TooltipContent>
    </Tooltip>
  );
}

function TabButton({ tabKey, icon: Icon, active, onClick, label }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClick}
          aria-pressed={active}
          aria-label={label}
          className={cn(
            'h-8 w-9 rounded-[9px]',
            active
              ? 'bg-accent/10 text-accent ring-1 ring-inset ring-accent/30'
              : 'text-foreground-tertiary'
          )}
        >
          <Icon className="w-[14px] h-[14px]" />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

export default function NodeRail({ onAddNode, onToggleAIGenerator }) {
  const { t } = useTranslation('workflow');
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('ALL');

  const NODE_TYPES = useMemo(
    () =>
      Object.keys(NODE_ICON_MAP).map((type) => ({
        type,
        icon: NODE_ICON_MAP[type],
        label: t(`nodeRail.nodes.${type}.label`),
        hotkey: NODE_HOTKEYS[type],
        category: NODE_CATEGORIES[type],
        description: t(`nodeRail.nodes.${type}.description`),
      })),
    [t]
  );

  const activeCats = TABS.find((tab) => tab.key === activeTab).cats;
  const showCategoryHeaders = activeCats.length > 1;

  return (
    <div className="w-14 shrink-0 flex flex-col items-center py-2 gap-1 bg-background-secondary border-e border-border">
      {/* Search */}
      <Popover open={searchOpen} onOpenChange={setSearchOpen}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(RAIL_ICON_BTN, searchOpen && 'bg-background-tertiary text-foreground')}
                aria-label={t('nodeRail.searchNodes')}
              >
                <Search className="w-4 h-4" />
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="right">{t('nodeRail.searchNodes')}</TooltipContent>
        </Tooltip>
        <PopoverContent side="right" align="start" className="w-64 p-0">
          <Command>
            <CommandInput placeholder={t('nodeRail.searchPlaceholder')} />
            <CommandList>
              <CommandEmpty>{t('nodeRail.noNodesFound')}</CommandEmpty>
              {CATEGORY_ORDER.map((cat) => (
                <CommandGroup key={cat} heading={t(`nodeRail.categories.${cat}`)}>
                  {NODE_TYPES.filter((n) => n.category === cat).map(
                    ({ type, icon: Icon, label, hotkey, description }) => (
                      <CommandItem
                        key={type}
                        value={`${label} ${description}`}
                        onSelect={() => {
                          onAddNode(type);
                          setSearchOpen(false);
                        }}
                        className="cursor-pointer"
                      >
                        <Icon className="w-3.5 h-3.5 shrink-0" />
                        <span className="flex-1 truncate">{label}</span>
                        <span className="text-[10px] text-foreground-tertiary ms-2 shrink-0">{hotkey}</span>
                      </CommandItem>
                    )
                  )}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      <div className="w-8 h-px my-0.5 bg-border" />

      {/* Team tabs */}
      <div className="flex flex-col items-center gap-0.5" role="tablist" aria-label={t('nodeRail.tabsLabel')}>
        {TABS.map((tab) => (
          <TabButton
            key={tab.key}
            tabKey={tab.key}
            icon={tab.icon}
            active={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
            label={t(`nodeRail.tabs.${tab.key.toLowerCase()}`)}
          />
        ))}
      </div>

      <div className="w-8 h-px my-0.5 bg-border" />

      {/* Filtered node list — scrolls if overflow */}
      <div className="flex-1 min-h-0 w-full overflow-y-auto scrollbar-none flex flex-col items-center gap-0.5 px-0.5">
        {activeCats.map((cat) => {
          const nodes = NODE_TYPES.filter((n) => n.category === cat);
          if (nodes.length === 0) return null;
          return (
            <div key={cat} className="flex flex-col items-center w-full gap-0.5">
              {showCategoryHeaders && (
                <div className="max-w-full truncate px-0.5 text-[9px] text-foreground-tertiary font-medium mt-1 mb-0.5 select-none">
                  {t(`nodeRail.categories.${cat}`)}
                </div>
              )}
              {nodes.map((node) => (
                <RailNodeButton key={node.type} {...node} onAddNode={onAddNode} />
              ))}
            </div>
          );
        })}
      </div>

      <div className="w-8 h-px my-0.5 bg-border" />

      {/* AI Generate */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onToggleAIGenerator(true)}
            className={cn(RAIL_ICON_BTN, 'text-accent hover:bg-accent/10 hover:text-accent')}
            aria-label={t('nodeRail.generateWithAI')}
          >
            <Sparkles className="w-4 h-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-[160px]">
          <div className="font-medium">{t('nodeRail.generateWithAI')}</div>
          <div className="text-[10px] text-foreground-secondary mt-0.5">{t('nodeRail.generateDescription')}</div>
        </TooltipContent>
      </Tooltip>
    </div>
  );
}

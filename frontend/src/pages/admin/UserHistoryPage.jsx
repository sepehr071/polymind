import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  MessageSquare,
  Calendar,
  Clock,
  User,
  Bot,
  ChevronRight,
  Loader2,
  History,
} from 'lucide-react'
import { adminService } from '../../services/adminService'
import { fmtDate } from '../../utils/dateLocale'
import { fmtNumber } from '@/utils/persianLocale'
import { prettifyModelName } from '@/utils/modelName'
import { cn } from '../../utils/cn'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import UsagePanel from './components/UsagePanel'
import PageShell from '@/components/layout/PageShell'
import PageHeader from '@/components/layout/PageHeader'

export default function UserHistoryPage() {
  const { t } = useTranslation('admin')
  const { userId } = useParams()
  const navigate = useNavigate()
  const [expandedConversation, setExpandedConversation] = useState(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-user-history', userId],
    queryFn: () => adminService.getUserHistory(userId, false),
  })

  const conversations = data?.conversations || []
  const userInfo = data?.user || {}

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-6">
        <p className="text-error mb-4">{t('userHistory.failedLoad')}</p>
        <Button variant="secondary" onClick={() => navigate('/admin/users')}>
          <ArrowLeft className="h-4 w-4 me-2 rtl:rotate-180" />
          {t('userHistory.backToUsers')}
        </Button>
      </div>
    )
  }

  return (
    <PageShell width="standard">
        {/* Header */}
        <PageHeader
          icon={History}
          tone="sky"
          title={t('userHistory.title')}
          subtitle={userInfo.display_name || userInfo.email || t('users.unknown')}
          backTo="/admin/users"
          backLabel={t('userHistory.backToUsers')}
        />

        {/* User Info Card */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-4">
              <Avatar size="lg">
                <AvatarFallback seed={userInfo.display_name || userInfo.email} className="text-lg">
                  {userInfo.display_name?.[0]?.toUpperCase() || userInfo.email?.[0]?.toUpperCase() || 'U'}
                </AvatarFallback>
              </Avatar>
              <div>
                <p className="font-medium text-foreground">{userInfo.display_name || t('users.noName')}</p>
                <p className="text-sm text-foreground-secondary">{userInfo.email}</p>
              </div>
              <div className="ms-auto text-end">
                <p className="text-sm text-foreground-secondary">{t('userHistory.totalConversations')}</p>
                <p className="text-xl font-bold text-foreground tabular-nums">{fmtNumber(conversations.length)}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Per-user usage drilldown (cost / tokens / requests from usage_logs) */}
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-foreground">{t('userHistory.usageTitle')}</h2>
          <UsagePanel userId={userId} />
        </section>

        {/* Conversations List */}
        {conversations.length === 0 ? (
          <div className="text-center py-12">
            <MessageSquare className="h-12 w-12 text-foreground-tertiary mx-auto mb-3" />
            <h3 className="text-lg font-medium text-foreground mb-1">{t('userHistory.noConversations')}</h3>
            <p className="text-foreground-secondary">{t('userHistory.noConversationsDesc')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {conversations.map((conversation) => (
              <ConversationItem
                key={conversation._id}
                userId={userId}
                conversation={conversation}
                isExpanded={expandedConversation === conversation._id}
                onToggle={() =>
                  setExpandedConversation(
                    expandedConversation === conversation._id ? null : conversation._id
                  )
                }
              />
            ))}
          </div>
        )}
    </PageShell>
  )
}

function ConversationItem({ userId, conversation, isExpanded, onToggle }) {
  const { t } = useTranslation('admin')

  const {
    data: messagesData,
    isLoading: messagesLoading,
    error: messagesError,
  } = useQuery({
    queryKey: ['admin-conv-msgs', conversation._id],
    queryFn: () => adminService.getUserHistoryMessages(userId, conversation._id),
    enabled: isExpanded,
    staleTime: 5 * 60_000,
  })

  const messages = messagesData?.messages || []

  return (
    <Card className="p-0 overflow-hidden">
      <Collapsible open={isExpanded} onOpenChange={onToggle}>
        {/* Conversation Header */}
        <CollapsibleTrigger asChild>
          <button className="w-full flex items-center gap-3 p-4 hover:bg-background-tertiary/50 transition-colors">
            <div className={cn(
              'transition-transform',
              isExpanded && 'rotate-90'
            )}>
              <ChevronRight className="h-5 w-5 text-foreground-tertiary rtl:rotate-180" />
            </div>
            <MessageSquare className="h-5 w-5 text-accent" />
            <div className="flex-1 text-start">
              <p className="font-medium text-foreground">
                {conversation.title || t('userHistory.untitled')}
              </p>
              <div className="flex items-center gap-3 text-xs text-foreground-tertiary mt-1 flex-wrap">
                <Badge variant="secondary" className="gap-1 tabular-nums">
                  <MessageSquare className="h-3 w-3" />
                  {fmtNumber(conversation.message_count || 0)}
                </Badge>
                <span className="flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {fmtDate(new Date(conversation.created_at), 'MMM d, yyyy')}
                </span>
                {conversation.last_message_at && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {t('userHistory.lastMessage', { time: fmtDate(new Date(conversation.last_message_at), 'MMM d, h:mm a') })}
                  </span>
                )}
              </div>
            </div>
            {conversation.token_count && (
              <Badge variant="outline" className="ms-auto tabular-nums">
                {t('users.tokens', { count: fmtNumber(conversation.token_count.total ?? 0) })}
              </Badge>
            )}
          </button>
        </CollapsibleTrigger>

        {/* Expanded Messages (lazily fetched on expand) */}
        <CollapsibleContent>
          <div className="border-t border-border bg-background-tertiary/30">
            <div className="max-h-96 overflow-y-auto p-4 space-y-4">
              {messagesLoading ? (
                <div className="flex items-center justify-center gap-2 py-6 text-foreground-tertiary">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm">{t('userHistory.loadingMessages')}</span>
                </div>
              ) : messagesError ? (
                <p className="text-center text-error py-4">{t('userHistory.failedMessages')}</p>
              ) : messages.length === 0 ? (
                <p className="text-center text-foreground-tertiary py-4">{t('userHistory.noMessages')}</p>
              ) : (
                messages.map((message, index) => (
                  <MessageItem key={message._id || index} message={message} />
                ))
              )}
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

function MessageItem({ message }) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'

  return (
    <div className={cn(
      'flex gap-3',
      isUser && 'flex-row-reverse'
    )}>
      <Avatar className="h-8 w-8 flex-shrink-0">
        <AvatarFallback className={cn(
          isUser ? 'bg-accent text-accent-foreground' : isSystem ? 'bg-warning/20 text-warning' : 'bg-background-elevated text-accent'
        )}>
          {isUser ? (
            <User className="h-4 w-4" />
          ) : isSystem ? (
            <span className="text-xs font-medium">S</span>
          ) : (
            <Bot className="h-4 w-4" />
          )}
        </AvatarFallback>
      </Avatar>
      <div className={cn(
        'flex-1 max-w-[80%]',
        isUser && 'text-end'
      )}>
        <div className={cn(
          'inline-block p-3 rounded-lg text-sm',
          isUser
            ? 'bg-accent text-accent-foreground'
            : isSystem
            ? 'bg-warning/10 text-foreground border border-warning/20'
            : 'bg-background-elevated text-foreground'
        )}>
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-foreground-tertiary mt-1 flex-wrap">
          {message.created_at && (
            <span>{fmtDate(new Date(message.created_at), 'h:mm a')}</span>
          )}
          {message.metadata?.model_id && (
            <Badge variant="outline" className="text-xs py-0">
              {prettifyModelName(message.metadata.model_id)}
            </Badge>
          )}
        </div>
      </div>
    </div>
  )
}

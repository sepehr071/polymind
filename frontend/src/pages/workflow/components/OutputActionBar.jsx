import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check, Download, BookmarkPlus, MessageSquarePlus, Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/button';
import { knowledgeService } from '@/services/knowledgeService';
import { chatService, configService } from '@/services/chatService';
import { useProject } from '@/context/ProjectContext';
import { useWorkspace } from '@/context/WorkspaceContext';

const FALLBACK_QUICK_CONFIG_ID = 'quick:google/gemini-3.5-flash-lite';

/**
 * Unified output action bar for workflow node inspectors.
 *
 * Props:
 *   outputType  - 'text' | 'image' | 'audio' | 'video'
 *   text        - string content (text outputs)
 *   url         - string URL (image / video outputs)
 *   audioDataUri - string data URI (audio outputs)
 *   filename    - suggested download filename
 *   knowledgeTitle - hint for the knowledge item title (default: 'Workflow output')
 *
 * Decisions:
 *   - "Open in Chat": uses chatService.createConversation() (no config — passes null
 *     which the backend treats as a default/no-config conversation), then navigates to
 *     /chat/:id. Because the conversation create endpoint does not accept an initial
 *     message body, the text output is stored in sessionStorage under the key
 *     `chat_prefill_<conversationId>` so the ChatPage can pick it up and pre-populate
 *     the input box on first load (compose pattern). For non-text outputs the URL/URI
 *     is pre-populated instead so the user can paste or attach it themselves.
 *   - "Save to Knowledge": uses source_type='workflow'. project_id auto-attached from
 *     active project context when available.
 */
export default function OutputActionBar({
  outputType = 'text',
  text,
  url,
  audioDataUri,
  filename = 'workflow-output',
  knowledgeTitle = 'Workflow output',
  workflowId = null,
  nodeId = null,
}) {
  const { t } = useTranslation('workflow');
  const navigate = useNavigate();
  const { currentProject } = useProject();
  const { currentWorkspace } = useWorkspace();

  const [copied, setCopied] = useState(false);
  const [savingKnowledge, setSavingKnowledge] = useState(false);
  const [openingChat, setOpeningChat] = useState(false);

  // Resolve the content string regardless of type (used for clipboard + knowledge + chat)
  const contentForText = outputType === 'text' ? (text || '') : (url || audioDataUri || '');

  // For non-text outputs, the knowledge entry is a small pointer record —
  // the asset itself lives in generated_images / generated_audios / generated_videos.
  // Inline data URIs would exceed the backend's 50k-char content cap.
  const knowledgeContent = outputType === 'text'
    ? (text || '')
    : outputType === 'image' && url
      ? `[Image] ${url.startsWith('data:') ? '(inline data — see workflow run)' : url}`
      : outputType === 'video' && url
        ? `[Video] ${url}`
        : outputType === 'audio' && audioDataUri
          ? `[Audio] (inline data — see workflow run)`
          : '';

  const handleCopy = useCallback(() => {
    const content = outputType === 'audio' ? audioDataUri : (text || url || '');
    if (!content) return;
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {
      toast.error(t('outputActionBar.errorCopy'));
    });
  }, [outputType, text, url, audioDataUri]);

  const handleDownload = useCallback(async () => {
    const href = outputType === 'audio' ? audioDataUri : url;
    if (!href) return;
    try {
      // For data URIs and same-origin URLs, fetch into a Blob so Firefox/Safari
      // honor the `download` attribute reliably (cross-origin data URIs are
      // blocked by Firefox on direct anchor clicks).
      const isDataUri = href.startsWith('data:');
      let blobUrl;
      if (isDataUri) {
        const res = await fetch(href);
        const blob = await res.blob();
        blobUrl = URL.createObjectURL(blob);
      } else {
        blobUrl = href;
      }
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      if (isDataUri) {
        // Defer revoke so click can complete
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      }
    } catch (err) {
      toast.error(t('outputActionBar.errorDownload'));
    }
  }, [outputType, url, audioDataUri, filename, t]);

  const handleSaveToKnowledge = useCallback(async () => {
    if (!knowledgeContent) {
      toast.error(t('outputActionBar.errorNoContent'));
      return;
    }
    if (!workflowId) {
      toast.error(t('outputActionBar.errorSaveFirst'));
      return;
    }
    if (!nodeId) {
      toast.error(t('outputActionBar.errorNodeId'));
      return;
    }
    setSavingKnowledge(true);
    try {
      const payload = {
        source_type: 'workflow',
        workflow_id: workflowId,
        node_id: nodeId,
        content: knowledgeContent,
        title: knowledgeTitle,
        tags: ['workflow'],
      };
      if (currentProject?._id) {
        payload.project_id = currentProject._id;
      }
      if (currentWorkspace?._id) {
        payload.workspace_id = currentWorkspace._id;
      }
      await knowledgeService.create(payload);
      toast.success(t('outputActionBar.successSave'));
    } catch (err) {
      toast.error(err?.response?.data?.error || t('outputActionBar.errorSave'));
    } finally {
      setSavingKnowledge(false);
    }
  }, [knowledgeContent, knowledgeTitle, currentProject, currentWorkspace, workflowId, nodeId, t]);

  const handleOpenInChat = useCallback(async () => {
    const prefill = contentForText;
    if (!prefill) {
      toast.error(t('outputActionBar.errorNoContent'));
      return;
    }
    setOpeningChat(true);
    try {
      // Resolve a usable config_id: backend rejects null. Try user's first
      // saved config; fall back to a quick-model id (config_resolver handles it).
      let configId = FALLBACK_QUICK_CONFIG_ID;
      try {
        const params = currentProject?._id ? { project_id: currentProject._id } : undefined;
        const res = await configService.getConfigs(params);
        const list = res?.configs || [];
        if (list.length > 0 && list[0]._id) {
          configId = list[0]._id;
        }
      } catch {
        // Ignore — fall back to quick model id.
      }

      const conversation = await chatService.createConversation(configId, 'Workflow output');
      const conversationId = conversation?.conversation?._id
        || conversation?.conversation?.id
        || conversation?._id
        || conversation?.id;
      if (!conversationId) {
        throw new Error(t('outputActionBar.errorNoConversationId'));
      }

      sessionStorage.setItem(`chat_prefill_${conversationId}`, prefill);
      navigate(`/chat/${conversationId}`);
    } catch (err) {
      toast.error(err?.response?.data?.error || err?.message || t('outputActionBar.errorChat'));
    } finally {
      setOpeningChat(false);
    }
  }, [contentForText, navigate, currentProject, t]);

  const isText = outputType === 'text';
  const isImage = outputType === 'image';
  const isAudio = outputType === 'audio';
  const isVideo = outputType === 'video';

  const hasContent = isText ? !!text : isAudio ? !!audioDataUri : !!url;

  if (!hasContent) return null;

  return (
    <div className="border-t border-border pt-3 mt-3 flex flex-wrap gap-2">
      {/* Copy — text only */}
      {isText && (
        <Button
          variant="outline"
          size="sm"
          onClick={handleCopy}
          className="flex-1 min-w-[80px]"
          title={t('outputActionBar.copy')}
        >
          {copied ? (
            <><Check className="h-3.5 w-3.5 me-1.5 text-success" />{t('outputActionBar.copied')}</>
          ) : (
            <><Copy className="h-3.5 w-3.5 me-1.5" />{t('outputActionBar.copy')}</>
          )}
        </Button>
      )}

      {/* Download — image / audio / video */}
      {(isImage || isAudio || isVideo) && (
        <Button
          variant="outline"
          size="sm"
          onClick={handleDownload}
          className="flex-1 min-w-[100px]"
          title={t('outputActionBar.download')}
        >
          <Download className="h-3.5 w-3.5 me-1.5" />
          {t('outputActionBar.download')}
        </Button>
      )}

      {/* Save to Knowledge */}
      <Button
        variant="outline"
        size="sm"
        onClick={handleSaveToKnowledge}
        disabled={savingKnowledge}
        className="flex-1 min-w-[80px]"
        title={t('outputActionBar.save')}
      >
        {savingKnowledge ? (
          <><Loader2 className="h-3.5 w-3.5 me-1.5 animate-spin" />{t('outputActionBar.saving')}</>
        ) : (
          <><BookmarkPlus className="h-3.5 w-3.5 me-1.5" />{t('outputActionBar.save')}</>
        )}
      </Button>

      {/* Open in Chat */}
      <Button
        variant="outline"
        size="sm"
        onClick={handleOpenInChat}
        disabled={openingChat}
        className="flex-1 min-w-[80px]"
        title={t('outputActionBar.chat')}
      >
        {openingChat ? (
          <><Loader2 className="h-3.5 w-3.5 me-1.5 animate-spin" />{t('outputActionBar.opening')}</>
        ) : (
          <><MessageSquarePlus className="h-3.5 w-3.5 me-1.5" />{t('outputActionBar.chat')}</>
        )}
      </Button>
    </div>
  );
}

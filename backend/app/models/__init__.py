# Models package.
# Import every model module here so all ORM classes register on
# db.metadata at import time. Alembic autogenerate only sees tables whose
# modules have been imported — an incomplete list silently drops tables
# from generated migrations (e.g. login_attempt_log).
from app.models.arena_message import ArenaMessageModel
from app.models.arena_session import ArenaSessionModel
from app.models.audit_log import AuditLogModel
from app.models.automate_message import AutomateMessageModel
from app.models.automate_task import AutomateTaskModel
from app.models.budget_allocation import BudgetAllocationModel
from app.models.conversation import ConversationModel
from app.models.conversation_share import ConversationShareModel
from app.models.credit_ledger import CreditLedgerModel
from app.models.debate_message import DebateMessageModel
from app.models.debate_session import DebateSessionModel
from app.models.dlp_event import DLPEventModel
from app.models.folder import FolderModel
from app.models.generated_audio import GeneratedAudioModel
from app.models.generated_image import GeneratedImageModel, ImageConversationModel
from app.models.generated_video import GeneratedVideoModel
from app.models.group import GroupModel
from app.models.group_member import GroupMemberModel
from app.models.helper_conversation import HelperConversationModel
from app.models.knowledge_folder import KnowledgeFolderModel
from app.models.knowledge_item import KnowledgeItemModel
from app.models.llm_config import LLMConfigModel
from app.models.login_attempt import LoginAttemptModel
from app.models.meeting import MeetingModel
from app.models.meeting_series import MeetingSeriesModel
from app.models.meeting_summary import MeetingSummaryModel
from app.models.meeting_transcript import MeetingTranscriptModel
from app.models.message import MessageModel
from app.models.ocr_job import OcrJob, OcrJobModel  # noqa: F401
from app.models.openrouter_model import OpenRouterModel
from app.models.platform_settings import PlatformSettingsModel
from app.models.presentation import Presentation, PresentationModel  # noqa: F401
from app.models.project import ProjectModel
from app.models.project_group_access import ProjectGroupAccessModel
from app.models.project_member import ProjectMemberModel
from app.models.project_webhook import ProjectWebhookModel
from app.models.prompt_template import PromptTemplateModel
from app.models.revoked_token import RevokedTokenModel
from app.models.spend_rollup import SpendRollupModel
from app.models.stream_state import StreamStateModel
from app.models.upload import UploadModel
from app.models.usage_log import UsageLogModel
from app.models.user import UserModel
from app.models.workflow import WorkflowModel
from app.models.workflow_run import WorkflowRunModel
from app.models.workspace import WorkspaceModel
from app.models.workspace_invite import WorkspaceInviteModel
from app.models.workspace_member import WorkspaceMemberModel

__all__ = [
    'ArenaMessageModel',
    'ArenaSessionModel',
    'AuditLogModel',
    'AutomateMessageModel',
    'AutomateTaskModel',
    'BudgetAllocationModel',
    'ConversationModel',
    'ConversationShareModel',
    'CreditLedgerModel',
    'DebateMessageModel',
    'DebateSessionModel',
    'DLPEventModel',
    'FolderModel',
    'GeneratedAudioModel',
    'GeneratedImageModel',
    'ImageConversationModel',
    'GeneratedVideoModel',
    'GroupModel',
    'GroupMemberModel',
    'HelperConversationModel',
    'KnowledgeFolderModel',
    'KnowledgeItemModel',
    'LLMConfigModel',
    'LoginAttemptModel',
    'MeetingModel',
    'MeetingSeriesModel',
    'MeetingSummaryModel',
    'MeetingTranscriptModel',
    'MessageModel',
    'OcrJobModel',
    'OpenRouterModel',
    'PlatformSettingsModel',
    'PresentationModel',
    'ProjectModel',
    'ProjectGroupAccessModel',
    'ProjectMemberModel',
    'ProjectWebhookModel',
    'PromptTemplateModel',
    'RevokedTokenModel',
    'SpendRollupModel',
    'StreamStateModel',
    'UploadModel',
    'UsageLogModel',
    'UserModel',
    'WorkflowModel',
    'WorkflowRunModel',
    'WorkspaceModel',
    'WorkspaceInviteModel',
    'WorkspaceMemberModel',
]

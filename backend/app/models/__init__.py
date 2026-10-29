"""Import every model so SQLAlchemy metadata is complete."""
# ruff: noqa: F401  (re-exports; __all__ is built dynamically below)
from app.models.ai import (
                           AIAgent,
                           AICall,
                           AIConversation,
                           AIMessage,
                           AIRun,
                           AISettings,
                           AITask,
                           AIToolCall,
                           Memory,
                           PromptTemplate,
                           ProviderSecret,
)
from app.models.base import Base
from app.models.brand import Brand, BrandAsset, BrandSettings, ContentPillar
from app.models.competitor import (
                           Competitor,
                           CompetitorPost,
                           CompetitorProfile,
                           CompetitorReport,
                           CompetitorSnapshot,
)
from app.models.content import (
                           Campaign,
                           ContentAsset,
                           ContentIdea,
                           ContentItem,
                           ContentSource,
                           ContentVariant,
                           ContentVersion,
                           Hashtag,
                           MediaAsset,
)
from app.models.identity import ApiKey, Invitation, RefreshSession, User, Workspace, WorkspaceMember
from app.models.platform import (
                           Approval,
                           AuditLog,
                           AutomationRun,
                           AutomationRunStep,
                           AutomationWorkflow,
                           EventOutbox,
                           Notification,
                           Report,
                           UsageBudget,
                           UsageLedger,
                           Webhook,
                           WorkflowEdge,
                           WorkflowNode,
)
from app.models.research import (
                           Keyword,
                           ResearchChunk,
                           ResearchDocument,
                           ResearchRun,
                           ResearchRunSource,
                           ResearchSource,
                           RssFeed,
                           Trend,
                           TrendSignal,
)
from app.models.scheduling import (
                           AccountMetric,
                           AnalyticsSnapshot,
                           Insight,
                           PostMetric,
                           PublishAttempt,
                           PublishedPost,
                           Recommendation,
                           RecurringSchedule,
                           ScheduledPost,
)
from app.models.social import OAuthState, OAuthToken, SocialAccount

__all__ = [n for n in dir() if not n.startswith("_")]

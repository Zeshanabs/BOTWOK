"""Pydantic output models for every agent action (doc 06 §6.3) + orchestrator schemas."""
from app.agents.schemas.analytics import Insight, Insights, Recommendation
from app.agents.schemas.common import AgentOutput, ClaimSource, GenericOutput, SourcedOutput, SourceRef
from app.agents.schemas.competitor import (
    CompetitorAnalysis,
    CompetitorComparison,
    CompetitorList,
    CompetitorRef,
    Gap,
    GapAnalysis,
)
from app.agents.schemas.content import ContentDraft, GenerationMetadata, Variant
from app.agents.schemas.critic import Critique, Issue, Scores
from app.agents.schemas.factcheck import Claim, Evidence, FactCheck
from app.agents.schemas.ideation import Idea, IdeaBatch
from app.agents.schemas.orchestrator import INTENTS, IntentResult, Plan, PlanTask, TaskBudget
from app.agents.schemas.report import Report, ReportSection
from app.agents.schemas.research import CrawlResult, KeyFinding, ResearchResult, SourceDetail
from app.agents.schemas.social import AudienceSignal, AvailabilityEntry, SocialListeningResult, SocialPostRef
from app.agents.schemas.strategy import (
    CalendarPlan,
    CalendarSlot,
    MixRecommendation,
    Opportunity,
    OpportunitySelection,
    Pillar,
    PlatformStrategy,
    Strategy,
)
from app.agents.schemas.trend import TrendExplanation, TrendItem, TrendSet
from app.agents.schemas.visual import VisualPlan

__all__ = [
    "INTENTS", "AgentOutput", "AudienceSignal", "AvailabilityEntry", "CalendarPlan", "CalendarSlot", "Claim", "ClaimSource",
    "CompetitorAnalysis", "CompetitorComparison", "CompetitorList", "CompetitorRef", "ContentDraft", "CrawlResult", "Critique",
    "Evidence", "FactCheck", "Gap", "GapAnalysis", "GenerationMetadata", "GenericOutput", "Idea", "IdeaBatch", "Insight",
    "Insights", "IntentResult", "Issue", "KeyFinding", "MixRecommendation", "Opportunity", "OpportunitySelection", "Pillar",
    "Plan", "PlanTask", "PlatformStrategy", "Recommendation", "Report", "ReportSection", "ResearchResult", "Scores",
    "SourceDetail", "SourceRef", "SourcedOutput", "SocialListeningResult", "SocialPostRef", "Strategy", "TaskBudget",
    "TrendExplanation", "TrendItem", "TrendSet", "Variant", "VisualPlan",
]

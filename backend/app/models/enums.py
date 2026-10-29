import enum


class Platform(enum.StrEnum):
    facebook = "facebook"
    instagram = "instagram"
    threads = "threads"
    linkedin = "linkedin"
    x = "x"
    tiktok = "tiktok"
    youtube = "youtube"
    pinterest = "pinterest"
    gbp = "gbp"


class MemberRole(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    approver = "approver"
    viewer = "viewer"


ROLE_RANK = {"viewer": 0, "approver": 1, "editor": 2, "admin": 3, "owner": 4}


class ContentStatus(enum.StrEnum):
    idea = "idea"
    draft = "draft"
    ai_generated = "ai_generated"
    needs_review = "needs_review"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"


class ScheduleStatus(enum.StrEnum):
    scheduled = "scheduled"
    queued = "queued"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    cancelled = "cancelled"
    paused = "paused"


class RunStatus(enum.StrEnum):
    queued = "queued"
    planning = "planning"
    running = "running"
    awaiting_approval = "awaiting_approval"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskStatus(enum.StrEnum):
    pending = "pending"
    ready = "ready"
    running = "running"
    awaiting_approval = "awaiting_approval"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class ApprovalStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class AccountStatus(enum.StrEnum):
    active = "active"
    expired = "expired"
    revoked = "revoked"
    error = "error"
    disconnected = "disconnected"


class ContentFormat(enum.StrEnum):
    text = "text"
    image = "image"
    carousel = "carousel"
    video = "video"
    short_video = "short_video"
    story = "story"
    article = "article"
    poll = "poll"
    document = "document"
    link = "link"


class ContentType(enum.StrEnum):
    educational = "educational"
    authority = "authority"
    promotional = "promotional"
    engagement = "engagement"
    storytelling = "storytelling"
    industry_news = "industry_news"
    case_study = "case_study"
    behind_the_scenes = "behind_the_scenes"
    ugc = "ugc"
    thought_leadership = "thought_leadership"
    announcement = "announcement"


class Availability(enum.StrEnum):
    official_api = "official_api"
    public_web = "public_web"
    search = "search"
    user_provided = "user_provided"
    not_collected = "not_collected"


class RiskLevel(enum.StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class AutomationStatus(enum.StrEnum):
    running = "running"
    waiting = "waiting"
    awaiting_approval = "awaiting_approval"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"

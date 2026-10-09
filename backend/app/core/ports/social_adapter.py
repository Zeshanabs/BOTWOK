from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)   # page tokens, open_id, etc.


@dataclass
class ConnectableAccount:
    external_id: str
    display_name: str
    handle: str | None = None
    avatar_url: str | None = None
    account_type: str | None = None
    parent_external_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Capabilities:
    formats: list[str]
    max_text: int | None
    max_media: int
    native_schedule: bool
    can_delete: bool
    supports_alt_text: bool
    limits: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ValidationIssue:
    code: str
    message: str
    field: str | None = None
    severity: str = "error"   # error | warning


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass
class MediaInput:
    url: str | None            # public URL (if available)
    bytes_loader: Any | None   # async callable returning bytes
    mime: str
    alt_text: str | None = None
    kind: str = "image"


@dataclass
class PublishRequest:
    text: str
    segments: list[str] = field(default_factory=list)      # threads
    media: list[MediaInput] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict) # platform-specific (title, description, privacy, link, poll…)
    fingerprint: str = ""


@dataclass
class PublishResult:
    external_id: str
    external_url: str | None
    published_at: datetime
    segments: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemotePost:
    external_id: str
    text: str | None
    created_at: datetime | None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class PublishError(Exception):
    """category: transient | rate_limited | auth | validation | permanent | ambiguous | unsupported"""

    def __init__(self, category: str, message: str, code: str | None = None, retry_after_s: int | None = None, raw: Any = None):
        super().__init__(message)
        self.category, self.message, self.code, self.retry_after_s, self.raw = category, message, code, retry_after_s, raw


class SocialAdapter(Protocol):
    platform: str
    verified_at: str

    def capabilities(self, account: Any) -> Capabilities: ...
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str: ...
    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet: ...
    async def refresh(self, tokens: TokenSet) -> TokenSet: ...
    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]: ...
    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]: ...
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult: ...
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult: ...
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost: ...
    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None: ...
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]: ...
    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]: ...
    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]: ...

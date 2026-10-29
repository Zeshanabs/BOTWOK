"""Tool registry: SideEffect classes, ToolDef, ToolContext, the global `registry`, and the `@tool` decorator (re-exported).

Other modules register tools by decorating async functions:

    from app.tools.registry import tool, SideEffect, ToolContext

    @tool("web.search", side_effect=SideEffect.EXTERNAL_READ, timeout_s=20, untrusted_output=True)
    async def web_search(ctx: ToolContext, query: str, kind: str = "web", limit: int = 10) -> dict: ...

The JSON schema for the LLM is derived from the signature (Pydantic); the docstring (or `description=`) is the description.
Tool modules under app/tools/*.py are imported by `load_builtin_tools()` so the registry is populated before a run.
"""
from __future__ import annotations

import enum
import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.core.ports.ai_provider import ToolSpec
from app.models.enums import ROLE_RANK

log = get_logger("tools")


class SideEffect(enum.StrEnum):
    READ = "READ"
    WRITE_INTERNAL = "WRITE_INTERNAL"
    EXTERNAL_READ = "EXTERNAL_READ"
    SPEND = "SPEND"
    APPROVAL = "APPROVAL"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"


# Side-effect classes that agents reading untrusted content may never hold (doc 19 §19.6 rule 4).
UNTRUSTED_FORBIDDEN = {SideEffect.APPROVAL, SideEffect.SPEND, SideEffect.EXTERNAL_WRITE}


@dataclass
class ToolContext:
    """Everything a tool gets besides its arguments. `db` is the run's session when executed inside a run."""
    workspace_id: UUID
    brand_id: UUID | None = None
    user_id: UUID | None = None
    role: str = "editor"
    run_id: UUID | None = None
    task_id: UUID | None = None
    agent_id: str | None = None
    budget: Any = None                      # BudgetGuard (or None outside runs)
    db: Any = None                          # AsyncSession | None
    session_factory: Callable[..., Any] | None = None
    logger: Any = None
    canary: str | None = None
    approval_results: dict[str, Any] = field(default_factory=dict)   # tool-call fingerprint -> stored result (resume)
    extra: dict[str, Any] = field(default_factory=dict)

    def has_role(self, required: str | None) -> bool:
        if not required:
            return True
        return ROLE_RANK.get(str(getattr(self.role, "value", self.role)), 0) >= ROLE_RANK.get(required, 99)

    def session(self):
        """Async context manager yielding a session scoped to this workspace (for tools called outside a run session)."""
        if self.session_factory is not None:
            return self.session_factory(self.workspace_id)
        from app.core.db import session_scope
        return session_scope(self.workspace_id)

    async def emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.db is None:
            return
        from app.core.events import emit
        actor = {"type": "agent", "id": self.agent_id} if self.agent_id else {"type": "system"}
        await emit(self.db, name, {**payload, "run_id": str(self.run_id) if self.run_id else None},
                   workspace_id=self.workspace_id, actor=actor)

    @property
    def log(self):
        return self.logger or log


ToolFn = Callable[..., Awaitable[Any]]


@dataclass
class ToolDef:
    name: str
    fn: ToolFn
    side_effect: SideEffect
    description: str
    parameters: dict[str, Any]
    args_model: Any                          # pydantic model class for argument validation
    roles: set[str] | None = None            # minimum role set (any of) required to call; None = any member
    timeout_s: float = 20.0
    idempotent: bool = False
    untrusted_output: bool = False
    rate_limit_per_run: int | None = None
    module: str | None = None

    @property
    def min_role(self) -> str | None:
        if not self.roles:
            return None
        return min(self.roles, key=lambda r: ROLE_RANK.get(r, 99))

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)

    def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        model = self.args_model.model_validate(args or {})
        return model.model_dump()


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, t: ToolDef, *, replace: bool = True) -> ToolDef:
        if t.name in self._tools and not replace:
            raise ValueError(f"tool {t.name} already registered")
        self._tools[t.name] = t
        return t

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolDef]:
        return [self._tools[n] for n in self.names()]

    def specs_for(self, names: list[str] | None) -> list[ToolSpec]:
        """ToolSpecs for the given allowlist (missing tools are skipped, logged once)."""
        out: list[ToolSpec] = []
        for n in names or []:
            t = self._tools.get(n)
            if t is None:
                if n not in _missing_warned:
                    _missing_warned.add(n)
                    log.info("tools.not_registered", tool=n)
                continue
            out.append(t.spec())
        return out

    def side_effect_of(self, name: str) -> SideEffect | None:
        t = self._tools.get(name)
        return t.side_effect if t else None


_missing_warned: set[str] = set()
registry = ToolRegistry()

# Modules that may register tools (other builders own most of them; missing modules are skipped).
BUILTIN_TOOL_MODULES = ["brand", "memory", "publishing", "web", "research", "content", "social", "competitors",
                        "analytics", "stats", "trends", "strategy", "ideas", "media", "reports", "factcheck", "claims",
                        "insights", "keywords", "hashtags", "platform", "policy", "rss"]
_loaded = False


def load_builtin_tools(force: bool = False) -> list[str]:
    """Import every app.tools.<module> that exists so decorators run. Idempotent."""
    global _loaded
    if _loaded and not force:
        return registry.names()
    for mod in BUILTIN_TOOL_MODULES:
        name = f"app.tools.{mod}"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name != name:
                log.warning("tools.module_import_failed", module=name, error=str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("tools.module_import_failed", module=name, error=str(e)[:300])
    _loaded = True
    return registry.names()


from app.tools.decorators import tool  # noqa: E402  (re-export; decorators imports this module's names)

__all__ = ["SideEffect", "ToolContext", "ToolDef", "ToolRegistry", "registry", "tool", "load_builtin_tools",
           "UNTRUSTED_FORBIDDEN"]

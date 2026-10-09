"""Editorial status guard matrix (doc 17 §17.2 `POST /content/{id}/transition`, doc 00 §4 RBAC).

Pure functions — no DB. ``ContentService.transition`` uses ``can_transition`` and adds the stateful checks
(live schedules, high-risk approvals, contradicted claims).

Roles: content editing is allowed to owner/admin/editor/approver (doc 00 §4 "Create/edit content"); approving and
rejecting only to owner/admin/approver; archiving to owner/admin.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

EDIT_ROLES = frozenset({"owner", "admin", "editor", "approver"})
APPROVE_ROLES = frozenset({"owner", "admin", "approver"})
ADMIN_ROLES = frozenset({"owner", "admin"})
ALL_STATUSES = ("idea", "draft", "ai_generated", "needs_review", "approved", "rejected", "archived")

# (from, to) → roles allowed. "*" as from means any non-archived status.
TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("idea", "draft"): EDIT_ROLES,
    ("draft", "needs_review"): EDIT_ROLES,
    ("ai_generated", "needs_review"): EDIT_ROLES,
    ("ai_generated", "draft"): EDIT_ROLES,          # a human takes over the AI draft
    ("needs_review", "approved"): APPROVE_ROLES,
    ("needs_review", "rejected"): APPROVE_ROLES,
    ("needs_review", "draft"): EDIT_ROLES,          # withdraw from review / request changes
    ("rejected", "draft"): EDIT_ROLES,              # revise after rejection
    ("approved", "draft"): EDIT_ROLES,              # unlock for editing (409 if live schedules exist)
    ("archived", "draft"): ADMIN_ROLES,             # unarchive
    ("*", "archived"): ADMIN_ROLES,
}

# Statuses whose content (body/variants) may be edited in place.
EDITABLE_STATUSES = frozenset({"idea", "draft", "ai_generated", "needs_review", "rejected"})
LOCKED_STATUSES = frozenset({"approved", "archived"})


def _v(x: Any) -> str:
    return (x.value if isinstance(x, Enum) else str(x or "")).strip().lower()


def can_transition(role: Any, from_status: Any, to_status: Any) -> bool:
    """True if a member with ``role`` may move content from ``from_status`` to ``to_status``."""
    r, f, t = _v(role), _v(from_status), _v(to_status)
    if f == t or f not in ALL_STATUSES or t not in ALL_STATUSES:
        return False
    roles = TRANSITIONS.get((f, t))
    if roles is None and t == "archived" and f != "archived":
        roles = TRANSITIONS[("*", "archived")]
    return roles is not None and r in roles


def is_known_transition(from_status: Any, to_status: Any) -> bool:
    """True if the transition exists for at least one role (distinguishes 409 invalid vs 403 forbidden)."""
    f, t = _v(from_status), _v(to_status)
    if f == t:
        return False
    return (f, t) in TRANSITIONS or (t == "archived" and f != "archived" and f in ALL_STATUSES)


def allowed_targets(role: Any, from_status: Any) -> list[str]:
    return [t for t in ALL_STATUSES if can_transition(role, from_status, t)]


def is_editable(status: Any) -> bool:
    return _v(status) in EDITABLE_STATUSES

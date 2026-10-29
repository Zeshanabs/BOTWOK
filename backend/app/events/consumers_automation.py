"""Event consumers owned by the automation engine (doc 14 §14.4).

One consumer per event name (every ``trigger.event`` catalog event + the resume events) → ``triggers.handle_event``:
* resume: AI_RUN_COMPLETED/FAILED (ai_agent/generate/analytics steps), RESEARCH_COMPLETED/FAILED (research steps),
  CONTENT_APPROVED/REJECTED/STATUS_CHANGED (approve steps on content) wake the waiting run and re-enqueue it;
* triggers: start runs of active workflows whose ``trigger.event`` matches (filter + condition).
"""
from __future__ import annotations

from typing import Any

from app.core.events import on_event
from app.workflows.catalog import TRIGGER_EVENTS

RESUME_EVENTS = ("AI_RUN_COMPLETED", "AI_RUN_FAILED", "RESEARCH_COMPLETED", "RESEARCH_FAILED", "CONTENT_APPROVED",
                 "CONTENT_REJECTED", "CONTENT_STATUS_CHANGED")


async def automation_event(envelope: dict[str, Any]) -> None:
    from app.workflows.triggers import handle_event
    await handle_event(envelope)


for _name in sorted(set(TRIGGER_EVENTS) | set(RESUME_EVENTS)):
    on_event(_name)(automation_event)

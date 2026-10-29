"""IntentRouter (doc 05 §5.2.3): one cheap structured call → IntentResult; keyword heuristics as offline fallback."""
from __future__ import annotations

import re
from typing import Any

from app.agents.orchestrator import ledger
from app.agents.orchestrator.context import RunContext
from app.agents.registry import get_agent
from app.agents.schemas.orchestrator import INTENTS, IntentResult
from app.core.logging import get_logger
from app.integrations.ai import base as ai_base
from app.integrations.ai.registry import providers_for_tier

log = get_logger("ai.intent")

_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("schedule", ("schedule", "queue it", "post it at", "set it to go out")),
    ("publish", ("publish now", "post now", "publish it", "go live")),
    ("repurpose", ("repurpose", "adapt this", "turn this into", "version for", "variants for")),
    ("generate_media", ("image", "visual", "carousel", "thumbnail", "video script", "picture", "graphic")),
    ("analyze_performance", ("performance", "what worked", "engagement", "analytics", "best performing", "metrics")),
    ("report", ("report", "summary report", "weekly recap", "write up")),
    ("build_calendar", ("calendar", "content plan for", "plan the week", "plan next month", "schedule for the month")),
    ("find_trends", ("trend", "trending", "what's hot", "emerging")),
    ("find_news", ("news", "latest", "this week in", "headlines")),
    ("research_competitors", ("competitor", "competitors", "rivals", "compare us to")),
    ("analyze_competitor_content", ("what are competitors posting", "competitor content", "competitor posts")),
    ("strategy_recommendation", ("strategy", "pillars", "content mix", "positioning", "how should we")),
    ("generate_ideas", ("ideas", "brainstorm", "topics to post", "what should we post", "suggest topics")),
    ("write_post", ("write", "draft", "create a post", "create posts", "post about", "caption", "linkedin post", "tweet", "thread")),
    ("research_topic", ("research", "find out", "look into", "learn about", "dig into", "what do we know")),
    ("configure_automation", ("automation", "automate", "workflow", "every week automatically", "recurring")),
    ("question_about_data", ("how many", "which post", "show me", "list my", "what did we")),
    ("smalltalk", ("hello", "hi ", "hey", "thanks", "thank you", "who are you", "what can you do")),
]
_PLATFORMS = ("facebook", "instagram", "threads", "linkedin", "x", "twitter", "tiktok", "youtube", "pinterest", "gbp", "google business")
_COUNT_RE = re.compile(r"\b(\d{1,2})\b")


def heuristic_route(message: str) -> IntentResult:
    m = (message or "").lower().strip()
    found: list[str] = []
    for intent, keys in _RULES:
        if any(k in m for k in keys) and intent not in found:
            found.append(intent)
    # ordering: evidence-gathering intents before production intents
    order = {i: n for n, i in enumerate(INTENTS)}
    found.sort(key=lambda i: order.get(i, 99))
    if not found:
        found = ["unknown" if len(m.split()) > 3 else "smalltalk"]
    entities: dict[str, Any] = {}
    plats = [p for p in _PLATFORMS if p in m]
    if plats:
        entities["platforms"] = ["x" if p == "twitter" else "gbp" if p == "google business" else p for p in plats]
    cm = _COUNT_RE.search(m)
    if cm:
        entities["count"] = int(cm.group(1))
    topic = re.sub(r"^(please|can you|could you|i want you to|i need)\s+", "", m)
    for verb in ("research", "write", "create", "find", "draft", "analyze", "generate", "give me", "make"):
        if topic.startswith(verb):
            topic = topic[len(verb):].strip()
            break
    entities["topic"] = topic[:120] if topic else None
    primary = found[0]
    clarification = primary == "unknown"
    reply = None
    if primary == "smalltalk":
        reply = ("Hi! I'm the Botwok assistant. I can research topics and competitors, find trends, generate ideas, write and "
                 "repurpose posts, plan calendars, analyze performance and draft reports. What would you like to do?")
    return IntentResult(intent=primary, intents=found, entities={k: v for k, v in entities.items() if v},
                        capabilities=["approval"] if primary in ("schedule", "publish") else [],
                        clarification_needed=clarification,
                        question="Could you tell me a bit more about what you'd like me to do (for example: research a topic, "
                                 "write posts for a platform, or analyze performance)?" if clarification else None,
                        confidence=0.4, reply=reply)


class IntentRouter:
    async def route(self, db: Any, ctx: RunContext, message: str) -> IntentResult:
        agent = get_agent("intent_router")
        try:
            prompt = await self._prompt(db, ctx)
            msgs = agent.build_messages(ctx, {"message": message, "entities_hint": ctx.intent or {}}, action="route",
                                        prompt_body=prompt, brand_context=ctx.brand, memory_snippets=ctx.memory.snippets(4),
                                        conversation=ctx.conversation, canary=ctx.canary)
            candidates = await providers_for_tier(db, ctx.workspace_id, "cheap", "intent_router", routing=ctx.settings.get("routing"))
            last_err: Exception | None = None
            for provider, model in candidates:
                try:
                    comp = await provider.complete(msgs, model=model, response_schema=agent.output_schema("route"),
                                                   temperature=0.0, max_tokens=600)
                except ai_base.ProviderError as e:
                    last_err = e
                    log.warning("intent.provider_failed", provider=provider.name, model=model, error=str(e)[:160])
                    continue
                await ledger.record_call(db, run=ctx.run, task=None, agent_id="intent_router", completion=comp,
                                         prompt_hash_=ledger.prompt_hash(msgs), temperature=0.0, workspace_id=ctx.workspace_id)
                agent.check_canary(comp.content, ctx.canary)
                data = ai_base.parse_structured(comp.content)
                result = IntentResult.model_validate(data)
                if result.intent == "unknown" and not result.intents and not result.clarification_needed:
                    h = heuristic_route(message)
                    if h.intent != "unknown":
                        return h
                return result
            if last_err:
                raise last_err
        except Exception as e:  # noqa: BLE001 - heuristics keep the system usable offline
            log.warning("intent.fallback_heuristic", error=str(e)[:200])
        return heuristic_route(message)

    async def _prompt(self, db: Any, ctx: RunContext) -> str | None:
        try:
            from app.services.ai_settings_service import AISettingsService
            return (await AISettingsService().get_prompt(db, ctx.workspace_id, "intent_router"))["body"]
        except Exception:  # noqa: BLE001
            return None

"""Planner + PlanValidator (doc 05 §5.2.4): powerful-tier structured Plan seeded by intent templates; validation of agents,
actions, DAG acyclicity, fan-out width, cost vs budget and approval flags; one re-prompt with errors."""
from __future__ import annotations

import json
import re
from typing import Any

from app.agents.orchestrator import ledger
from app.agents.orchestrator.context import RunContext
from app.agents.orchestrator.plan_templates import MAX_FAN_OUT, TIER_COST_USD, compose_plan, template_hints
from app.agents.registry import catalog_for_planner, enabled_agent_ids, get_agent
from app.agents.schemas.orchestrator import IntentResult, Plan, PlanTask
from app.agents.specs import SPECS
from app.core.logging import get_logger
from app.core.ports.ai_provider import Message
from app.integrations.ai import base as ai_base
from app.integrations.ai.registry import providers_for_tier

log = get_logger("ai.planner")
_TASK_ID_RE = re.compile(r"^t\d+(\.\d+)?$")
_REF_RE = re.compile(r"^(t\d+)(?:\.(\S+))?$")


class PlanInvalid(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors)[:1000])
        self.errors = errors


class PlanValidator:
    def __init__(self, enabled_agents: set[str] | None = None, *, max_fan_out: int = MAX_FAN_OUT, budget_usd: float | None = None,
                 fan_out_assumed_width: int = 3):
        self.enabled = enabled_agents if enabled_agents is not None else set(SPECS)
        self.max_fan_out = max_fan_out
        self.budget_usd = budget_usd
        self.assumed_width = fan_out_assumed_width

    @staticmethod
    def topo_order(tasks: list[PlanTask]) -> list[str]:
        """Kahn's algorithm; raises PlanInvalid on cycles or unknown dependencies."""
        ids = [t.id for t in tasks]
        deps = {t.id: [d for d in t.depends_on] for t in tasks}
        unknown = [f"{t.id} depends on unknown task {d}" for t in tasks for d in t.depends_on if d not in deps]
        if unknown:
            raise PlanInvalid(unknown)
        indeg = {i: len(deps[i]) for i in ids}
        out: list[str] = []
        ready = [i for i in ids if indeg[i] == 0]
        while ready:
            cur = ready.pop(0)
            out.append(cur)
            for other in ids:
                if cur in deps[other]:
                    indeg[other] -= 1
                    if indeg[other] == 0:
                        ready.append(other)
        if len(out) != len(ids):
            raise PlanInvalid([f"plan has a dependency cycle involving: {', '.join(sorted(set(ids) - set(out)))}"])
        return out

    def estimate_cost(self, plan: Plan) -> float:
        total = 0.0
        for t in plan.tasks:
            spec = SPECS.get(t.agent)
            per = TIER_COST_USD.get(spec.tier if spec else "balanced", 0.08)
            if t.budget and t.budget.max_cost_usd is not None:
                per = min(per, float(t.budget.max_cost_usd)) if t.fan_out is None else float(t.budget.max_cost_usd)
            width = self.assumed_width if t.fan_out else 1
            if t.fan_out and t.fan_out.startswith("$inputs."):
                key = t.fan_out.split(".", 1)[1]
                items = t.inputs.get(key)
                if isinstance(items, list):
                    width = min(len(items), self.max_fan_out)
            total += per * width
        return round(total, 4)

    def validate(self, plan: Plan) -> list[str]:
        errors: list[str] = []
        if not plan.tasks:
            return ["plan has no tasks"]
        seen: set[str] = set()
        for t in plan.tasks:
            if not _TASK_ID_RE.match(t.id):
                errors.append(f"task id {t.id!r} must look like t1, t2, …")
            if t.id in seen:
                errors.append(f"duplicate task id {t.id}")
            seen.add(t.id)
            spec = SPECS.get(t.agent)
            if spec is None:
                errors.append(f"{t.id}: unknown agent {t.agent!r}")
                continue
            if t.agent not in self.enabled:
                errors.append(f"{t.id}: agent {t.agent!r} is disabled in this workspace")
            if t.action not in spec.actions:
                errors.append(f"{t.id}: agent {t.agent!r} has no action {t.action!r} (valid: {', '.join(spec.actions)})")
            elif spec.actions[t.action].approval:
                t.requires_approval = True
            if t.id in t.depends_on:
                errors.append(f"{t.id} depends on itself")
            if t.fan_out:
                m = _REF_RE.match(t.fan_out)
                if not (m or t.fan_out.startswith("$inputs.")):
                    errors.append(f"{t.id}: fan_out must reference a task output like t1.items")
                elif m and m.group(1) not in t.depends_on and m.group(1) != t.id:
                    errors.append(f"{t.id}: fan_out source {m.group(1)} must be in depends_on")
                if t.fan_out.startswith("$inputs."):
                    items = t.inputs.get(t.fan_out.split(".", 1)[1])
                    if isinstance(items, list) and len(items) > self.max_fan_out:
                        errors.append(f"{t.id}: fan-out width {len(items)} exceeds {self.max_fan_out}")
            for ref in _iter_refs(t.inputs):
                src = _REF_RE.match(ref)
                if src and src.group(1) not in t.depends_on and src.group(1) != t.id:
                    errors.append(f"{t.id}: input references {src.group(1)} which is not in depends_on")
        try:
            self.topo_order(plan.tasks)
        except PlanInvalid as e:
            errors.extend(e.errors)
        if self.budget_usd is not None:
            est = self.estimate_cost(plan)
            plan.estimated_cost_usd = est
            if est > self.budget_usd:
                errors.append(f"estimated cost ${est:.2f} exceeds run budget ${self.budget_usd:.2f}; use fewer/cheaper tasks")
        for d in plan.deliverables:
            m = _REF_RE.match(d)
            if not m or m.group(1) not in seen:
                errors.append(f"deliverable {d!r} does not reference a task")
        plan.approval_points = sorted({*plan.approval_points, *(t.id for t in plan.tasks if t.requires_approval)})
        return errors


def _iter_refs(obj: Any, depth: int = 0):
    if depth > 6:
        return
    if isinstance(obj, str):
        if _REF_RE.match(obj):
            yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if (k.endswith("_from") or k == "from") and isinstance(v, str):
                yield v
            elif (k.endswith("_from") or k == "from") and isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        yield x
            else:
                yield from _iter_refs(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_refs(v, depth + 1)


class Planner:
    async def plan(self, db: Any, ctx: RunContext, intent: IntentResult, message: str) -> Plan:
        intents = intent.all_intents()
        enabled = await enabled_agent_ids(db)
        validator = PlanValidator(enabled, budget_usd=ctx.budget.max_cost_usd)
        seed = compose_plan(intents, intent.entities, message)
        agent = get_agent("planner")
        inputs = {"message": message, "intents": intents, "entities": intent.entities,
                  "templates": template_hints(intents, intent.entities, message), "budget_usd": ctx.budget.max_cost_usd,
                  "conversation_summary": ctx.conversation_summary}
        extra = {"agents": catalog_for_planner(), "max_fan_out": MAX_FAN_OUT, "budget_usd": ctx.budget.max_cost_usd}
        prompt = await self._prompt(db, ctx)
        msgs = agent.build_messages(ctx, inputs, action="plan", prompt_body=prompt, brand_context=ctx.brand,
                                    memory_snippets=ctx.memory.snippets(4), conversation=ctx.conversation, canary=ctx.canary,
                                    extra_vars=extra)
        schema = agent.output_schema("plan")
        try:
            candidates = await providers_for_tier(db, ctx.workspace_id, "powerful", "planner", routing=ctx.settings.get("routing"))
        except Exception as e:  # noqa: BLE001
            log.warning("planner.no_provider", error=str(e)[:160])
            candidates = []
        errors: list[str] = []
        for attempt in range(2):
            plan = await self._ask(db, ctx, agent, candidates, msgs, schema)
            if plan is None:
                break
            errors = validator.validate(plan)
            if not errors:
                return plan
            log.info("planner.invalid", attempt=attempt, errors=errors[:5])
            msgs = msgs + [Message(role="assistant", content=json.dumps(plan.model_dump(), default=str)),
                           Message(role="user", content="The plan failed validation:\n- " + "\n- ".join(errors) +
                                   "\nReturn a corrected plan as JSON only.")]
        if seed is not None:
            seed_errors = validator.validate(seed)
            if not seed_errors:
                log.info("planner.using_template", intents=intents)
                return seed
            errors = errors or seed_errors
        raise PlanInvalid(errors or [f"no plan template for intents {intents}; please rephrase the request"])

    async def _ask(self, db: Any, ctx: RunContext, agent, candidates, msgs: list[Message], schema: dict[str, Any]) -> Plan | None:
        for provider, model in candidates:
            try:
                comp = await provider.complete(msgs, model=model, response_schema=schema, temperature=0.1, max_tokens=3000)
            except ai_base.ProviderError as e:
                log.warning("planner.provider_failed", provider=provider.name, model=model, error=str(e)[:160])
                continue
            await ledger.record_call(db, run=ctx.run, task=None, agent_id="planner", completion=comp,
                                     prompt_hash_=ledger.prompt_hash(msgs), temperature=0.1, workspace_id=ctx.workspace_id)
            agent.check_canary(comp.content, ctx.canary)
            try:
                data = ai_base.parse_structured(comp.content)
                return Plan.model_validate(data)
            except Exception as e:  # noqa: BLE001
                log.warning("planner.parse_failed", error=str(e)[:160])
                msgs.append(Message(role="assistant", content=comp.content or "(empty)"))
                msgs.append(Message(role="user", content=f"That was not a valid Plan JSON ({str(e)[:200]}). Reply with JSON only."))
                continue
        return None

    async def _prompt(self, db: Any, ctx: RunContext) -> str | None:
        try:
            from app.services.ai_settings_service import AISettingsService
            return (await AISettingsService().get_prompt(db, ctx.workspace_id, "planner"))["body"]
        except Exception:  # noqa: BLE001
            return None

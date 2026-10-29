"""wait — duration (minutes/hours/days), an ``until`` time, or ``until_expression`` polled every ``poll_minutes`` up to
``timeout_hours``. The run goes to ``waiting`` with ``waiting_until``; ``dispatch_waiting`` resumes it. A wait inside a
loop counts iterations in ``context._loops`` and fails once ``max_iterations`` is exceeded."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.workflows.expressions import ExpressionError
from app.workflows.nodes.base import NodeContext, NodeError, NodeYield, parse_dt, utcnow


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    st = ctx.state
    if "started_at" not in st:
        loops = dict((ctx.run.context or {}).get("_loops") or {})
        loops[ctx.node_key] = int(loops.get(ctx.node_key, 0)) + 1
        ctx.run.context = {**(ctx.run.context or {}), "_loops": loops}
        st["iteration"] = loops[ctx.node_key]
        st["started_at"] = utcnow().isoformat()
        max_it = config.get("max_iterations")
        if isinstance(max_it, int) and st["iteration"] > max_it:
            raise NodeError(f"loop through wait {ctx.node_key!r} exceeded max_iterations={max_it}")
    started = parse_dt(st["started_at"]) or utcnow()
    if config.get("until_expression"):
        timeout = started + timedelta(hours=float(config.get("timeout_hours") or 24))
        try:
            done = bool(ctx.evaluate(str(config["until_expression"])))
        except ExpressionError as e:
            raise NodeError(f"until_expression: {e}") from e
        if done or ctx.dry_run:
            return {"waited_until": utcnow().isoformat(), "timed_out": False, "iteration": st["iteration"],
                    **({"simulated": True} if ctx.dry_run and not done else {})}
        if utcnow() >= timeout:
            return {"waited_until": utcnow().isoformat(), "timed_out": True, "iteration": st["iteration"]}
        nxt = min(utcnow() + timedelta(minutes=int(config.get("poll_minutes") or 15)), timeout)
        raise NodeYield("waiting", reason="wait_expression", until=nxt)
    if "due" not in st:
        if config.get("until"):
            due = parse_dt(config["until"])
        else:
            delta = timedelta(minutes=float(config.get("minutes") or 0), hours=float(config.get("hours") or 0),
                              days=float(config.get("days") or 0))
            due = started + delta
        st["due"] = due.isoformat() if due else started.isoformat()
    due = parse_dt(st["due"]) or started
    if ctx.dry_run:
        return {"waited_until": due.isoformat(), "simulated": True, "iteration": st["iteration"]}
    if utcnow() >= due:
        return {"waited_until": due.isoformat(), "iteration": st["iteration"]}
    raise NodeYield("waiting", reason="wait", until=due)

"""webhook — signed outbound HTTPS call (EXTERNAL_WRITE; requires autonomous actions). SSRF-guarded by
``SafeFetcher.validate_url`` (public addresses only, no redirects followed), optional host allowlist in workspace
settings ``automations.webhook_allowed_hosts``, HMAC-SHA256 signature ``X-Botwok-Signature: t=<ts>,v1=<hex>`` over
``"<ts>.<body>"`` with the workflow's signing secret (``AutomationEngine.signing_secret``)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlsplit

from app.workflows.nodes.base import NodeContext, NodeError, jsonable

BLOCKED_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "x-botwok-signature", "cookie"}
MAX_RESPONSE = 256 * 1024


def sign(secret: str, ts: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


async def _allowed_hosts(ctx: NodeContext) -> list[str]:
    from app.models.identity import Workspace
    ws = await ctx.db.get(Workspace, ctx.workspace_id)
    hosts = ((ws.settings or {}).get("automations") or {}).get("webhook_allowed_hosts") if ws else None
    return [str(h).lower().strip() for h in hosts or [] if str(h).strip()]


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    from app.workflows.engine import AutomationEngine
    if not ctx.workflow.autonomous_actions_enabled:
        raise NodeError("autonomous actions are disabled for this workflow; webhook not sent")
    url = str(config.get("url") or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise NodeError("webhook url must use https://")
    host = (parts.hostname or "").lower()
    allowed = await _allowed_hosts(ctx)
    if allowed and not any(host == h or host.endswith("." + h) for h in allowed):
        raise NodeError(f"host {host!r} is not in the workspace's webhook allowlist")
    method = str(config.get("method") or "POST").upper()
    payload = config.get("body")
    if payload is None:
        payload = {"workflow_id": str(ctx.workflow.id), "run_id": str(ctx.run.id), "trigger": ctx.scope.get("trigger"),
                   "steps": ctx.scope.get("steps")}
    body = json.dumps(jsonable(payload), default=str).encode()
    if len(body) > 512 * 1024:
        raise NodeError("webhook body is larger than 512 KB")
    headers = {str(k): str(v) for k, v in (config.get("headers") or {}).items()
               if str(k).lower() not in BLOCKED_HEADERS and "\n" not in str(v) and "\r" not in str(v)}
    headers.update({"Content-Type": "application/json", "User-Agent": "Botwok-Automations/1.0",
                    "X-Botwok-Workflow": str(ctx.workflow.id), "X-Botwok-Run": str(ctx.run.id),
                    "Idempotency-Key": f"{ctx.run.id}:{ctx.node_key}"})
    if config.get("sign", True):
        headers["X-Botwok-Signature"] = sign(AutomationEngine.signing_secret(ctx.workflow), int(time.time()), body)
    if ctx.dry_run:
        return ctx.simulated(url=url, method=method, body=payload, signed="X-Botwok-Signature" in headers)
    from app.core.resilience import ResilienceError
    from app.core.safe_fetch import SafeFetcher
    timeout = float(config.get("timeout_seconds") or 10)
    fetcher = SafeFetcher(respect_robots=False, attempts=1, read_timeout=timeout)
    try:
        await fetcher.validate_url(url)
        resp = await fetcher.client.request(method, url, raise_for_status=False, max_bytes=MAX_RESPONSE, retry=False,
                                            attempts=1, content=body, headers=headers)
    except ResilienceError as e:
        raise NodeError(f"webhook blocked or failed: {e.message}") from e
    finally:
        await fetcher.aclose()
    text = resp.text[:4000] if resp.content else ""
    try:
        parsed: Any = resp.json() if resp.content else None
    except ValueError:
        parsed = text
    out = {"status": resp.status_code, "ok": 200 <= resp.status_code < 300, "response": jsonable(parsed)}
    if resp.is_redirect:
        raise NodeError(f"webhook returned a redirect ({resp.status_code}); redirects are not followed")
    if not out["ok"]:
        raise NodeError(f"webhook returned HTTP {resp.status_code}", out)
    return out

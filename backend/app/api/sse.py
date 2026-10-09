"""Server-Sent Events: GET /api/v1/events/stream (Redis pub/sub per workspace, Last-Event-ID replay from a stream)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentMember
from app.core.redis import get_redis

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream(request: Request, member: CurrentMember):
    channel = f"ws:{member.workspace_id}"
    last_id = request.headers.get("last-event-id")

    async def gen():
        r = get_redis()
        if last_id:
            try:
                for sid, fields in await r.xrange(f"stream:{channel}", min=f"({last_id}", max="+", count=500):
                    yield f"id: {sid}\nevent: message\ndata: {fields['data']}\n\n"
            except Exception:
                pass
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if msg is None:
                    yield ": heartbeat\n\n"
                    continue
                data = msg["data"]
                try:
                    name = json.loads(data).get("name", "message")
                except Exception:
                    name = "message"
                yield f"event: {name}\ndata: {data}\n\n"
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class JobQueue(Protocol):
    async def enqueue(self, task_name: str, args: dict[str, Any], *, queue: str = "default", lock: str | None = None,
                      queueing_lock: str | None = None, run_at: datetime | None = None) -> int: ...

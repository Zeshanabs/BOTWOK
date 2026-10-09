"""Entry: python -m app.workers.main worker|scheduler"""
from __future__ import annotations

import asyncio
import sys

from app.config import settings
from app.core.logging import configure_logging, get_logger

configure_logging(settings.log_level)
log = get_logger("workers")


async def run_worker() -> None:
    from app.workers.app import QUEUES, procrastinate_app
    try:
        from app.events import load_consumers
        load_consumers()
    except Exception as e:
        log.warning("consumers.not_loaded", error=str(e))
    async with procrastinate_app.open_async():
        log.info("worker.start", queues=QUEUES)
        await procrastinate_app.run_worker_async(queues=QUEUES, concurrency=8, wait=True)


async def run_scheduler() -> None:
    from app.workers.scheduler import scheduler_loop
    await scheduler_loop()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "worker"
    asyncio.run(run_worker() if mode == "worker" else run_scheduler())

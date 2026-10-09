"""Procrastinate app: Postgres-backed queue. Tasks register with @procrastinate_app.task in app/workers/jobs/*."""
from __future__ import annotations

import procrastinate

from app.config import settings

connector = procrastinate.PsycopgConnector(conninfo=settings.database_url_sync)
procrastinate_app = procrastinate.App(
    connector=connector,
    import_paths=["app.workers.jobs.ai", "app.workers.jobs.research", "app.workers.jobs.publishing", "app.workers.jobs.analytics",
                  "app.workers.jobs.media", "app.workers.jobs.competitors", "app.workers.jobs.automation",
                  "app.workers.jobs.notifications", "app.workers.jobs.maintenance", "app.workers.jobs.reports"],
)
QUEUES = ["ai", "research", "publishing", "analytics", "media", "automation", "notifications", "maintenance"]

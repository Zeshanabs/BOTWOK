from __future__ import annotations

from app.agents.base import Agent
from app.agents.specs import SPECS


class RepurposerAgent(Agent):
    spec = SPECS["repurposer"]

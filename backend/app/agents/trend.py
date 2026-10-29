from __future__ import annotations

from app.agents.base import Agent
from app.agents.specs import SPECS


class TrendAgent(Agent):
    spec = SPECS["trend"]

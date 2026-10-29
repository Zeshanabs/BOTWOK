"""Event consumers. Each `consumers_<module>.py` registers handlers with `@on_event(...)` (app.core.events).

Processes that relay the outbox (the scheduler) should call `load_consumers()` once at startup so every
consumer module is imported and registered.
"""
from __future__ import annotations

import importlib
import pkgutil


def load_consumers() -> list[str]:
    """Import every `app.events.consumers_*` module; returns the module names loaded."""
    loaded = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("consumers_"):
            importlib.import_module(f"{__name__}.{info.name}")
            loaded.append(info.name)
    return loaded

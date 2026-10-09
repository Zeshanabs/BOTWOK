import logging
import re
import sys
from contextvars import ContextVar
from types import MappingProxyType

import structlog

request_context: ContextVar[dict] = ContextVar("request_context", default=MappingProxyType({}))  # type: ignore[assignment]
_SECRET_RE = re.compile(r"(token|secret|key|password|authorization)", re.I)


def _redact(_, __, event_dict):
    for k in list(event_dict.keys()):
        if _SECRET_RE.search(k) and k not in ("key_version", "tool_name", "task_key"):
            event_dict[k] = "***"
    return event_dict


def _bind_context(_, __, event_dict):
    event_dict.update(request_context.get())
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _bind_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="ts"),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "botwok"):
    return structlog.get_logger(name)

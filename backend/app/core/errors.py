"""RFC 9457 Problem Details errors."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class ProblemError(HTTPException):
    def __init__(self, status: int, type_: str, title: str, detail: str | None = None, errors: list[dict[str, Any]] | None = None):
        super().__init__(status_code=status, detail=detail or title)
        self.type = type_
        self.title = title
        self.errors = errors or []


def not_found(what: str = "Resource") -> ProblemError:
    return ProblemError(404, "not_found", f"{what} not found")


def forbidden(detail: str = "You do not have permission to do this") -> ProblemError:
    return ProblemError(403, "forbidden", "Forbidden", detail)


def conflict(type_: str, detail: str) -> ProblemError:
    return ProblemError(409, type_, "Conflict", detail)


def validation(detail: str, errors: list[dict[str, Any]] | None = None) -> ProblemError:
    return ProblemError(422, "validation_error", "Validation failed", detail, errors)


def budget_exceeded(detail: str) -> ProblemError:
    return ProblemError(402, "budget_exceeded", "Budget exceeded", detail)

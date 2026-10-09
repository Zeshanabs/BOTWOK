from uuid import UUID

from uuid6 import uuid7


def new_id() -> UUID:
    """Time-ordered UUIDv7 for every primary key (index locality)."""
    return uuid7()

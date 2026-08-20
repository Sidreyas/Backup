"""
Identifier and timestamp conventions.

The frontend's `Id` type is an opaque string and its fixtures use readable,
prefixed ids (`req-1`, `n-cfg-approval`, `tp-1042`). Preserving that convention
rather than switching to bare UUIDs keeps ids legible in the audit log, in URLs
and in support conversations — which matters for a product whose output is read
by auditors.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    """A short, readable, collision-resistant id: `req-k3f9a2`."""
    return f"{prefix}-{secrets.token_hex(4)}"


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Naive datetimes are banned throughout: an audit record whose timestamp has
    no zone is ambiguous exactly when someone needs it to be precise.
    """
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    """Serialise for the wire in the shape the frontend expects.

    The frontend parses these with `new Date(...)`, so they must carry a zone.
    Postgres `timestamptz` round-trips as aware, but a value that arrived naive
    is coerced to UTC here rather than silently rendering without an offset.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

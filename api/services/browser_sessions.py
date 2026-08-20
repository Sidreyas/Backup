"""
Browser session lifecycle.

A captured session is the most powerful thing Meridian holds for a connection:
it carries a real administrator's permissions in a customer's tenant. So the
rules here are deliberately narrow.

**One live session per connection.** Capturing supersedes the previous one
rather than accumulating. Several valid sessions for one connection would mean
several answers to "whose access read this", which is the question an auditor
actually asks.

**Never returned.** `state()` decrypts for the replay runner and nothing else;
every API-facing shape goes through `status()`, which reports presence, capturer
and expiry but not the session itself.

**Expiry is a hint, not a guarantee.** Workday does not publish its idle
timeout and it differs per tenant, so `expires_at` is an estimate used to warn
someone before they start a long run. Replay never trusts it — a session can
die early, and the runner has to survive that either way.

**Superseded rows are kept.** A session that produced extracted configuration
is part of that data's provenance; deleting it would leave nodes attributed to
nobody.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core import secrets
from api.core.ids import new_id, utcnow
from api.domain.models import BrowserSessionRecord

#: Default assumed lifetime. Workday's own default idle timeout is commonly
#: around an hour; tenants shorten it. Deliberately conservative — warning
#: someone early costs a re-capture, warning them late costs a failed run.
DEFAULT_TTL = timedelta(minutes=45)

#: Below this, a long extraction should not be started. Surfaced by the UI so
#: an admin re-captures before a walk rather than halfway through one.
LOW_REMAINING = timedelta(minutes=10)


class SessionUnavailable(RuntimeError):
    """No usable session exists for this connection."""


@dataclass(slots=True)
class SessionStatus:
    """What the API and UI may know about a session.

    Notably absent: the session itself.
    """

    present: bool
    captured_by: str = ""
    captured_at: str = ""
    expires_at: str = ""
    last_used_at: str = ""
    #: Seconds until the estimated expiry; negative once past it.
    remaining_seconds: int = 0
    expired: bool = False
    #: True when there is too little time left to start a long extraction.
    expiring_soon: bool = False
    message: str = ""


def live_session(
    db: Session, connection_id: str
) -> BrowserSessionRecord | None:
    """The current session for a connection, if one exists and is not revoked.

    Expiry is *not* filtered here: an expired session is still the current one,
    and the caller needs to tell "expired, re-capture" apart from "never
    captured", which are different problems with different fixes.
    """
    return db.execute(
        select(BrowserSessionRecord)
        .where(
            BrowserSessionRecord.connection_id == connection_id,
            BrowserSessionRecord.revoked_at.is_(None),
        )
        .order_by(BrowserSessionRecord.captured_at.desc())
    ).scalars().first()


def capture(
    db: Session,
    *,
    connection_id: str,
    state_json: str,
    captured_by: str,
    workspace_id: str | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> BrowserSessionRecord:
    """Store a session captured by the desktop helper.

    Validates that the payload is really a Playwright storage state before
    storing it. An admin who pastes the wrong thing should find out now, not
    when a scheduled extraction fails at 2am with a JSON error.
    """
    if not secrets.available():
        raise SessionUnavailable(
            "MERIDIAN_SECRET_KEY is not configured, so Meridian cannot store a "
            "browser session. It will not hold one in plaintext."
        )

    try:
        parsed = json.loads(state_json)
    except (TypeError, ValueError) as exc:
        raise SessionUnavailable(
            "That does not look like a browser session. Expected the JSON "
            "storage state the capture tool produces."
        ) from exc

    if not isinstance(parsed, dict) or not (
        parsed.get("cookies") or parsed.get("origins")
    ):
        raise SessionUnavailable(
            "The session contains no cookies or origins, so it is not an "
            "authenticated session. Sign in fully before capturing."
        )

    # Supersede rather than accumulate.
    previous = live_session(db, connection_id)
    if previous is not None:
        previous.revoked_at = utcnow()
        previous.revoked_reason = "superseded by a newer capture"

    record = BrowserSessionRecord(
        id=new_id("bs"),
        connection_id=connection_id,
        workspace_id=workspace_id,
        state_encrypted=secrets.encrypt({"state": state_json}),
        captured_by=captured_by,
        captured_at=utcnow(),
        expires_at=utcnow() + ttl,
    )
    db.add(record)
    db.flush()
    return record


def state(db: Session, connection_id: str) -> str:
    """The decrypted session, for the replay runner only.

    The single place a session is readable. Every other path reports `status()`.
    """
    record = live_session(db, connection_id)
    if record is None:
        raise SessionUnavailable(
            "No Workday browser session has been captured for this connection. "
            "An administrator must sign in once using the capture tool."
        )
    payload = secrets.decrypt(record.state_encrypted)
    return str(payload.get("state") or "")


def mark_used(db: Session, connection_id: str) -> None:
    """Record that replay used this session.

    Distinguishes "captured and forgotten" from "captured and working" — the
    two look identical without it.
    """
    record = live_session(db, connection_id)
    if record is not None:
        record.last_used_at = utcnow()


def revoke(db: Session, connection_id: str, *, reason: str = "revoked") -> bool:
    """End the current session without deleting its history."""
    record = live_session(db, connection_id)
    if record is None:
        return False
    record.revoked_at = utcnow()
    record.revoked_reason = reason
    db.flush()
    return True


def status(db: Session, connection_id: str) -> SessionStatus:
    """What the UI may show about the session."""
    record = live_session(db, connection_id)
    if record is None:
        return SessionStatus(
            present=False,
            message=(
                "No session captured. Screen discovery is unavailable until an "
                "administrator signs in with the capture tool."
            ),
        )

    now = utcnow()
    expires = record.expires_at
    remaining = int((expires - now).total_seconds()) if expires else 0
    expired = bool(expires and remaining <= 0)
    soon = bool(
        expires and not expired and remaining <= LOW_REMAINING.total_seconds()
    )

    if expired:
        message = (
            f"Session captured by {record.captured_by or 'an administrator'} has "
            "expired. Capture a new one to resume screen discovery."
        )
    elif soon:
        message = (
            f"Session expires in about {max(remaining, 0) // 60} minute(s). "
            "Capture a new one before starting a long extraction."
        )
    else:
        message = (
            f"Session active, captured by "
            f"{record.captured_by or 'an administrator'}."
        )

    return SessionStatus(
        present=True,
        captured_by=record.captured_by,
        captured_at=record.captured_at.isoformat() if record.captured_at else "",
        expires_at=expires.isoformat() if expires else "",
        last_used_at=(
            record.last_used_at.isoformat() if record.last_used_at else ""
        ),
        remaining_seconds=remaining,
        expired=expired,
        expiring_soon=soon,
        message=message,
    )

"""
The audit ledger — server-authoritative.

This is the backend counterpart of `src/lib/audit.ts`, and the canonicalisation
below is a deliberate byte-for-byte port of `canonicalise()` there. The two must
agree: a chain seeded in the browser and continued on the server (or verified in
either place) has to produce identical hashes, and a field-ordering difference
would show up as a spurious tamper alarm rather than as an obvious bug.

Moving the ledger server-side changes one thing fundamentally. In the frontend
the chain was honest but unenforceable — anything running in the page could
rewrite it. Here the only exported mutation is `append`, the table has no update
path, and `seq` is unique, so an insert between two entries fails on the
constraint before hashes are even considered.

Concurrency: `append` serialises on the ledger's tail. Two simultaneous writers
would otherwise read the same head, compute the same `seq`, and produce a fork
where one entry's `prev_hash` points at a sibling rather than a parent. The
advisory lock below makes the read-compute-insert sequence atomic without
locking the whole table for readers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from api.core.ids import iso, new_id, utcnow
from api.domain import enums
from api.domain.governance import AuditEntry

# The anchor the first entry commits to.
GENESIS_HASH = "0" * 64

# Postgres advisory-lock key for ledger appends. Arbitrary but fixed; it only
# has to be distinct from other advisory locks the application takes.
_LEDGER_LOCK_KEY = 0x4D45_5249  # "MERI"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonicalise(entry: dict) -> str:
    """The exact bytes an entry commits to.

    Field order is fixed and explicit rather than derived from dict iteration,
    because key order would otherwise depend on construction order and two
    identical entries could hash differently.

    Every field that carries meaning is included. Omitting `changes` or
    `reason` would let someone rewrite the before-value of a record without
    breaking its hash — which would defeat the point of storing them.
    """
    changes = "".join(
        "".join([c.get("field", ""), c.get("before") or " ", c.get("after") or " "])
        for c in (entry.get("changes") or [])
    )

    ai_obj = entry.get("ai")
    ai = (
        "".join(
            [
                ai_obj.get("model", ""),
                ai_obj.get("modelVersion", ""),
                ai_obj.get("promptHash", ""),
                str(ai_obj.get("tokensIn", 0)),
                str(ai_obj.get("tokensOut", 0)),
                # JS `String(0.2)` is "0.2"; Python str(0.2) is also "0.2".
                # Formatted through the same helper as the frontend to keep
                # integral floats ("0" vs "0.0") from diverging.
                _js_number(ai_obj.get("temperature", 0)),
                ",".join(ai_obj.get("groundedNodeIds") or []),
            ]
        )
        if ai_obj
        else ""
    )

    return "".join(
        [
            str(entry["seq"]),
            entry["at"],
            entry["action"],
            entry["actor"],
            entry["actorType"],
            entry.get("requirementRef") or "",
            entry["summary"],
            entry["prevHash"],
            # `toFixed(4)` in JS — four decimal places, always.
            f"{float(entry.get('costUsd', 0)):.4f}",
            str(int(entry.get("durationSeconds", 0))),
            changes,
            entry.get("reason") or "",
            ai,
            entry["retention"],
            # JS `String(true)` is "true", not Python's "True".
            "true" if entry.get("legalHold") else "false",
            entry.get("workspaceId") or "",
        ]
    )


def _js_number(value: float | int) -> str:
    """Render a number the way JavaScript's `String()` would.

    JS prints 2.0 as "2" and 0.2 as "0.2"; Python prints "2.0" and "0.2". Only
    the integral case differs, and it differs silently — which is exactly the
    kind of mismatch that would make cross-checking a chain fail for a reason
    nobody could see.
    """
    f = float(value)
    return str(int(f)) if f.is_integer() else repr(f)


def _default_retention(action: str, has_ai: bool) -> str:
    """Which retention obligation an action falls under when unspecified.

    Approvals and closures are the SOX-relevant control points; anything an AI
    produced falls under the AI Act's six-month floor; incidents are kept
    permanently because their whole value is the long tail.
    """
    if action.startswith("incident."):
        return enums.RetentionClass.PERMANENT
    if (
        action.startswith("approval.")
        or action in {"closure.signed", "change.deployed", "access.granted"}
    ):
        return enums.RetentionClass.SOX
    if has_ai:
        return enums.RetentionClass.AI_ACT
    return enums.RetentionClass.STANDARD


@dataclass(slots=True)
class RecordInput:
    action: str
    actor: str
    actor_type: str
    summary: str
    requirement_ref: str | None = None
    cost_usd: float = 0.0
    duration_seconds: int = 0
    changes: list[dict] | None = None
    reason: str | None = None
    ai: dict | None = None
    retention: str | None = None
    legal_hold: bool = False
    workspace_id: str | None = None


def _wire(entry: AuditEntry, at: str) -> dict:
    """The dict shape `canonicalise` consumes, in frontend key names."""
    return {
        "seq": entry.seq,
        "at": at,
        "action": entry.action,
        "actor": entry.actor,
        "actorType": entry.actor_type,
        "requirementRef": entry.requirement_ref,
        "summary": entry.summary,
        "prevHash": entry.prev_hash,
        "costUsd": entry.cost_usd,
        "durationSeconds": entry.duration_seconds,
        "changes": entry.changes,
        "reason": entry.reason,
        "ai": entry.ai,
        "retention": entry.retention,
        "legalHold": entry.legal_hold,
        "workspaceId": entry.workspace_id,
    }


def append(db: Session, entry_input: RecordInput) -> AuditEntry:
    """Append one entry, deriving its hash from its content and its predecessor.

    Takes an advisory lock so concurrent writers cannot fork the chain. The
    lock is released when the transaction ends, so a caller that fails after
    this point rolls the entry back with everything else — an audit entry for
    an action that did not happen would be worse than a missing one.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LEDGER_LOCK_KEY})

    head = db.execute(
        select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1)
    ).scalar_one_or_none()

    prev_hash = head.hash if head else GENESIS_HASH
    seq = (head.seq if head else 0) + 1
    now = utcnow()

    entry = AuditEntry(
        id=new_id("au"),
        seq=seq,
        at=now,
        action=entry_input.action,
        actor=entry_input.actor,
        actor_type=entry_input.actor_type,
        requirement_ref=entry_input.requirement_ref,
        summary=entry_input.summary,
        prev_hash=prev_hash,
        hash="",  # replaced below, once the content is fixed
        cost_usd=entry_input.cost_usd,
        duration_seconds=entry_input.duration_seconds,
        changes=entry_input.changes,
        reason=entry_input.reason,
        ai=entry_input.ai,
        retention=entry_input.retention
        or _default_retention(entry_input.action, bool(entry_input.ai)),
        legal_hold=entry_input.legal_hold,
        workspace_id=entry_input.workspace_id,
    )

    # Hash the wire form, using the same ISO rendering the API will emit, so a
    # client recomputing from the response reaches the same digest.
    entry.hash = sha256(canonicalise(_wire(entry, iso(now))))

    db.add(entry)
    db.flush()
    return entry


@dataclass(slots=True)
class ChainVerification:
    valid: bool
    entries_checked: int
    verified_at: str
    first_broken_seq: int | None
    detail: str


def verify(db: Session, workspace_id: str | None = None) -> ChainVerification:
    """Recompute the whole chain and report the first break.

    Walks oldest-to-newest so `first_broken_seq` is genuinely the earliest
    point of divergence. Two distinct failures are detected: an entry whose
    stored hash no longer matches its content (it was edited), and an entry
    whose `prev_hash` does not match the actual predecessor (one was removed or
    reordered).

    Note the scope argument is accepted but verification always runs over the
    whole chain. A chain is a single sequence; verifying a filtered subset
    would report breaks at every workspace boundary and mean nothing.
    """
    verified_at = iso(utcnow())

    rows = list(db.execute(select(AuditEntry).order_by(AuditEntry.seq.asc())).scalars())

    if not rows:
        return ChainVerification(
            valid=True,
            entries_checked=0,
            verified_at=verified_at,
            first_broken_seq=None,
            detail="The chain is empty. Nothing to verify.",
        )

    for i, entry in enumerate(rows):
        expected_prev = entry.prev_hash if i == 0 else rows[i - 1].hash

        if entry.prev_hash != expected_prev:
            return ChainVerification(
                valid=False,
                entries_checked=i + 1,
                verified_at=verified_at,
                first_broken_seq=entry.seq,
                detail=(
                    f"Entry #{entry.seq} commits to a predecessor that is not the entry "
                    "before it. An entry has been removed or reordered."
                ),
            )

        recomputed = sha256(canonicalise(_wire(entry, iso(entry.at))))
        if recomputed != entry.hash:
            return ChainVerification(
                valid=False,
                entries_checked=i + 1,
                verified_at=verified_at,
                first_broken_seq=entry.seq,
                detail=(
                    f'Entry #{entry.seq} ("{entry.summary[:60]}…") does not match its stored '
                    "hash. Its content was altered after it was written, which invalidates "
                    "every entry after it."
                ),
            )

    return ChainVerification(
        valid=True,
        entries_checked=len(rows),
        verified_at=verified_at,
        first_broken_seq=None,
        detail=(
            f"All {len(rows)} entries recomputed and matched, "
            f"from #{rows[0].seq} to #{rows[-1].seq}."
        ),
    )


def head_seq(db: Session) -> int:
    return db.execute(select(func.coalesce(func.max(AuditEntry.seq), 0))).scalar_one()


def simulate_tamper(db: Session, seq: int) -> bool:
    """Corrupt one entry in place, for demonstration only.

    A tamper-evidence claim that cannot be shown failing is a marketing line.
    This edits the summary and leaves the hash untouched — exactly what someone
    editing the database directly would do.

    This is the only function in the codebase that mutates an audit row, it is
    reachable solely from a clearly-labelled demonstration endpoint, and it
    should be removed before the ledger holds anything real.
    """
    entry = db.execute(select(AuditEntry).where(AuditEntry.seq == seq)).scalar_one_or_none()
    if entry is None:
        return False
    entry.summary = f"{entry.summary} [altered]"
    db.flush()
    return True


def to_wire(entry: AuditEntry) -> dict:
    """Serialise for the frontend's `AuditEntry` interface."""
    return {
        "id": entry.id,
        "seq": entry.seq,
        "at": iso(entry.at),
        "action": entry.action,
        "actor": entry.actor,
        "actorType": entry.actor_type,
        "requirementRef": entry.requirement_ref,
        "summary": entry.summary,
        "hash": entry.hash,
        "prevHash": entry.prev_hash,
        "costUsd": entry.cost_usd,
        "durationSeconds": entry.duration_seconds,
        "changes": entry.changes,
        "reason": entry.reason,
        "ai": entry.ai,
        "retention": entry.retention,
        "legalHold": entry.legal_hold,
        "workspaceId": entry.workspace_id,
    }


def diff_fields(
    before: object, after: object, fields: list[tuple[str, str]]
) -> list[dict]:
    """Field-level diff between two versions of a record.

    Only the named fields are compared. Not every property change is
    governance-relevant: bumping `updated_at` on every save would bury the one
    edit that mattered under noise. The caller decides what counts.
    """

    def display(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) if value else "(empty)"
        if isinstance(value, datetime):
            return iso(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, dict):
            return str(value)
        s = str(value)
        return s if s else "(empty)"

    changes: list[dict] = []
    for field, label in fields:
        b = display(getattr(before, field, None))
        a = display(getattr(after, field, None))
        if b != a:
            changes.append({"field": field, "label": label, "before": b, "after": a})
    return changes

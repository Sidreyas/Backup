"""
Governance records: approvals, the audit ledger, AI incidents, policies.

The audit ledger is the spine of the product's central claim — that the record
of what happened cannot be altered without the alteration being detectable. Two
properties make that true rather than decorative, and both are enforced in
`api/ledger/chain.py` rather than here:

  1. Hashes are computed from content, never authored.
  2. Verification recomputes and compares, so an edited row fails, and so does
     every row after it.

What this file contributes is the storage guarantee: the table has no update
path in the application, and `seq` is unique so an entry cannot be quietly
inserted between two others.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.db import Base
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import TimestampMixin

JSON = JSONB


class ApprovalPackage(Base, TimestampMixin):
    __tablename__ = "approval_packages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ap"))
    requirement_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requirement_ref: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    submitted_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    # Recomputed from live evidence on read. Persisted as a cache for the list
    # view only — a stale count on an approval screen is a governance defect,
    # so `api/services/approvals.py` refreshes it rather than trusting it.
    evidence_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default=enums.Criticality.MEDIUM)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    gates: Mapped[list[ApprovalGate]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


class ApprovalGate(Base):
    """One sign-off point.

    `requires_evidence_grade` is the field that gives the verified/asserted
    distinction teeth: a gate demanding `verified` cannot be satisfied by an
    agent's claim, and that is checked server-side before a decision is
    accepted. A rule enforced only in the UI is a suggestion.
    """

    __tablename__ = "approval_gates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("gate"))
    package_id: Mapped[str] = mapped_column(
        ForeignKey("approval_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    requires_evidence_grade: Mapped[str | None] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(16), default=enums.ApprovalDecision.PENDING)
    approver: Mapped[str | None] = mapped_column(String(200))
    approver_email: Mapped[str | None] = mapped_column(String(320))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    blocked_by: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # A breached deadline is reported, never enforced. Auto-rejecting on a
    # missed SLA would replace a human decision with a timer, which is the
    # opposite of what a sign-off is for.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # EU AI Act Art. 14 evidence that the decision was meaningful rather than
    # nominal. Null while pending: there is no oversight to record until
    # someone has actually decided.
    oversight: Mapped[dict | None] = mapped_column(JSON)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    package: Mapped[ApprovalPackage] = relationship(back_populates="gates")


class AuditEntry(Base):
    """One link in the hash chain.

    There is deliberately no update path to this table anywhere in the
    application. `api/ledger/chain.py` exposes `append` and `verify` and
    nothing else; the tamper helper used by the demonstration endpoint is the
    single labelled exception.
    """

    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("au"))

    # Unique so an entry cannot be silently inserted between two others — a
    # gap or a duplicate is detectable even before hashes are recomputed.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    requirement_ref: Mapped[str | None] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    hash: Mapped[str] = mapped_column(String(80), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(80), nullable=False)

    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ALCOA+ / 21 CFR Part 11 §11.10(e): the prior value, not just the fact of
    # a change. "The test expectation was edited" and "the expectation was
    # weakened from X to Y" are different findings; only the second is
    # actionable.
    changes: Mapped[list | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)

    # EU AI Act Art. 12 — which system version produced this, and can it be
    # reproduced. Without the pinned version a silent model upgrade is
    # invisible in the history.
    ai: Mapped[dict | None] = mapped_column(JSON)

    retention: Mapped[str] = mapped_column(
        String(16), default=enums.RetentionClass.STANDARD, nullable=False, index=True
    )
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    __table_args__ = (
        UniqueConstraint("seq", name="uq_audit_seq"),
        Index("ix_audit_workspace_seq", "workspace_id", "seq"),
    )


class AiIncident(Base):
    """An incident in *Meridian's own AI*, not in the system under test.

    Defects record what the tested software got wrong. Nothing recorded what
    the platform got wrong — a fabricated citation, an impact analysis that
    missed a breaking change, an agent acting outside advisory mode. NIST AI
    RMF asks for incident disclosure and EU AI Act Art. 73 obliges providers to
    report serious incidents on a deadline, so this is a first-class register.
    """

    __tablename__ = "ai_incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("inc"))
    ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=enums.IncidentStatus.OPEN, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    detected_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    detection_method: Mapped[str] = mapped_column(String(32), default="human_review")
    affected_requirement_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    affected_artifact_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(64))

    # Reportability is a legal test, not a severity threshold — recorded as a
    # judgement with its rationale rather than derived from `severity`.
    reportable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reportable_rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)

    disclosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disclosed_to: Mapped[str | None] = mapped_column(String(300))
    corrective_action: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pol"))
    ref: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    scope: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    triggered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)


class CostEvent(Base):
    """Unit-economics ledger.

    Every LLM call, execution and environment hour writes a row. The analytics
    endpoints aggregate from here rather than from hardcoded series, which is
    what makes "cost per test case" and "cost per requirement" answerable
    instead of merely displayable.
    """

    __tablename__ = "cost_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ce"))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    requirement_id: Mapped[str | None] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(120), index=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    compute_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    detail: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

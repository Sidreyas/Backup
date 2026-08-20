"""
The Software Testing Life Cycle, persisted.

Every artefact here is authored by an agent and then reviewed by a human.
Nothing an agent produces is approved until someone signs it — the same rule
the graph applies to assertions and the evidence store applies to claims.

Criteria are a table rather than a JSON blob on the parent. They are the thing
closure is *evaluated* against, which means they get queried ("show me every
requirement blocked on an unmet exit criterion") and updated individually. A
JSON column would have made that a full-table scan and a read-modify-write.
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.db import Base
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import TimestampMixin

JSON = JSONB


class Criterion(Base):
    """An entry or exit condition.

    `met` is deliberately three-state: True, False, and None for "not yet
    evaluated". Defaulting an unevaluated criterion to False would make a
    closure look blocked when it is merely unchecked, and defaulting to True
    would let an unchecked condition satisfy a gate. Neither is acceptable, so
    the unknown is modelled.
    """

    __tablename__ = "criteria"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cr"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    met: Mapped[bool | None] = mapped_column(Boolean)
    evaluated_by: Mapped[str | None] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(Text)

    # Which parent this belongs to, and in what role. One table serves plans
    # (entry/exit), environments (readiness), executions (preflight) and
    # closures (exit) because the semantics are identical in all four.
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (Index("ix_criterion_owner", "owner_type", "owner_id", "role"),)


class TestPlan(Base, TimestampMixin):
    """STLC phase 2 — planning."""

    __tablename__ = "test_plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tp"))
    ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_ref: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), default=enums.ArtifactOrigin.AI_GENERATED)
    state: Mapped[str] = mapped_column(String(16), default=enums.ReviewState.DRAFT, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    author: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scope_in: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    scope_out: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    levels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    risks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    covered_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Nodes impact analysis flagged that this plan does NOT cover. Stored
    # rather than derived so the gap is visible on the plan itself, where the
    # person deciding whether to approve it is looking.
    uncovered_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    environment_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    estimated_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_duration_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    generation_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class TestCase(Base, TimestampMixin):
    """STLC phase 3 — test case development."""

    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tc"))
    ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("test_plans.id", ondelete="SET NULL"), index=True
    )
    requirement_id: Mapped[str | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), default=enums.ArtifactOrigin.AI_GENERATED)
    state: Mapped[str] = mapped_column(String(16), default=enums.ReviewState.DRAFT, index=True)
    level: Mapped[str] = mapped_column(String(16), default=enums.TestLevel.SYSTEM)
    type: Mapped[str] = mapped_column(String(24), default=enums.TestType.FUNCTIONAL)
    priority: Mapped[str] = mapped_column(String(16), default=enums.Criticality.MEDIUM)

    # Whether this case can run deterministically. Drives EvidenceGrade at
    # execution: a non-automatable case can only ever produce an assertion.
    automatable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    preconditions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    test_data: Mapped[str] = mapped_column(Text, default="", nullable=False)
    covers_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    author: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Scored assessment. Absent on human-authored cases: there is nothing to
    # audit about a person's judgement that the person did not already sign,
    # and scoring their work with a model would invert the accountability.
    rubric: Mapped[dict | None] = mapped_column(JSON)


class TestSuite(Base):
    """A named, ordered selection of cases.

    Stores case ids rather than a snapshot of the cases: a suite means "these
    tests", and if a case is later corrected the suite should run the corrected
    version. Freezing copies would re-run superseded tests and produce evidence
    for a case that no longer exists.
    """

    __tablename__ = "test_suites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ts"))
    ref: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    case_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    saved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)


class TestEnvironment(Base):
    """STLC phase 4 — environment.

    Long-lived and shared, so modelled as a precondition checked at execution
    time rather than a wizard step repeated per requirement.
    """

    __tablename__ = "test_environments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("env"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="sandbox")
    platform: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=enums.EnvironmentStatus.READY)

    # The fingerprint travels onto every execution and run performed here, so
    # evidence stays interpretable after the environment is refreshed out from
    # under it. Copied, not referenced, for exactly that reason.
    fingerprint: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owned_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    hourly_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)


class TestExecution(Base):
    """STLC phase 5 — one run of a suite in one environment."""

    __tablename__ = "test_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("te"))
    ref: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    requirement_id: Mapped[str | None] = mapped_column(String(64), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(64), index=True)
    suite_id: Mapped[str | None] = mapped_column(String(64))
    suite_name: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    environment_id: Mapped[str | None] = mapped_column(String(64))
    environment: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=enums.ExecutionStatus.QUEUED, index=True)
    triggered_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    triggered_by_type: Mapped[str] = mapped_column(String(16), default=enums.ActorType.HUMAN)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    results: Mapped[list[CaseResult]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class CaseResult(Base):
    """Per-case outcome — the expected-vs-actual record.

    `expected` and `actual` are stored as text on the result rather than read
    back from the case, because a case edited after a run would otherwise
    rewrite the history of what that run proved.
    """

    __tablename__ = "case_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cres"))
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("test_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str | None] = mapped_column(String(64), index=True)
    case_ref: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    case_title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=enums.RunStatus.QUEUED)
    grade: Mapped[str] = mapped_column(String(16), default=enums.EvidenceGrade.ASSERTED)
    expected: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actual: Mapped[str] = mapped_column(Text, default="", nullable=False)
    deviation: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    covers_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    defect_ref: Mapped[str | None] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    execution: Mapped[TestExecution] = relationship(back_populates="results")


class TestRun(Base):
    """Evidence-page view of a run.

    Distinct from TestExecution: an execution is an orchestrated run of a suite
    inside Meridian, while a TestRun is any evidence-bearing run including ones
    imported from an external CI system that Meridian did not orchestrate.
    """

    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("run"))
    ref: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    requirement_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    grade: Mapped[str] = mapped_column(String(16), default=enums.EvidenceGrade.ASSERTED, index=True)
    status: Mapped[str] = mapped_column(String(16), default=enums.RunStatus.QUEUED)
    suite: Mapped[str | None] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    flake_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    runner: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    environment: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    covered_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)


class Defect(Base):
    """STLC phase 5b — raised from a failed or deviating result.

    `fixed` and `closed` are distinct states. A developer marking something
    fixed is a claim; only a passing re-test turns that claim into a closed
    defect. Collapsing the two would let an unverified assertion satisfy a
    closure gate, which is the exact failure this product exists to prevent.
    """

    __tablename__ = "defects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("def"))
    ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    requirement_id: Mapped[str | None] = mapped_column(String(64), index=True)
    execution_id: Mapped[str | None] = mapped_column(String(64), index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), index=True)
    case_ref: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # Copied at raise time so the defect stays readable even if the case is
    # later edited.
    expected: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actual: Mapped[str] = mapped_column(Text, default="", nullable=False)

    severity: Mapped[str] = mapped_column(String(16), default=enums.ImpactSeverity.MINOR)
    status: Mapped[str] = mapped_column(String(16), default=enums.DefectStatus.OPEN, index=True)
    owner: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    raised_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    raised_by_type: Mapped[str] = mapped_column(String(32), default=enums.ArtifactOrigin.HUMAN_AUTHORED)
    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    notes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    retest_execution_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    verified_by_execution_id: Mapped[str | None] = mapped_column(String(64))
    affected_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)


class TestClosure(Base):
    """STLC phase 6 — evaluated, not declared."""

    __tablename__ = "test_closures"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tcl"))
    requirement_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requirement_ref: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String(64))
    execution_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=enums.ClosureState.OPEN, index=True)
    closed_by: Mapped[str | None] = mapped_column(String(200))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Recomputed on read rather than trusted from the last write — see
    # api/services/closure.py. Persisted only as a cache for list views.
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    open_defects: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    residual_risks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    lessons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_duration_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

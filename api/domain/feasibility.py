"""
Feasibility assessments.

A requirement is not actionable because someone believes it is. It is actionable
when three separate conditions hold, each checkable:

  1. The request is understood — nothing material is still being guessed at.
  2. The configuration it touches is in the graph, and fresh enough to trust.
  3. Meridian can make the change in the system that owns that configuration.

These tables record the answer and, more importantly, the *reasons*. A stored
verdict with no gaps attached would be an opinion; a verdict alongside the
specific things that were missing is something a reviewer can disagree with
precisely.

Why the verdict is a column rather than a computed property: an assessment is a
point-in-time claim about a world that keeps moving. A permission granted
tomorrow should not silently rewrite yesterday's refusal — it should produce a
new assessment. The history of what Meridian refused, and why, is part of the
audit story rather than a cache to be invalidated.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
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


class FeasibilityAssessment(Base, TimestampMixin):
    __tablename__ = "feasibility_assessments"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: new_id("feas")
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    intent: Mapped[str] = mapped_column(
        String(16), default=enums.ChangeIntent.UNCLEAR, nullable=False
    )
    verdict: Mapped[str] = mapped_column(
        String(16),
        default=enums.FeasibilityVerdict.INCOMPLETE,
        nullable=False,
        index=True,
    )

    # The request in Meridian's own words, for the requester to correct. A
    # restatement they can disagree with catches a misreading before it becomes
    # an approved plan, which is far cheaper than catching it afterwards.
    understood_as: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # The nodes the change was resolved to. Empty is meaningful: it says the
    # graph holds nothing matching the request, which is a DATA gap rather than
    # a question for the requester.
    target_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Systems that would have to be written to, derived from where the target
    # nodes came from. Never inferred from the request text: a change lands in
    # whichever system owns the configuration, and that is recorded on the node.
    owning_connection_ids: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False
    )

    # Questions asked this round, and the ceiling in force when they were
    # chosen. Recorded because the ceiling is adjustable, and an adjustment
    # nobody can see afterwards is indistinguishable from having no ceiling.
    question_budget: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    budget_raised_to: Mapped[int | None] = mapped_column(Integer)
    budget_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Set when no model was configured and the deterministic path produced this
    # assessment, so nothing downstream reads a placeholder as reasoning.
    source: Mapped[str] = mapped_column(String(16), default="llm", nullable=False)

    # Questions the model returned that referenced something outside the
    # retrieved context. Dropped, and kept here: a question about a field that
    # does not exist would send the requester looking for it.
    discarded: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    gaps: Mapped[list[FeasibilityGap]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="FeasibilityGap.position",
    )
    questions: Mapped[list[ClarificationQuestion]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="ClarificationQuestion.position",
    )

    @property
    def blocking_gaps(self) -> list[FeasibilityGap]:
        return [g for g in self.gaps if g.blocking]

    @property
    def is_feasible(self) -> bool:
        """Whether this assessment permits action.

        Derived from the stored verdict rather than recomputed from the gaps: the
        gate must agree with what was recorded and shown to the user, not with a
        fresh opinion formed at the moment someone tried to proceed.
        """
        return self.verdict == enums.FeasibilityVerdict.FEASIBLE


class FeasibilityGap(Base):
    """One specific reason a requirement is not yet actionable."""

    __tablename__ = "feasibility_gaps"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: new_id("fgap")
    )
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("feasibility_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    # One line, addressed to whoever has to act on it.
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # What to do about it. A gap without a remedy is a complaint — the value of
    # naming the missing scope is that someone can go and grant it.
    remedy: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # What the gap is about: a connection id, a node id, a scope name. Lets the
    # UI link the gap to the thing rather than making the user search for it.
    subject: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    # False for a gap worth stating that does not by itself stop the work —
    # configuration slightly past its staleness threshold, say. Blocking gaps
    # are the ones the gate refuses on.
    blocking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # What could go wrong if this were ignored. Populated for blocking gaps so a
    # refusal can explain the risk rather than only asserting the rule.
    risk: Mapped[str] = mapped_column(Text, default="", nullable=False)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    assessment: Mapped[FeasibilityAssessment] = relationship(back_populates="gaps")


class ClarificationQuestion(Base):
    """One question put to the requester, and their answer.

    Options come from the graph rather than from the model's imagination. A
    question offering four candidates that all exist in the tenant is answerable
    in a click; an open question hands Meridian's work back to the requester.

    `answered_as` keeps the answer beside the question that prompted it, so the
    exchange behind an approved plan can be read back later without
    reconstructing it from chat.
    """

    __tablename__ = "clarification_questions"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: new_id("cq")
    )
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("feasibility_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Why this is being asked. Shown to the requester, because "why do you need
    # to know" is the first thing anyone thinks when interrogated by software.
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Candidate answers, each drawn from retrieved configuration.
    options: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # The node id or attribute key this question is about. Used to check the
    # question against what was actually retrieved.
    about: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    answered_as: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Set when the requester accepts the unknown rather than resolving it. Kept
    # distinct from an answer: proceeding on a stated assumption is a decision
    # someone made, and the approval record should show that it was made.
    accepted_unknown: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    assessment: Mapped[FeasibilityAssessment] = relationship(
        back_populates="questions"
    )

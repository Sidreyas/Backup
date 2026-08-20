"""
The feasibility gate.

One rule, enforced here rather than in a prompt or the UI: a requirement does not
advance to an acting stage unless a feasibility assessment says it can.

Why this file exists at all, when the same check could live in the router: the
rule has to hold for every path that moves a requirement forward — the API, a
future scheduler, a bulk import — and a check written once per caller is a check
that is eventually forgotten by one of them. `require_feasible` is the only way
past, and it takes no force argument.

There is deliberately no override. A flag that skips the gate makes the gate
decorative, and the moment it would be used is precisely the moment it matters:
someone senior is impatient, the change looks small, and the missing permission
is "probably fine". What Meridian offers instead of an override is a legible
refusal — every gap, its remedy, and the specific risk of ignoring it — so the
decision to go around Meridian is made outside Meridian, by a person, on the
record.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from api.agents import feasibility as feasibility_agent
from api.domain import enums
from api.domain.feasibility import FeasibilityAssessment
from api.domain.models import Requirement

#: Stages that mean something is about to happen, or that someone is about to be
#: asked to endorse it.
#:
#: AWAITING_APPROVAL is included on purpose. Sending an infeasible plan to an
#: approver spends their attention on a decision that cannot be honoured, and it
#: trains them to approve without reading — which costs more than the delay.
ACTING_STAGES: frozenset[str] = frozenset(
    {
        enums.RequirementStage.AWAITING_APPROVAL,
        enums.RequirementStage.BUILDING,
        enums.RequirementStage.EVIDENCE,
        enums.RequirementStage.SIGNED_OFF,
    }
)


class NotFeasible(Exception):
    """Raised when a requirement cannot advance.

    Carries the assessment rather than a message, so every caller can render the
    same gaps, remedies and risks. A refusal reduced to a sentence loses the part
    that makes it actionable.
    """

    def __init__(
        self, requirement: Requirement, stage: str, assessment: FeasibilityAssessment | None
    ) -> None:
        self.requirement = requirement
        self.stage = stage
        self.assessment = assessment
        super().__init__(self.headline())

    def headline(self) -> str:
        if self.assessment is None:
            return (
                f"{self.requirement.ref} has not been assessed for feasibility, so it "
                f"cannot move to {self.stage}."
            )
        if self.assessment.verdict == enums.FeasibilityVerdict.BLOCKED:
            return (
                f"{self.requirement.ref} is blocked: something outside this "
                f"conversation has to change before it can move to {self.stage}."
            )
        return (
            f"{self.requirement.ref} is not fully understood yet, so it cannot move "
            f"to {self.stage}."
        )

    def detail(self) -> dict:
        """The refusal, in full, for an API response or a chat reply."""
        assessment = self.assessment
        return {
            "requirementRef": self.requirement.ref,
            "attemptedStage": self.stage,
            "headline": self.headline(),
            "verdict": assessment.verdict if assessment else None,
            "assessmentId": assessment.id if assessment else None,
            "gaps": [
                {
                    "kind": g.kind,
                    "summary": g.summary,
                    "remedy": g.remedy,
                    "risk": g.risk,
                    "subject": g.subject,
                }
                for g in (assessment.blocking_gaps if assessment else [])
            ],
            "openQuestions": [
                {"id": q.id, "text": q.text, "rationale": q.rationale, "options": q.options}
                for q in (assessment.questions if assessment else [])
                if not q.answered_as and not q.accepted_unknown
            ],
        }


def requires_feasibility(stage: str) -> bool:
    return stage in ACTING_STAGES


def require_feasible(db: Session, requirement: Requirement, stage: str) -> None:
    """Permit the move, or raise.

    Reads the recorded verdict rather than reassessing. Two reasons: the user was
    shown a specific assessment and the gate must agree with it, and a check that
    silently re-ran would let a stage change turn into a model call whose cost and
    latency nobody asked for.
    """
    if not requires_feasibility(stage):
        return

    assessment = feasibility_agent.latest(db, requirement.id)
    if assessment is None or not assessment.is_feasible:
        raise NotFeasible(requirement, stage, assessment)

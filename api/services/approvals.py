"""
Approval gates — where the evidence-grade rule is enforced.

In the frontend prototype the verified/asserted distinction was displayed. Here
it is *checked*. A gate carrying `requires_evidence_grade = 'verified'` cannot
be approved while the requirement's evidence is only asserted, and the attempt
is refused server-side with the reason.

That difference is the point of moving this to a backend at all. A rule
enforced only in the UI is a suggestion: anyone with a terminal can approve
past it, and the audit trail then records a decision the product's own policy
said was impossible.

Two further rules live here:

  - **Evidence is recomputed, never trusted.** The summary counts on the
    package are a cache for list views; every decision re-derives them from the
    actual runs, because a stale count on an approval screen is a governance
    defect rather than a display bug.

  - **Oversight is recorded with the decision, not inferred later.** Art. 14
    asks whether oversight was effective *at the moment it was exercised*.
    Reconstructing that afterwards from access logs would be a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.ids import iso, utcnow
from api.domain import enums
from api.domain.governance import ApprovalGate, ApprovalPackage
from api.domain.stlc import Defect, TestRun


class GateBlocked(Exception):
    """A gate cannot be decided as requested.

    Carries the reasons so the API can return them and the user can see what
    would have to change, rather than a bare refusal.
    """

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(slots=True)
class EvidenceSummary:
    verified: int
    asserted: int
    failed: int
    coverage_gaps: int

    def as_dict(self) -> dict:
        return {
            "verified": self.verified,
            "asserted": self.asserted,
            "failed": self.failed,
            "coverageGaps": self.coverage_gaps,
        }


def summarise_evidence(db: Session, requirement_id: str) -> EvidenceSummary:
    """Count the evidence actually on record for a requirement.

    Only passing runs count toward verified or asserted. A failed run is
    evidence of a problem, not evidence of correctness, and folding it into
    either bucket would let a failure argue for approval.
    """
    runs = list(
        db.execute(select(TestRun).where(TestRun.requirement_id == requirement_id)).scalars()
    )

    verified = sum(
        1
        for r in runs
        if r.grade == enums.EvidenceGrade.VERIFIED and r.status == enums.RunStatus.PASSED
    )
    asserted = sum(
        1
        for r in runs
        if r.grade == enums.EvidenceGrade.ASSERTED and r.status == enums.RunStatus.PASSED
    )
    failed = sum(1 for r in runs if r.status == enums.RunStatus.FAILED)

    from api.domain.models import ImpactAnalysis, ImpactItem

    gaps = (
        db.execute(
            select(ImpactItem)
            .join(ImpactAnalysis, ImpactItem.analysis_id == ImpactAnalysis.id)
            .where(
                ImpactAnalysis.requirement_id == requirement_id,
                ImpactItem.coverage_gap.is_(True),
            )
        )
        .scalars()
        .all()
    )

    return EvidenceSummary(
        verified=verified, asserted=asserted, failed=failed, coverage_gaps=len(gaps)
    )


def evaluate_blockers(
    db: Session, package: ApprovalPackage, gate: ApprovalGate
) -> list[str]:
    """Everything standing between this gate and an approval.

    Returned as prose because the list is shown to the person who has to act on
    it. "requires_evidence_grade" means nothing to a finance director;
    "this gate requires verified evidence and none exists" does.
    """
    reasons: list[str] = []
    summary = summarise_evidence(db, package.requirement_id)

    if gate.requires_evidence_grade == enums.EvidenceGrade.VERIFIED:
        if summary.verified == 0:
            reasons.append(
                "This gate requires verified evidence — a deterministic, replayable "
                "test with artifacts. None exists for this requirement; there "
                f"{'is' if summary.asserted == 1 else 'are'} {summary.asserted} "
                "asserted result(s), which cannot satisfy it."
            )

    if summary.failed:
        reasons.append(
            f"{summary.failed} test run(s) failed and have not been superseded by a "
            "passing re-run."
        )

    blocking_defects = list(
        db.execute(
            select(Defect).where(
                Defect.requirement_id == package.requirement_id,
                Defect.status.in_(
                    [
                        enums.DefectStatus.OPEN,
                        enums.DefectStatus.IN_PROGRESS,
                        # 'fixed' still blocks: a fix claimed is not a fix proven.
                        # Only a passing re-test closes a defect.
                        enums.DefectStatus.FIXED,
                    ]
                ),
                Defect.severity.in_(
                    [enums.ImpactSeverity.BREAKING, enums.ImpactSeverity.MAJOR]
                ),
            )
        ).scalars()
    )
    if blocking_defects:
        refs = ", ".join(d.ref for d in blocking_defects[:5])
        reasons.append(
            f"{len(blocking_defects)} unclosed breaking/major defect(s) remain: {refs}."
        )

    # Policy-authored blockers already recorded on the gate.
    reasons.extend(gate.blocked_by or [])

    return reasons


def decide(
    db: Session,
    *,
    package_id: str,
    gate_id: str,
    decision: str,
    comment: str,
    oversight: dict,
    actor_name: str,
    actor_email: str,
) -> ApprovalPackage:
    """Record a gate decision, refusing an approval that policy forbids.

    A *rejection* is never blocked. Blockers are reasons a change is not safe
    to approve; refusing to let someone reject it because of them would be
    incoherent, and would trap a package that should be sent back.
    """
    package = db.get(ApprovalPackage, package_id)
    if package is None:
        raise KeyError("Approval package not found")

    # Queried directly rather than scanned out of `package.gates`. That
    # collection can be a stale cached load within the same session, so a gate
    # added earlier in this transaction would not be found — and the caller
    # would see "Gate not found" for a gate that demonstrably exists.
    gate = db.execute(
        select(ApprovalGate).where(
            ApprovalGate.id == gate_id, ApprovalGate.package_id == package_id
        )
    ).scalar_one_or_none()
    if gate is None:
        raise KeyError("Gate not found")

    if decision == enums.ApprovalDecision.APPROVED:
        reasons = evaluate_blockers(db, package, gate)
        if reasons:
            raise GateBlocked(reasons)

        if oversight.get("overridden") and not oversight.get("overrideRationale"):
            # Art. 14: an override without a stated reason is not oversight.
            raise GateBlocked(
                [
                    "Overriding the system's recommendation requires a written "
                    "rationale."
                ]
            )

    gate.decision = decision
    gate.approver = actor_name
    gate.approver_email = actor_email
    gate.decided_at = utcnow()
    gate.comment = comment
    gate.oversight = oversight

    package.evidence_summary = summarise_evidence(db, package.requirement_id).as_dict()

    db.flush()
    return package


def refresh_summaries(db: Session) -> None:
    """Recompute every package's cached evidence counts."""
    for package in db.execute(select(ApprovalPackage)).scalars():
        package.evidence_summary = summarise_evidence(db, package.requirement_id).as_dict()
    db.flush()


def oversight_record(
    *,
    review_duration_seconds: int,
    artifacts_opened: list[str],
    artifacts_available: int,
    ai_recommendation: str,
    human_decision: str,
    override_rationale: str | None,
) -> dict:
    """Build the Art. 14 record.

    `overridden` is derived rather than accepted from the caller: whether a
    human went against the recommendation is a fact about the two values, not a
    claim the client gets to make.
    """
    overridden = ai_recommendation in {"approve", "reject"} and (
        ai_recommendation != human_decision
    )
    return {
        "reviewDurationSeconds": review_duration_seconds,
        "artifactsOpened": artifacts_opened,
        "artifactsAvailable": artifacts_available,
        "aiRecommendation": ai_recommendation,
        "humanDecision": human_decision,
        "overridden": overridden,
        "overrideRationale": override_rationale,
        "recordedAt": iso(utcnow()),
    }

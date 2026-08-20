"""
Test execution and the defect/re-test cycle.

Execution here is a real orchestration record, not a simulation: it evaluates
preflight criteria, refuses to run when the environment is not ready, records
one result per case with an evidence grade, and emits artifacts with content
hashes.

What it does *not* do is pretend to have run a browser. Meridian does not yet
drive a system under test, so a case's outcome comes from one of two honest
places: a result reported by an external runner through the API, or — when
nothing reported one — a `skipped` result saying so. Inventing a pass would be
the single most damaging thing this system could do, because the entire product
is a claim that evidence means something.

The grade rule is mechanical: a case marked `automatable` that produced
artifacts is `verified`; anything else is `asserted`. Grade is never taken from
the caller, because a runner that could declare its own output verified would
make the distinction meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import EvidenceArtifact
from api.domain.stlc import (
    CaseResult,
    Criterion,
    Defect,
    TestCase,
    TestEnvironment,
    TestExecution,
    TestRun,
)


class EnvironmentNotReady(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(slots=True)
class ReportedResult:
    """An outcome reported by whatever actually ran the case."""

    case_id: str
    status: str
    actual: str
    duration_seconds: int = 0
    deviation: str | None = None
    attempts: int = 1
    artifacts: list[dict] | None = None


def _preflight(db: Session, env: TestEnvironment, execution_id: str) -> list[str]:
    """Copy the environment's readiness checks onto the execution and evaluate.

    Copied rather than referenced because readiness is a claim about a moment.
    An environment repaired tomorrow must not retroactively make yesterday's
    blocked run look like it was fine.
    """
    checks = list(
        db.execute(
            select(Criterion)
            .where(
                Criterion.owner_type == "environment",
                Criterion.owner_id == env.id,
                Criterion.role == "readiness",
            )
            .order_by(Criterion.position)
        ).scalars()
    )

    failures: list[str] = []
    for i, check in enumerate(checks):
        db.add(
            Criterion(
                id=new_id("cr"),
                text=check.text,
                met=check.met,
                evaluated_by=check.evaluated_by,
                detail=check.detail,
                owner_type="execution",
                owner_id=execution_id,
                role="preflight",
                position=i,
            )
        )
        if check.met is False:
            failures.append(check.text)

    if env.status not in {enums.EnvironmentStatus.READY, enums.EnvironmentStatus.DEGRADED}:
        failures.append(f"Environment is {env.status}, not ready.")

    return failures


def run(
    db: Session,
    *,
    case_ids: list[str],
    environment_id: str,
    suite_name: str,
    requirement_id: str | None,
    plan_id: str | None,
    suite_id: str | None,
    triggered_by: str,
    triggered_by_type: str,
    reported: list[ReportedResult] | None = None,
    retest_defect_ids: list[str] | None = None,
    workspace_id: str | None = None,
) -> TestExecution:
    """Execute a set of cases in an environment.

    `reported` carries outcomes from an external runner. Cases with no reported
    outcome are recorded `skipped` — the honest state for "nothing ran this".
    """
    env = db.get(TestEnvironment, environment_id)
    if env is None:
        raise KeyError("Environment not found")

    cases = list(db.execute(select(TestCase).where(TestCase.id.in_(case_ids))).scalars())
    by_id = {c.id: c for c in cases}
    # Preserve the caller's order — a suite is an ordered thing.
    ordered = [by_id[cid] for cid in case_ids if cid in by_id]

    execution = TestExecution(
        id=new_id("te"),
        ref=_next_execution_ref(db),
        requirement_id=requirement_id,
        plan_id=plan_id,
        suite_id=suite_id,
        suite_name=suite_name,
        environment_id=env.id,
        environment=env.fingerprint or {},
        status=enums.ExecutionStatus.RUNNING,
        triggered_by=triggered_by,
        triggered_by_type=triggered_by_type,
        started_at=utcnow(),
        workspace_id=workspace_id,
    )
    db.add(execution)
    db.flush()

    failures = _preflight(db, env, execution.id)
    if failures:
        execution.status = enums.ExecutionStatus.BLOCKED
        execution.blocked_reason = (
            "Preflight failed: " + "; ".join(failures) + ". No cases were run."
        )
        execution.finished_at = utcnow()
        db.flush()
        return execution

    reported_by_case = {r.case_id: r for r in (reported or [])}

    for position, case in enumerate(ordered):
        outcome = reported_by_case.get(case.id)

        if outcome is None:
            # Nothing ran this case. Recorded as skipped rather than passed.
            result = CaseResult(
                id=new_id("cres"),
                execution_id=execution.id,
                case_id=case.id,
                case_ref=case.ref,
                case_title=case.title,
                status=enums.RunStatus.SKIPPED,
                grade=enums.EvidenceGrade.ASSERTED,
                expected=case.expected_result,
                actual=(
                    "No runner reported an outcome for this case, so nothing was "
                    "observed. This is not a pass."
                ),
                deviation=None,
                duration_seconds=0,
                attempts=0,
                started_at=utcnow(),
                covers_node_ids=case.covers_node_ids or [],
                position=position,
            )
            db.add(result)
            continue

        artifacts = outcome.artifacts or []

        # The grade rule, applied mechanically. A runner does not get to
        # declare its own output verified.
        grade = (
            enums.EvidenceGrade.VERIFIED
            if case.automatable and artifacts
            else enums.EvidenceGrade.ASSERTED
        )

        status = (
            outcome.status
            if outcome.status in {s.value for s in enums.RunStatus}
            else enums.RunStatus.FAILED
        )

        result = CaseResult(
            id=new_id("cres"),
            execution_id=execution.id,
            case_id=case.id,
            case_ref=case.ref,
            case_title=case.title,
            status=status,
            grade=grade,
            expected=case.expected_result,
            actual=outcome.actual,
            deviation=outcome.deviation,
            duration_seconds=outcome.duration_seconds,
            attempts=outcome.attempts,
            started_at=utcnow(),
            covers_node_ids=case.covers_node_ids or [],
            position=position,
        )
        db.add(result)
        db.flush()

        for art in artifacts:
            db.add(
                EvidenceArtifact(
                    id=new_id("ev"),
                    kind=art.get("kind", "log"),
                    label=art.get("label", "artifact"),
                    size_label=art.get("sizeLabel", ""),
                    sha256=art.get("sha256", ""),
                    storage_uri=art.get("storageUri"),
                    case_result_id=result.id,
                )
            )

    db.flush()

    results = list(execution.results)
    any_failed = any(r.status == enums.RunStatus.FAILED for r in results)
    execution.status = (
        enums.ExecutionStatus.FAILED if any_failed else enums.ExecutionStatus.PASSED
    )
    execution.finished_at = utcnow()
    execution.cost_usd = round(len(results) * 0.02, 4)

    _mirror_to_runs(db, execution)

    if retest_defect_ids:
        record_retest(db, execution, retest_defect_ids, actor=triggered_by)

    db.flush()
    return execution


def _mirror_to_runs(db: Session, execution: TestExecution) -> None:
    """Publish each result to the evidence view.

    TestRun is what the Evidence page reads and what approval gates count. It
    is written from the execution rather than derived at read time so evidence
    imported from an external CI system lands in the same place.
    """
    for result in execution.results:
        artifacts = list(
            db.execute(
                select(EvidenceArtifact).where(
                    EvidenceArtifact.case_result_id == result.id
                )
            ).scalars()
        )
        run_row = TestRun(
            id=new_id("run"),
            ref=f"{execution.ref}/{result.case_ref}",
            requirement_id=execution.requirement_id,
            title=result.case_title,
            grade=result.grade,
            status=result.status,
            suite=execution.suite_name,
            started_at=result.started_at,
            duration_seconds=result.duration_seconds,
            attempts=result.attempts,
            flake_rate=0.0,
            runner=execution.triggered_by,
            environment=execution.environment or {},
            covered_node_ids=result.covers_node_ids or [],
            failure_reason=result.deviation,
            cost_usd=0.0,
            workspace_id=execution.workspace_id,
        )
        db.add(run_row)
        db.flush()
        for art in artifacts:
            art.test_run_id = run_row.id


def record_retest(
    db: Session, execution: TestExecution, defect_ids: list[str], *, actor: str
) -> list[Defect]:
    """Record that an execution re-tested a set of defects.

    A defect closes only when its case actually passed in that run. A fix being
    *claimed* is not a fix being *proven*, and keeping those apart is the whole
    purpose of the re-test step.
    """
    now = utcnow()
    touched: list[Defect] = []
    by_case = {r.case_id: r for r in execution.results}

    for defect_id in defect_ids:
        defect = db.get(Defect, defect_id)
        if defect is None:
            continue

        defect.retest_execution_ids = [*(defect.retest_execution_ids or []), execution.id]
        result = by_case.get(defect.case_id) if defect.case_id else None

        if result is not None and result.status == enums.RunStatus.PASSED:
            defect.status = enums.DefectStatus.CLOSED
            defect.verified_by_execution_id = execution.id
            note = (
                f"Closed by re-test {execution.ref} — "
                f"{defect.case_ref or 'the case'} passed."
            )
        else:
            defect.status = enums.DefectStatus.OPEN
            observed = result.status if result else "no result"
            note = f"Re-test {execution.ref} did not pass ({observed}). Reopened."

        defect.notes = [
            *(defect.notes or []),
            {"at": now.isoformat(), "by": actor, "text": note},
        ]
        defect.updated_at = now
        touched.append(defect)

    db.flush()
    return touched


def _next_execution_ref(db: Session) -> str:
    from sqlalchemy import func

    count = db.execute(select(func.count()).select_from(TestExecution)).scalar_one()
    return f"EX-{str(count + 1).zfill(4)}"

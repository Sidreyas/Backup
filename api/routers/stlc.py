"""
STLC endpoints: plans, cases, suites, environments, executions, defects, closure.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.agents import testgen
from api.core.db import get_db
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import EvidenceArtifact, ImpactAnalysis, Requirement
from api.domain.stlc import (
    CaseResult,
    Defect,
    TestCase,
    TestClosure,
    TestEnvironment,
    TestExecution,
    TestPlan,
    TestRun,
    TestSuite,
)
from api.ledger import chain
from api.routers.deps import Actor, current_actor, current_workspace
from api.schemas import wire
from api.services import execution as execution_service

router = APIRouter(tags=["stlc"])


def _artifacts_for_results(db: Session, result_ids: list[str]) -> dict[str, list[dict]]:
    if not result_ids:
        return {}
    rows = db.execute(
        select(EvidenceArtifact).where(EvidenceArtifact.case_result_id.in_(result_ids))
    ).scalars()
    out: dict[str, list[dict]] = {}
    for a in rows:
        out.setdefault(a.case_result_id, []).append(wire.artifact(a))
    return out


# ------------------------------------------------------------------- plans


@router.get("/test-plans")
def list_plans(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(TestPlan).order_by(TestPlan.created_at.desc())).scalars()
    return [wire.test_plan(db, p) for p in rows]


@router.get("/test-plans/{plan_id}")
def get_plan(plan_id: str, db: Session = Depends(get_db)) -> dict | None:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        plan = db.execute(
            select(TestPlan).where(TestPlan.requirement_id == plan_id).limit(1)
        ).scalar_one_or_none()
    return wire.test_plan(db, plan) if plan else None


class StateChange(BaseModel):
    state: str
    reason: str | None = None


@router.patch("/test-plans/{plan_id}/state")
def set_plan_state(
    plan_id: str,
    body: StateChange,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    if body.state not in {s.value for s in enums.ReviewState}:
        raise HTTPException(status_code=422, detail=f"Unknown state: {body.state}")

    before_state, before_approver = plan.state, plan.approved_by
    plan.state = body.state
    plan.updated_at = utcnow()
    approved = body.state == enums.ReviewState.APPROVED
    plan.approved_by = actor.name if approved else None
    plan.approved_at = utcnow() if approved else None

    chain.append(
        db,
        chain.RecordInput(
            action="plan.state_changed",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=plan.requirement_ref,
            summary=f"{plan.ref} {'approved' if approved else f'moved to {body.state}'}.",
            changes=[
                {
                    "field": "state",
                    "label": "Review state",
                    "before": before_state,
                    "after": body.state,
                },
                {
                    "field": "approvedBy",
                    "label": "Approved by",
                    "before": before_approver,
                    "after": plan.approved_by,
                },
            ],
            reason=body.reason,
            # A plan approval is a SOX control point, not routine authoring.
            retention=enums.RetentionClass.SOX if approved else None,
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.test_plan(db, plan)


class GeneratePlan(BaseModel):
    requirementId: str
    generateCases: bool = True


@router.post("/test-plans/generate")
def generate_plan(
    body: GeneratePlan,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Author a plan, and optionally its cases, from the impact analysis."""
    requirement = db.get(Requirement, body.requirementId)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")

    analysis = db.execute(
        select(ImpactAnalysis)
        .where(ImpactAnalysis.requirement_id == requirement.id)
        .order_by(ImpactAnalysis.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    plan = testgen.generate_plan(db, requirement, analysis, actor.name)

    chain.append(
        db,
        chain.RecordInput(
            action="plan.generated",
            actor=f"{plan.model} · planning agent",
            actor_type=enums.ActorType.AGENT,
            requirement_ref=requirement.ref,
            summary=(
                f"{plan.ref} generated from "
                + (
                    f"an impact analysis of {len(analysis.items)} node(s)."
                    if analysis
                    else "the requirement alone — no impact analysis existed."
                )
            ),
            cost_usd=plan.generation_cost_usd,
            workspace_id=workspace_id,
        ),
    )

    cases: list[TestCase] = []
    if body.generateCases:
        cases = testgen.generate_cases(db, requirement, plan, analysis, actor.name)
        chain.append(
            db,
            chain.RecordInput(
                action="test.generated",
                actor=f"{plan.model} · test design agent",
                actor_type=enums.ActorType.AGENT,
                requirement_ref=requirement.ref,
                summary=(
                    f"{len(cases)} case(s) generated against {plan.ref}. "
                    f"{len(plan.uncovered_node_ids)} impacted node(s) remain uncovered."
                ),
                workspace_id=workspace_id,
            ),
        )

    db.commit()
    return {
        "plan": wire.test_plan(db, plan),
        "cases": [wire.test_case(c) for c in cases],
    }


# ------------------------------------------------------------------- cases


@router.get("/test-cases")
def list_cases(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(TestCase).order_by(TestCase.ref)).scalars()
    return [wire.test_case(c) for c in rows]


class SaveCase(BaseModel):
    title: str | None = None
    expectedResult: str | None = None
    priority: str | None = None
    level: str | None = None
    type: str | None = None
    automatable: bool | None = None
    testData: str | None = None
    preconditions: list[str] | None = None
    steps: list[dict] | None = None
    reason: str | None = None


@router.patch("/test-cases/{case_id}")
def save_case(
    case_id: str,
    body: SaveCase,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Persist an edited case, recording a field-level diff.

    Weakening an expected result is the single most consequential edit anyone
    can make to a test asset, and a record saying only "case edited" cannot
    distinguish it from a typo fix. Part 11 §11.10(e) asks for the prior value
    for exactly this reason.
    """
    case = db.get(TestCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Test case not found")

    before = {
        "title": case.title,
        "expected_result": case.expected_result,
        "priority": case.priority,
        "level": case.level,
        "type": case.type,
        "automatable": case.automatable,
        "test_data": case.test_data,
        "origin": case.origin,
    }

    patch = body.model_dump(exclude_none=True, exclude={"reason"})
    field_map = {
        "title": "title",
        "expectedResult": "expected_result",
        "priority": "priority",
        "level": "level",
        "type": "type",
        "automatable": "automatable",
        "testData": "test_data",
        "preconditions": "preconditions",
        "steps": "steps",
    }
    for wire_name, value in patch.items():
        attr = field_map.get(wire_name)
        if attr:
            setattr(case, attr, value)

    # An AI-generated case a human edits is no longer purely generated.
    if case.origin == enums.ArtifactOrigin.AI_GENERATED:
        case.origin = enums.ArtifactOrigin.AI_EDITED_BY_HUMAN

    # The rubric described a version that no longer exists. Marked rather than
    # dropped: silently discarding it would conceal that a human overrode a
    # judged case, which is precisely the event a reviewer needs to see.
    if case.rubric:
        case.rubric = {**case.rubric, "supersededByEdit": True}

    case.updated_at = utcnow()

    labels = {
        "title": "Title",
        "expected_result": "Expected result",
        "priority": "Priority",
        "level": "Level",
        "type": "Type",
        "automatable": "Automatable",
        "test_data": "Test data",
        "origin": "Origin",
    }
    changes = []
    for attr, label in labels.items():
        old, new = before[attr], getattr(case, attr)
        if old != new:
            changes.append(
                {
                    "field": attr,
                    "label": label,
                    "before": _render(old),
                    "after": _render(new),
                }
            )

    if changes:
        chain.append(
            db,
            chain.RecordInput(
                action="testcase.edited",
                actor=actor.name,
                actor_type=enums.ActorType.HUMAN,
                requirement_ref=case.ref,
                summary=f"{case.ref} edited — {', '.join(c['label'] for c in changes)}.",
                changes=changes,
                reason=body.reason,
                workspace_id=workspace_id,
            ),
        )

    db.commit()
    return wire.test_case(case)


def _render(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@router.patch("/test-cases/{case_id}/state")
def set_case_state(
    case_id: str,
    body: StateChange,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    case = db.get(TestCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Test case not found")
    if body.state not in {s.value for s in enums.ReviewState}:
        raise HTTPException(status_code=422, detail=f"Unknown state: {body.state}")

    before = case.state
    case.state = body.state
    case.updated_at = utcnow()

    chain.append(
        db,
        chain.RecordInput(
            action="testcase.state_changed",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=case.ref,
            summary=(
                f"{case.ref} "
                f"{'approved' if body.state == enums.ReviewState.APPROVED else f'moved to {body.state}'}."
            ),
            changes=[
                {
                    "field": "state",
                    "label": "Review state",
                    "before": before,
                    "after": body.state,
                }
            ],
            reason=body.reason,
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.test_case(case)


# ------------------------------------------------------------------ suites


@router.get("/test-suites")
def list_suites(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(TestSuite).order_by(TestSuite.created_at.desc())).scalars()
    return [wire.test_suite(s) for s in rows]


class SuiteInput(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    caseIds: list[str] = Field(default_factory=list)


@router.post("/test-suites", status_code=201)
def create_suite(
    body: SuiteInput,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    count = db.execute(select(func.count()).select_from(TestSuite)).scalar_one()
    suite = TestSuite(
        id=new_id("ts"),
        ref=f"TS-{str(count + 1).zfill(3)}",
        name=body.name.strip(),
        description=body.description.strip(),
        # De-duplicated: the picker allows a case to be toggled repeatedly, and
        # a suite listing the same case twice would run it twice.
        case_ids=list(dict.fromkeys(body.caseIds)),
        saved=True,
        created_by=actor.name,
        workspace_id=workspace_id,
    )
    db.add(suite)
    db.commit()
    return wire.test_suite(suite)


@router.patch("/test-suites/{suite_id}")
def update_suite(
    suite_id: str, body: SuiteInput, db: Session = Depends(get_db)
) -> dict:
    suite = db.get(TestSuite, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    suite.name = body.name.strip()
    suite.description = body.description.strip()
    suite.case_ids = list(dict.fromkeys(body.caseIds))
    db.commit()
    return wire.test_suite(suite)


@router.delete("/test-suites/{suite_id}", status_code=204)
def delete_suite(suite_id: str, db: Session = Depends(get_db)) -> None:
    suite = db.get(TestSuite, suite_id)
    if suite is not None:
        db.delete(suite)
        db.commit()


# ------------------------------------------------------------ environments


@router.get("/test-environments")
def list_environments(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(TestEnvironment).order_by(TestEnvironment.name)).scalars()
    return [wire.test_environment(db, e) for e in rows]


# -------------------------------------------------------------- executions


@router.get("/test-executions")
def list_executions(db: Session = Depends(get_db)) -> list[dict]:
    rows = list(
        db.execute(
            select(TestExecution).order_by(TestExecution.started_at.desc())
        ).scalars()
    )
    result_ids = [r.id for e in rows for r in e.results]
    artifacts = _artifacts_for_results(db, result_ids)
    return [wire.test_execution(db, e, artifacts) for e in rows]


@router.get("/test-executions/{execution_id}")
def get_execution(execution_id: str, db: Session = Depends(get_db)) -> dict | None:
    e = db.get(TestExecution, execution_id)
    if e is None:
        return None
    artifacts = _artifacts_for_results(db, [r.id for r in e.results])
    return wire.test_execution(db, e, artifacts)


class ReportedResultIn(BaseModel):
    caseId: str
    status: str
    actual: str = ""
    durationSeconds: int = 0
    deviation: str | None = None
    attempts: int = 1
    artifacts: list[dict] = Field(default_factory=list)


class RunExecution(BaseModel):
    caseIds: list[str]
    environmentId: str
    suiteName: str = "Ad-hoc selection"
    requirementId: str | None = None
    planId: str | None = None
    suiteId: str | None = None
    results: list[ReportedResultIn] = Field(default_factory=list)
    retestDefectIds: list[str] = Field(default_factory=list)


@router.post("/test-executions")
def run_execution(
    body: RunExecution,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Record an execution.

    `results` carries outcomes from whatever actually ran the cases. Cases with
    no reported outcome are recorded `skipped` — Meridian does not yet drive a
    system under test, and inventing a pass would destroy the only thing this
    product sells.
    """
    try:
        execution = execution_service.run(
            db,
            case_ids=body.caseIds,
            environment_id=body.environmentId,
            suite_name=body.suiteName,
            requirement_id=body.requirementId,
            plan_id=body.planId,
            suite_id=body.suiteId,
            triggered_by=actor.name,
            triggered_by_type=enums.ActorType.HUMAN,
            reported=[
                execution_service.ReportedResult(
                    case_id=r.caseId,
                    status=r.status,
                    actual=r.actual,
                    duration_seconds=r.durationSeconds,
                    deviation=r.deviation,
                    attempts=r.attempts,
                    artifacts=r.artifacts,
                )
                for r in body.results
            ],
            retest_defect_ids=body.retestDefectIds,
            workspace_id=workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    verified = sum(
        1 for r in execution.results if r.grade == enums.EvidenceGrade.VERIFIED
    )
    chain.append(
        db,
        chain.RecordInput(
            action="execution.finished",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=body.requirementId,
            summary=(
                f"{execution.ref} {execution.status} — {len(execution.results)} case(s) "
                f"in {execution.environment.get('environment', 'an environment')}, "
                f"{verified} verified-grade."
                + (f" {execution.blocked_reason}" if execution.blocked_reason else "")
            ),
            cost_usd=execution.cost_usd,
            duration_seconds=sum(r.duration_seconds for r in execution.results),
            workspace_id=workspace_id,
        ),
    )
    db.commit()

    artifacts = _artifacts_for_results(db, [r.id for r in execution.results])
    return wire.test_execution(db, execution, artifacts)


# ------------------------------------------------------------------- runs


@router.get("/test-runs")
def list_runs(db: Session = Depends(get_db)) -> list[dict]:
    rows = list(
        db.execute(select(TestRun).order_by(TestRun.started_at.desc())).scalars()
    )
    by_run: dict[str, list[dict]] = {}
    if rows:
        arts = db.execute(
            select(EvidenceArtifact).where(
                EvidenceArtifact.test_run_id.in_([r.id for r in rows])
            )
        ).scalars()
        for a in arts:
            by_run.setdefault(a.test_run_id, []).append(wire.artifact(a))
    return [wire.test_run(r, by_run.get(r.id)) for r in rows]


# ---------------------------------------------------------------- defects


@router.get("/defects")
def list_defects(
    requirementId: str | None = None, db: Session = Depends(get_db)
) -> list[dict]:
    stmt = select(Defect).order_by(Defect.raised_at.desc())
    if requirementId:
        stmt = stmt.where(Defect.requirement_id == requirementId)
    return [wire.defect(d) for d in db.execute(stmt).scalars()]


class RaiseDefect(BaseModel):
    requirementId: str
    executionId: str | None = None
    caseId: str | None = None
    caseRef: str | None = None
    title: str = Field(min_length=1)
    expected: str = ""
    actual: str = ""
    severity: str = enums.ImpactSeverity.MAJOR
    owner: str = ""
    affectedNodeIds: list[str] = Field(default_factory=list)


@router.post("/defects", status_code=201)
def raise_defect(
    body: RaiseDefect,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    count = db.execute(select(func.count()).select_from(Defect)).scalar_one()
    now = utcnow()
    ref = f"DEF-{count + 315}"

    defect = Defect(
        id=new_id("def"),
        ref=ref,
        requirement_id=body.requirementId,
        execution_id=body.executionId,
        case_id=body.caseId,
        case_ref=body.caseRef,
        title=body.title,
        expected=body.expected,
        actual=body.actual,
        severity=body.severity,
        status=enums.DefectStatus.OPEN,
        owner=body.owner or actor.name,
        raised_by=actor.name,
        raised_by_type=enums.ArtifactOrigin.HUMAN_AUTHORED,
        raised_at=now,
        notes=[
            {
                "at": now.isoformat(),
                "by": actor.name,
                "text": f"Raised from {body.caseRef or 'a result'}.",
            }
        ],
        retest_execution_ids=[],
        affected_node_ids=body.affectedNodeIds,
        workspace_id=workspace_id,
    )
    db.add(defect)

    if body.caseId and body.executionId:
        result = db.execute(
            select(CaseResult).where(
                CaseResult.execution_id == body.executionId,
                CaseResult.case_id == body.caseId,
            )
        ).scalar_one_or_none()
        if result is not None:
            result.defect_ref = ref

    chain.append(
        db,
        chain.RecordInput(
            action="defect.raised",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=ref,
            summary=(
                f"{ref} raised at {body.severity} severity from "
                f"{body.caseRef or 'a result'} — {body.title}"
            ),
            changes=[
                {
                    "field": "expected",
                    "label": "Expected",
                    "before": None,
                    "after": body.expected,
                },
                {
                    "field": "actual",
                    "label": "Actual",
                    "before": None,
                    "after": body.actual,
                },
            ],
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.defect(defect)


class DefectStatusChange(BaseModel):
    status: str
    note: str | None = None


@router.patch("/defects/{defect_id}/status")
def set_defect_status(
    defect_id: str,
    body: DefectStatusChange,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="Defect not found")
    if body.status not in {s.value for s in enums.DefectStatus}:
        raise HTTPException(status_code=422, detail=f"Unknown status: {body.status}")

    # 'closed' means a re-test proved the fix. Setting it by hand would let a
    # claim masquerade as evidence, which is the exact confusion the separate
    # 'fixed' state exists to prevent.
    if (
        body.status == enums.DefectStatus.CLOSED
        and defect.verified_by_execution_id is None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "A defect can only be closed by a re-test in which its case passed. "
                "Mark it 'fixed' and run a re-test."
            ),
        )

    before = defect.status
    now = utcnow()
    defect.status = body.status
    defect.updated_at = now
    if body.note:
        defect.notes = [
            *(defect.notes or []),
            {"at": now.isoformat(), "by": actor.name, "text": body.note},
        ]

    chain.append(
        db,
        chain.RecordInput(
            action="defect.status_changed",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=defect.ref,
            summary=f"{defect.ref} moved from {before} to {body.status}.",
            changes=[
                {
                    "field": "status",
                    "label": "Status",
                    "before": before,
                    "after": body.status,
                }
            ],
            reason=body.note,
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.defect(defect)


# ---------------------------------------------------------------- closure


@router.get("/test-closures")
def list_closures(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(TestClosure)).scalars()
    return [wire.test_closure(db, c) for c in rows]


@router.get("/requirements/{requirement_id}/closure")
def get_closure(requirement_id: str, db: Session = Depends(get_db)) -> dict | None:
    closure = db.execute(
        select(TestClosure).where(TestClosure.requirement_id == requirement_id)
    ).scalar_one_or_none()
    return wire.test_closure(db, closure) if closure else None

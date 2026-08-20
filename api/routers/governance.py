"""
Audit chain, approvals, incidents, analytics and evidence export.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.ids import iso, new_id, utcnow
from api.domain import enums
from api.domain.governance import (
    AiIncident,
    ApprovalPackage,
    AuditEntry,
    CostEvent,
)
from api.domain.models import ExtractionRun
from api.domain.stlc import TestCase, TestExecution
from api.ledger import chain
from api.routers.deps import Actor, current_actor, current_workspace
from api.schemas import wire
from api.services import approvals as approvals_service

router = APIRouter(tags=["governance"])


# ------------------------------------------------------------------- audit


@router.get("/audit")
def get_audit(limit: int = 500, db: Session = Depends(get_db)) -> list[dict]:
    """The ledger, newest first."""
    rows = db.execute(
        select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(limit)
    ).scalars()
    return [chain.to_wire(e) for e in rows]


@router.post("/audit/verify")
def verify_chain(
    db: Session = Depends(get_db), workspace_id: str = Depends(current_workspace)
) -> dict:
    """Recompute the chain and report the result.

    Its own endpoint because verification is an action with a cost and an
    outcome, not a property to be read off a page. A failure is itself audited
    — a failed integrity check is exactly the kind of event the record should
    contain.
    """
    result = chain.verify(db)

    if not result.valid:
        chain.append(
            db,
            chain.RecordInput(
                action="chain.verified",
                actor="Meridian Integrity Monitor",
                actor_type=enums.ActorType.SYSTEM,
                summary=f"Chain verification FAILED at entry #{result.first_broken_seq}.",
                retention=enums.RetentionClass.PERMANENT,
                workspace_id=workspace_id,
            ),
        )
        db.commit()

    return {
        "valid": result.valid,
        "entriesChecked": result.entries_checked,
        "verifiedAt": result.verified_at,
        "firstBrokenSeq": result.first_broken_seq,
        "detail": result.detail,
    }


@router.post("/audit/simulate-tamper")
def simulate_tamper(seq: int, db: Session = Depends(get_db)) -> dict:
    """Corrupt one entry so detection can be demonstrated.

    A tamper-evidence claim that cannot be shown failing is a marketing line.
    This exists so the Audit page can prove detection works rather than
    asserting it, and it should be removed before the ledger holds anything
    real.
    """
    ok = chain.simulate_tamper(db, seq)
    db.commit()
    return {"ok": ok}


# --------------------------------------------------------------- approvals


@router.get("/approvals")
def list_approvals(db: Session = Depends(get_db)) -> list[dict]:
    approvals_service.refresh_summaries(db)
    rows = db.execute(
        select(ApprovalPackage).order_by(ApprovalPackage.submitted_at.desc())
    ).scalars()
    out = [wire.approval_package(p) for p in rows]
    db.commit()
    return out


class GateDecision(BaseModel):
    decision: str
    comment: str = ""
    reviewDurationSeconds: int = 0
    artifactsOpened: list[str] = Field(default_factory=list)
    artifactsAvailable: int = 0
    aiRecommendation: str = "none"
    overrideRationale: str | None = None


@router.post("/approvals/{package_id}/gates/{gate_id}/decide")
def decide_gate(
    package_id: str,
    gate_id: str,
    body: GateDecision,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Record a gate decision with its oversight evidence.

    The oversight record is written in the same call as the decision rather
    than inferred later, because Art. 14 asks whether oversight was effective
    at the moment it was exercised. Reconstructing that afterwards from access
    logs would be a guess.

    An approval that policy forbids is refused with its reasons — 409, not a
    silent success.
    """
    if body.decision not in {
        enums.ApprovalDecision.APPROVED,
        enums.ApprovalDecision.REJECTED,
    }:
        raise HTTPException(status_code=422, detail="Decision must be approved or rejected.")

    oversight = approvals_service.oversight_record(
        review_duration_seconds=body.reviewDurationSeconds,
        artifacts_opened=body.artifactsOpened,
        artifacts_available=body.artifactsAvailable,
        ai_recommendation=body.aiRecommendation,
        human_decision="approve"
        if body.decision == enums.ApprovalDecision.APPROVED
        else "reject",
        override_rationale=body.overrideRationale,
    )

    try:
        package = approvals_service.decide(
            db,
            package_id=package_id,
            gate_id=gate_id,
            decision=body.decision,
            comment=body.comment,
            oversight=oversight,
            actor_name=actor.name,
            actor_email=actor.email,
        )
    except approvals_service.GateBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "This gate cannot be approved.", "reasons": exc.reasons},
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    gate = next(g for g in package.gates if g.id == gate_id)
    minutes = round(oversight["reviewDurationSeconds"] / 60)
    chain.append(
        db,
        chain.RecordInput(
            action=(
                "approval.granted"
                if body.decision == enums.ApprovalDecision.APPROVED
                else "approval.rejected"
            ),
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=package.requirement_ref,
            summary=(
                f"{gate.name} gate {body.decision} after {minutes}m review; "
                f"{len(oversight['artifactsOpened'])}/{oversight['artifactsAvailable']} "
                "evidence artifacts opened"
                + (" — AI recommendation overridden." if oversight["overridden"] else ".")
            ),
            changes=[
                {
                    "field": "decision",
                    "label": "Decision",
                    "before": enums.ApprovalDecision.PENDING,
                    "after": body.decision,
                }
            ],
            reason=body.comment,
            duration_seconds=body.reviewDurationSeconds,
            retention=enums.RetentionClass.SOX,
            legal_hold=True,
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.approval_package(package)


@router.get("/approvals/{package_id}/gates/{gate_id}/blockers")
def gate_blockers(
    package_id: str, gate_id: str, db: Session = Depends(get_db)
) -> dict:
    """What stands between this gate and an approval, before anyone tries."""
    package = db.get(ApprovalPackage, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Approval package not found")
    gate = next((g for g in package.gates if g.id == gate_id), None)
    if gate is None:
        raise HTTPException(status_code=404, detail="Gate not found")

    reasons = approvals_service.evaluate_blockers(db, package, gate)
    return {"blocked": bool(reasons), "reasons": reasons}


# --------------------------------------------------------------- incidents


@router.get("/incidents")
def list_incidents(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(AiIncident).order_by(AiIncident.detected_at.desc())
    ).scalars()
    return [wire.incident(i) for i in rows]


class RaiseIncident(BaseModel):
    kind: str
    severity: str
    title: str = Field(min_length=1)
    description: str = ""
    affectedRequirementRefs: list[str] = Field(default_factory=list)
    reportable: bool = False
    reportableRationale: str = ""


@router.post("/incidents", status_code=201)
def raise_incident(
    body: RaiseIncident,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    from api.core.config import settings

    count = db.execute(select(func.count()).select_from(AiIncident)).scalar_one()
    now = utcnow()
    incident = AiIncident(
        id=new_id("inc"),
        ref=f"AIR-{str(count + 1).zfill(4)}",
        kind=body.kind,
        severity=body.severity,
        status=enums.IncidentStatus.OPEN,
        title=body.title,
        description=body.description,
        detected_at=now,
        detected_by=actor.name,
        detection_method="human_review",
        affected_requirement_refs=body.affectedRequirementRefs,
        affected_artifact_ids=[],
        model=settings.meridian_model,
        model_version=settings.meridian_model_version,
        reportable=body.reportable,
        reportable_rationale=body.reportableRationale,
        notes=[{"at": now.isoformat(), "by": actor.name, "text": "Incident raised."}],
        workspace_id=workspace_id,
    )
    db.add(incident)

    chain.append(
        db,
        chain.RecordInput(
            action="incident.raised",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            summary=(
                f"{incident.ref} raised ({body.severity}, "
                f"{body.kind.replace('_', ' ')}) — {body.title}"
            ),
            reason=body.reportableRationale,
            retention=enums.RetentionClass.PERMANENT,
            legal_hold=body.reportable,
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.incident(incident)


class IncidentStatusChange(BaseModel):
    status: str
    note: str | None = None


@router.patch("/incidents/{incident_id}/status")
def set_incident_status(
    incident_id: str,
    body: IncidentStatusChange,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    incident = db.get(AiIncident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    before = incident.status
    now = utcnow()
    incident.status = body.status
    if body.status == enums.IncidentStatus.RESOLVED:
        incident.resolved_at = now
    if body.note:
        incident.notes = [
            *(incident.notes or []),
            {"at": now.isoformat(), "by": actor.name, "text": body.note},
        ]

    chain.append(
        db,
        chain.RecordInput(
            action="incident.updated",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            summary=f"{incident.ref} moved from {before} to {body.status}.",
            changes=[
                {
                    "field": "status",
                    "label": "Status",
                    "before": before,
                    "after": body.status,
                }
            ],
            reason=body.note,
            retention=enums.RetentionClass.PERMANENT,
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.incident(incident)


# --------------------------------------------------------------- analytics


@router.get("/analytics")
def get_analytics(days: int = 30, db: Session = Depends(get_db)) -> dict:
    """Aggregated from the cost ledger and the run history, not from a fixture.

    Every figure here traces to `CostEvent` rows written by the code that
    actually spent the money, or to `ExtractionRun` rows written by the
    pipeline that did the work. That is what makes "cost per test case"
    answerable rather than merely displayable — and it is also why a fresh
    install shows near-zero rather than an impressive demo curve.

    `days` bounds every series, so the window the caller asked for is the
    window every number describes. Returning a fixed 30-day total beside a
    7-day chart is the kind of quiet mismatch nobody notices until a figure
    is quoted in a meeting.
    """
    # A window has to be bounded somewhere: an unbounded one scans the whole
    # ledger, and a zero or negative one silently returns nothing.
    #
    # `days or 30` would be wrong — 0 is falsy, so an explicit `days=0` would
    # quietly become a month rather than being clamped to the minimum. Only a
    # genuinely absent value should take the default.
    days = max(1, min(int(30 if days is None else days), 365))
    now = utcnow()
    since = now - timedelta(days=days)

    events = list(
        db.execute(select(CostEvent).where(CostEvent.at >= since)).scalars()
    )

    by_day: dict[str, dict] = defaultdict(
        lambda: {"llmUsd": 0.0, "computeUsd": 0.0, "changes": 0}
    )
    for e in events:
        day = e.at.date().isoformat()
        by_day[day]["llmUsd"] += e.llm_usd
        by_day[day]["computeUsd"] += e.compute_usd
        if e.kind in {"impact_analysis", "plan_generation"}:
            by_day[day]["changes"] += 1

    cost_series = [
        {
            "date": day,
            "llmUsd": round(v["llmUsd"], 4),
            "computeUsd": round(v["computeUsd"], 4),
            "changes": v["changes"],
        }
        for day, v in sorted(by_day.items())
    ]

    by_model: dict[str, dict] = defaultdict(lambda: {"costUsd": 0.0, "calls": 0})
    for e in events:
        if not e.model:
            continue
        by_model[e.model]["costUsd"] += e.llm_usd
        by_model[e.model]["calls"] += 1

    total_model_cost = sum(v["costUsd"] for v in by_model.values()) or 1.0
    model_spend = [
        {
            "model": model,
            "costUsd": round(v["costUsd"], 4),
            "calls": v["calls"],
            "share": round(v["costUsd"] / total_model_cost, 4),
        }
        for model, v in sorted(
            by_model.items(), key=lambda kv: kv[1]["costUsd"], reverse=True
        )
    ]

    executions = list(
        db.execute(select(TestExecution).where(TestExecution.started_at >= since)).scalars()
    )
    finished = [e for e in executions if e.finished_at]
    avg_hours = (
        sum((e.finished_at - e.started_at).total_seconds() for e in finished)
        / len(finished)
        / 3600
        if finished
        else 0.0
    )

    case_count = db.execute(select(func.count()).select_from(TestCase)).scalar_one()
    gen_cost = sum(
        e.llm_usd for e in events if e.kind in {"case_generation", "case_judging"}
    )

    dora = [
        {
            "label": "Cost per test case",
            "value": f"${gen_cost / case_count:.2f}" if case_count else "—",
            "deltaPct": 0,
            "direction": "down_good",
            "detail": (
                f"{case_count} case(s) generated for ${gen_cost:.2f} in LLM spend."
                if case_count
                else "No cases have been generated yet."
            ),
        },
        {
            "label": "Mean execution time",
            "value": f"{avg_hours:.2f}h" if finished else "—",
            "deltaPct": 0,
            "direction": "down_good",
            "detail": (
                f"Across {len(finished)} completed execution(s) in the last 30 days."
                if finished
                else "No executions have completed in the last 30 days."
            ),
        },
        {
            "label": "LLM spend (30d)",
            "value": f"${sum(e.llm_usd for e in events):.2f}",
            "deltaPct": 0,
            "direction": "down_good",
            "detail": f"{len(events)} recorded AI operation(s).",
        },
    ]

    # --- extraction runs ----------------------------------------------------
    #
    # The other half of "what has this system actually done". Cost answers
    # what was spent; runs answer what was extracted, how often, and how much
    # of it failed — which is the question an operator asks first.
    runs = list(
        db.execute(
            select(ExtractionRun).where(ExtractionRun.started_at >= since)
        ).scalars()
    )

    runs_by_day: dict[str, dict] = defaultdict(
        lambda: {"runs": 0, "failed": 0, "nodes": 0, "seconds": 0.0}
    )
    durations: list[float] = []
    for r in runs:
        day = r.started_at.date().isoformat()
        bucket = runs_by_day[day]
        bucket["runs"] += 1
        bucket["nodes"] += r.nodes_created or 0
        if r.status == "failed":
            bucket["failed"] += 1
        if r.finished_at:
            seconds = (r.finished_at - r.started_at).total_seconds()
            bucket["seconds"] += seconds
            durations.append(seconds)

    run_series = [
        {
            "date": day,
            "runs": v["runs"],
            "failed": v["failed"],
            "nodes": v["nodes"],
            # Mean rather than total: a day with one slow run and a day with
            # ten fast ones should not read as the same shape.
            "avgSeconds": round(v["seconds"] / v["runs"], 1) if v["runs"] else 0.0,
        }
        for day, v in sorted(runs_by_day.items())
    ]

    failed_runs = sum(1 for r in runs if r.status == "failed")
    total_seconds = sum(durations)
    run_totals = {
        "runs": len(runs),
        "failed": failed_runs,
        "succeeded": len(runs) - failed_runs,
        "nodes": sum(r.nodes_created or 0 for r in runs),
        "totalSeconds": round(total_seconds, 1),
        # Distinguished from `runs`: a run still in flight has no duration,
        # and averaging over all runs would understate it.
        "timedRuns": len(durations),
        "avgSeconds": round(total_seconds / len(durations), 1) if durations else 0.0,
        "llmUsd": round(sum(e.llm_usd for e in events), 4),
        "computeUsd": round(sum(e.compute_usd for e in events), 4),
        "tokensIn": sum(e.tokens_in or 0 for e in events),
        "tokensOut": sum(e.tokens_out or 0 for e in events),
        "operations": len(events),
        "days": days,
    }

    return {
        "windowDays": days,
        "runs": run_series,
        "runTotals": run_totals,
        "cost": cost_series,
        # Requires a historical baseline this installation does not have.
        # Returned empty rather than fabricated: an invented baseline would
        # make every efficiency claim on the dashboard a fiction.
        "cycleTime": [],
        "dora": dora,
        "modelSpend": model_spend,
    }


# --------------------------------------------------------- evidence export


class ExportInput(BaseModel):
    requirementRef: str | None = None
    scope: str = "All activity"


@router.post("/evidence/export")
def export_evidence(
    body: ExportInput,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Build a verifiable evidence pack.

    The pack contains the chain segment, a recomputed verification result and
    the hash of the manifest itself, so a recipient can check it without access
    to Meridian. Exporting is itself recorded — who took a copy of the record,
    and when, is part of the record.
    """
    verification = chain.verify(db)

    stmt = select(AuditEntry).order_by(AuditEntry.seq.asc())
    if body.requirementRef:
        stmt = stmt.where(AuditEntry.requirement_ref == body.requirementRef)
    entries = [chain.to_wire(e) for e in db.execute(stmt).scalars()]

    incidents = db.execute(select(AiIncident)).scalars()
    incident_wire = [
        wire.incident(i)
        for i in incidents
        if not body.requirementRef
        or body.requirementRef in (i.affected_requirement_refs or [])
    ]

    payload = {
        "generatedAt": iso(utcnow()),
        "generatedBy": {"name": actor.name, "email": actor.email},
        "scope": body.scope,
        "requirementRef": body.requirementRef,
        "standards": [
            "EU AI Act Art. 12 (record-keeping)",
            "EU AI Act Art. 14 (human oversight)",
            "ISO/IEC 42001 A.6.2.8 (AI event logging)",
            "21 CFR Part 11 §11.10(e) (audit trail)",
            "NIST AI RMF (traceability, incident disclosure)",
        ],
        "chainVerification": {
            "valid": verification.valid,
            "entriesChecked": verification.entries_checked,
            "verifiedAt": verification.verified_at,
            "firstBrokenSeq": verification.first_broken_seq,
            "detail": verification.detail,
        },
        "entryCount": len(entries),
        "entries": entries,
        "incidents": incident_wire,
    }

    content = json.dumps(payload, indent=2)
    manifest_hash = chain.sha256(content)
    stamp = utcnow().date().isoformat()
    filename = f"meridian-evidence-{body.requirementRef or 'all'}-{stamp}.json"

    chain.append(
        db,
        chain.RecordInput(
            action="evidence.exported",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=body.requirementRef,
            summary=(
                f"Evidence pack exported ({len(entries)} entries, scope: {body.scope}). "
                f"Manifest {manifest_hash[:16]}…, chain "
                f"{'verified' if verification.valid else 'FAILED VERIFICATION'}."
            ),
            retention=enums.RetentionClass.SOX,
            workspace_id=workspace_id,
        ),
    )
    db.commit()

    return {"filename": filename, "content": content, "manifestHash": manifest_hash}

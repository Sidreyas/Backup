"""
Wire serialisation.

The database is snake_case and the frontend contract in `src/lib/types.ts` is
camelCase. Rather than decorate every model with aliases, serialisation is
explicit and lives here — one place to look when a field does not appear in the
UI, and one place that fails loudly when the contract changes.

These functions are hand-written rather than generated on purpose. Several
fields are not straight renames: `GraphEdge` is a flattened projection of an
`Assertion`, criteria are gathered from a side table, and `TestExecution.results`
is ordered. A generic mapper would have to be told about each of those anyway,
and would hide them while doing it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.ids import iso
from api.domain import enums
from api.domain.governance import (
    AiIncident,
    ApprovalGate,
    ApprovalPackage,
    Policy,
)
from api.domain.models import (
    Assertion,
    Connection,
    GraphBuildRun,
    GraphNode,
    ImpactAnalysis,
    IngestJob,
    KnowledgeSource,
    Project,
    Requirement,
    Workspace,
)
from api.domain.stlc import (
    CaseResult,
    Criterion,
    Defect,
    TestCase,
    TestClosure,
    TestEnvironment,
    TestExecution,
    TestPlan,
    TestRun,
    TestSuite,
)

# --------------------------------------------------------------- org scope


def workspace(w: Workspace, project_ids: list[str]) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "slug": w.slug,
        "compliance": w.compliance or [],
        "region": w.region,
        "memberCount": w.member_count,
        "projectIds": project_ids,
    }


def project(p: Project, source_ids: list[str], open_requirements: list[str]) -> dict:
    return {
        "id": p.id,
        "workspaceId": p.workspace_id,
        "name": p.name,
        "key": p.key,
        "description": p.description,
        "status": p.status,
        "platform": p.platform,
        "lead": p.lead,
        "createdAt": iso(p.created_at),
        "sourceIds": source_ids,
        "openRequirements": open_requirements,
        "monthlySpendUsd": p.monthly_spend_usd,
    }


# ----------------------------------------------------------------- sources


def source(s: KnowledgeSource) -> dict:
    out = {
        "id": s.id,
        "name": s.name,
        "kind": s.kind,
        "provider": s.provider,
        "status": s.status,
        "lastSyncedAt": iso(s.last_synced_at),
        "stalenessThresholdDays": s.staleness_threshold_days,
        "entities": s.entities,
        "documents": s.documents,
        "coverage": s.coverage,
        "sizeLabel": s.size_label,
        "owner": s.owner,
    }
    if s.error:
        out["error"] = s.error
    return out


def connection(c: Connection) -> dict:
    out = {
        "id": c.id,
        "connectorId": c.connector_id,
        "label": c.label,
        "status": c.status,
        "authMethod": c.auth_method,
        "grantedScopes": c.granted_scopes or [],
        "cadence": c.cadence,
        "lastSyncedAt": iso(c.last_synced_at),
        "nextSyncAt": iso(c.next_sync_at),
        "owner": c.owner,
        "connectedBy": c.connected_by,
        "connectedAt": iso(c.connected_at),
        "recordCount": c.record_count,
        "lastTestedAt": iso(c.last_tested_at),
    }
    if c.error:
        out["error"] = c.error
    if c.source_id:
        out["sourceId"] = c.source_id
    return out


def connector_definition(entry: Any) -> dict:
    """A connector from the registry.

    `comingSoon` is set from whether an implementation exists, not from a hand
    maintained flag. The catalogue cannot then drift out of step with what the
    code can actually do.
    """
    return {
        "id": entry.id,
        "name": entry.name,
        "vendor": entry.vendor,
        "category": entry.category,
        "kind": entry.kind,
        "description": entry.description,
        "authMethods": entry.auth_methods,
        "provides": entry.provides,
        "scopes": [
            {
                "id": s.id,
                "label": s.label,
                "description": s.description,
                "required": s.required,
                "writes": s.writes,
            }
            for s in entry.scopes
        ],
        "comingSoon": not entry.implemented,
    }


def ingest_job(j: IngestJob) -> dict:
    out = {
        "id": j.id,
        "projectId": j.project_id,
        "name": j.name,
        "kind": j.kind,
        "provider": j.provider,
        "stage": j.stage,
        "progress": j.progress,
        "sizeLabel": j.size_label,
        "uploadedAt": iso(j.uploaded_at),
        "uploadedBy": j.uploaded_by,
        "entitiesExtracted": j.entities_extracted,
        "linksProposed": j.links_proposed,
        "parseCoverage": j.parse_coverage,
        "warnings": j.warnings or [],
    }
    if j.doc_kind:
        out["docKind"] = j.doc_kind
    if j.message:
        out["message"] = j.message
    return out


def graph_build(b: GraphBuildRun) -> dict:
    return {
        "id": b.id,
        "projectId": b.project_id,
        "startedAt": iso(b.started_at),
        "finishedAt": iso(b.finished_at),
        "status": b.status,
        "steps": b.steps or [],
        "nodesCreated": b.nodes_created,
        "edgesProposed": b.edges_proposed,
        "edgesConfirmed": b.edges_confirmed,
        "costUsd": b.cost_usd,
        "unresolved": b.unresolved or [],
    }


# ------------------------------------------------------------------- graph


def graph_node(n: GraphNode) -> dict:
    return {
        "id": n.id,
        "label": n.label,
        "kind": n.kind,
        "sourceId": n.source_id or "",
        "provenance": n.provenance,
        "sourceRef": n.source_ref,
        "criticality": n.criticality,
        "owner": n.owner,
        "lastVerifiedAt": iso(n.last_verified_at),
        "x": n.x,
        "y": n.y,
        "description": n.description,
    }


def graph_edge(a: Assertion) -> dict:
    """An assertion, flattened to the frontend's simpler `GraphEdge`.

    The assertion's extra dimensions — validity window, superseding chain,
    asserting agent — are not dropped, they are simply not in this projection.
    `confidence` here reports `confirmed` only when a human actually confirmed
    it, so a machine-proposed edge can never present as a fact.
    """
    confirmed = a.status == enums.AssertionStatus.CONFIRMED
    return {
        "id": a.id,
        "from": a.subject_id,
        "to": a.object_id,
        "label": a.label or a.predicate.replace("_", " ").lower(),
        "confidence": enums.LinkConfidence.CONFIRMED if confirmed else a.confidence,
        "confirmedBy": a.confirmed_by,
        "confirmedAt": iso(a.confirmed_at),
        "rationale": a.rationale,
    }


# ------------------------------------------------------------ requirements


def requirement(r: Requirement) -> dict:
    return {
        "id": r.id,
        "ref": r.ref,
        "title": r.title,
        "summary": r.summary,
        "stage": r.stage,
        "requestedBy": r.requested_by,
        "requestedByRole": r.requested_by_role,
        "createdAt": iso(r.created_at),
        "updatedAt": iso(r.updated_at),
        "platform": r.platform,
        "systemKind": r.system_kind,
        "priority": r.priority,
        "impactedNodeIds": r.impacted_node_ids or [],
        "estimatedCostUsd": r.estimated_cost_usd,
        "actualCostUsd": r.actual_cost_usd,
        "riskLevel": r.risk_level,
    }


def chat_message(m: Any) -> dict:
    out: dict[str, Any] = {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "at": iso(m.at),
    }
    if m.citations:
        out["citations"] = m.citations
    if m.dissent:
        out["dissent"] = m.dissent
    if m.tokens_in is not None:
        out["tokensIn"] = m.tokens_in
    if m.tokens_out is not None:
        out["tokensOut"] = m.tokens_out
    if m.cost_usd is not None:
        out["costUsd"] = m.cost_usd
    if m.model:
        out["model"] = m.model
    if m.crawl:
        out["crawl"] = m.crawl
    if m.generated_cases:
        out["generatedCases"] = m.generated_cases
    if m.run_summary:
        out["runSummary"] = m.run_summary
    if m.tool_calls:
        out["toolCalls"] = m.tool_calls
    return out


def impact_analysis(a: ImpactAnalysis) -> dict:
    return {
        "requirementId": a.requirement_id,
        "generatedAt": iso(a.generated_at),
        "model": a.model,
        "costUsd": a.cost_usd,
        "durationSeconds": a.duration_seconds,
        "items": [
            {
                "id": i.id,
                "nodeId": i.node_id,
                "nodeLabel": i.node_label,
                "nodeKind": i.node_kind,
                "severity": i.severity,
                "confidence": i.confidence,
                "reason": i.reason,
                "provenance": i.provenance,
                "owner": i.owner,
                "coveredByTestIds": i.covered_by_test_ids or [],
                "coverageGap": i.coverage_gap,
            }
            for i in a.items
        ],
        "blindSpots": a.blind_spots or [],
        "environmentFingerprint": a.environment_fingerprint or {},
    }


def feasibility_assessment(a: Any) -> dict:
    """A feasibility assessment, gaps and questions included.

    Gaps and open questions are always present, even when empty. A client that
    has to distinguish "no gaps" from "gaps not sent" will eventually get it
    wrong in the permissive direction.
    """
    return {
        "id": a.id,
        "requirementId": a.requirement_id,
        "assessedAt": iso(a.assessed_at),
        "intent": a.intent,
        "verdict": a.verdict,
        "understoodAs": a.understood_as,
        "targetNodeIds": a.target_node_ids or [],
        "owningConnectionIds": a.owning_connection_ids or [],
        "questionBudget": a.question_budget,
        "budgetRaisedTo": a.budget_raised_to,
        "budgetReason": a.budget_reason,
        "model": a.model,
        "costUsd": a.cost_usd,
        "source": a.source,
        "discarded": a.discarded or [],
        "gaps": [
            {
                "id": g.id,
                "kind": g.kind,
                "summary": g.summary,
                "remedy": g.remedy,
                "subject": g.subject,
                "blocking": g.blocking,
                "risk": g.risk,
            }
            for g in a.gaps
        ],
        "questions": [
            {
                "id": q.id,
                "text": q.text,
                "rationale": q.rationale,
                "options": q.options or [],
                "about": q.about,
                "answeredAs": q.answered_as,
                "answeredAt": iso(q.answered_at) if q.answered_at else None,
                "acceptedUnknown": q.accepted_unknown,
            }
            for q in a.questions
        ],
    }


# -------------------------------------------------------------------- STLC


def criterion(c: Criterion) -> dict:
    out = {
        "id": c.id,
        "text": c.text,
        "met": c.met,
        "evaluatedBy": c.evaluated_by,
    }
    if c.detail:
        out["detail"] = c.detail
    return out


def criteria_for(db: Session, owner_type: str, owner_id: str, role: str) -> list[dict]:
    rows = db.execute(
        select(Criterion)
        .where(
            Criterion.owner_type == owner_type,
            Criterion.owner_id == owner_id,
            Criterion.role == role,
        )
        .order_by(Criterion.position)
    ).scalars()
    return [criterion(c) for c in rows]


def test_plan(db: Session, p: TestPlan) -> dict:
    return {
        "id": p.id,
        "ref": p.ref,
        "requirementId": p.requirement_id,
        "requirementRef": p.requirement_ref,
        "title": p.title,
        "origin": p.origin,
        "state": p.state,
        "version": p.version,
        "createdAt": iso(p.created_at),
        "updatedAt": iso(p.updated_at),
        "author": p.author,
        "approvedBy": p.approved_by,
        "approvedAt": iso(p.approved_at),
        "objective": p.objective,
        "scopeIn": p.scope_in or [],
        "scopeOut": p.scope_out or [],
        "levels": p.levels or [],
        "types": p.types or [],
        "entryCriteria": criteria_for(db, "plan", p.id, "entry"),
        "exitCriteria": criteria_for(db, "plan", p.id, "exit"),
        "risks": p.risks or [],
        "coveredNodeIds": p.covered_node_ids or [],
        "uncoveredNodeIds": p.uncovered_node_ids or [],
        "environmentIds": p.environment_ids or [],
        "estimatedCases": p.estimated_cases,
        "estimatedDurationHours": p.estimated_duration_hours,
        "generationCostUsd": p.generation_cost_usd,
        "model": p.model,
    }


def test_case(c: TestCase) -> dict:
    out = {
        "id": c.id,
        "ref": c.ref,
        "planId": c.plan_id or "",
        "requirementId": c.requirement_id or "",
        "title": c.title,
        "origin": c.origin,
        "state": c.state,
        "level": c.level,
        "type": c.type,
        "priority": c.priority,
        "automatable": c.automatable,
        "preconditions": c.preconditions or [],
        "steps": c.steps or [],
        "expectedResult": c.expected_result,
        "testData": c.test_data,
        "coversNodeIds": c.covers_node_ids or [],
        "createdAt": iso(c.created_at),
        "updatedAt": iso(c.updated_at),
        "author": c.author,
        "rationale": c.rationale,
        "estimatedDurationSeconds": c.estimated_duration_seconds,
        "tags": c.tags or [],
    }
    if c.rubric:
        out["rubric"] = c.rubric
    return out


def test_suite(s: TestSuite) -> dict:
    return {
        "id": s.id,
        "ref": s.ref,
        "name": s.name,
        "description": s.description,
        "caseIds": s.case_ids or [],
        "saved": s.saved,
        "createdAt": iso(s.created_at),
        "createdBy": s.created_by,
    }


def test_environment(db: Session, e: TestEnvironment) -> dict:
    out = {
        "id": e.id,
        "name": e.name,
        "kind": e.kind,
        "platform": e.platform,
        "status": e.status,
        "fingerprint": e.fingerprint or {},
        "readiness": criteria_for(db, "environment", e.id, "readiness"),
        "lastRefreshedAt": iso(e.last_refreshed_at),
        "ownedBy": e.owned_by,
        "hourlyCostUsd": e.hourly_cost_usd,
    }
    if e.notes:
        out["notes"] = e.notes
    return out


def case_result(r: CaseResult, artifacts: list[dict] | None = None) -> dict:
    out = {
        "id": r.id,
        "caseId": r.case_id or "",
        "caseRef": r.case_ref,
        "caseTitle": r.case_title,
        "status": r.status,
        "grade": r.grade,
        "expected": r.expected,
        "actual": r.actual,
        "deviation": r.deviation,
        "durationSeconds": r.duration_seconds,
        "attempts": r.attempts,
        "startedAt": iso(r.started_at),
        "artifacts": artifacts or [],
        "coversNodeIds": r.covers_node_ids or [],
    }
    if r.defect_ref:
        out["defectRef"] = r.defect_ref
    return out


def test_execution(
    db: Session, e: TestExecution, artifacts_by_result: dict[str, list[dict]] | None = None
) -> dict:
    by_result = artifacts_by_result or {}
    results = sorted(e.results, key=lambda r: r.position)
    out = {
        "id": e.id,
        "ref": e.ref,
        "requirementId": e.requirement_id or "",
        "planId": e.plan_id or "",
        "suiteId": e.suite_id,
        "suiteName": e.suite_name,
        "environmentId": e.environment_id or "",
        "environment": e.environment or {},
        "status": e.status,
        "triggeredBy": e.triggered_by,
        "triggeredByType": e.triggered_by_type,
        "startedAt": iso(e.started_at),
        "finishedAt": iso(e.finished_at),
        "results": [case_result(r, by_result.get(r.id)) for r in results],
        "costUsd": e.cost_usd,
        "preflight": criteria_for(db, "execution", e.id, "preflight"),
    }
    if e.blocked_reason:
        out["blockedReason"] = e.blocked_reason
    return out


def test_run(r: TestRun, artifacts: list[dict] | None = None) -> dict:
    out = {
        "id": r.id,
        "ref": r.ref,
        "requirementId": r.requirement_id or "",
        "title": r.title,
        "grade": r.grade,
        "status": r.status,
        "suite": r.suite,
        "startedAt": iso(r.started_at),
        "durationSeconds": r.duration_seconds,
        "attempts": r.attempts,
        "flakeRate": r.flake_rate,
        "runner": r.runner,
        "environment": r.environment or {},
        "artifacts": artifacts or [],
        "coveredNodeIds": r.covered_node_ids or [],
        "costUsd": r.cost_usd,
    }
    if r.failure_reason:
        out["failureReason"] = r.failure_reason
    return out


def defect(d: Defect) -> dict:
    return {
        "id": d.id,
        "ref": d.ref,
        "requirementId": d.requirement_id or "",
        "executionId": d.execution_id,
        "caseId": d.case_id,
        "caseRef": d.case_ref,
        "title": d.title,
        "expected": d.expected,
        "actual": d.actual,
        "severity": d.severity,
        "status": d.status,
        "owner": d.owner,
        "raisedBy": d.raised_by,
        "raisedByType": d.raised_by_type,
        "raisedAt": iso(d.raised_at),
        "updatedAt": iso(d.updated_at),
        "notes": d.notes or [],
        "retestExecutionIds": d.retest_execution_ids or [],
        "verifiedByExecutionId": d.verified_by_execution_id,
        "affectedNodeIds": d.affected_node_ids or [],
    }


def test_closure(db: Session, c: TestClosure) -> dict:
    return {
        "id": c.id,
        "requirementId": c.requirement_id,
        "requirementRef": c.requirement_ref,
        "planId": c.plan_id or "",
        "executionIds": c.execution_ids or [],
        "exitCriteria": criteria_for(db, "closure", c.id, "exit"),
        "state": c.state,
        "closedBy": c.closed_by,
        "closedAt": iso(c.closed_at),
        "summary": c.summary or {},
        "openDefects": c.open_defects or [],
        "residualRisks": c.residual_risks or [],
        "lessons": c.lessons or [],
        "totalCostUsd": c.total_cost_usd,
        "totalDurationHours": c.total_duration_hours,
    }


# ------------------------------------------------------------- governance


def approval_gate(g: ApprovalGate) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "role": g.role,
        "requiresEvidenceGrade": g.requires_evidence_grade,
        "decision": g.decision,
        "approver": g.approver,
        "approverEmail": g.approver_email,
        "decidedAt": iso(g.decided_at),
        "comment": g.comment,
        "blockedBy": g.blocked_by or [],
        "dueAt": iso(g.due_at),
        "oversight": g.oversight,
    }


def approval_package(p: ApprovalPackage) -> dict:
    return {
        "id": p.id,
        "requirementId": p.requirement_id,
        "requirementRef": p.requirement_ref,
        "title": p.title,
        "submittedAt": iso(p.submitted_at),
        "submittedBy": p.submitted_by,
        "gates": [approval_gate(g) for g in sorted(p.gates, key=lambda g: g.position)],
        "evidenceSummary": p.evidence_summary or {},
        "estimatedCostUsd": p.estimated_cost_usd,
        "riskLevel": p.risk_level,
    }


def incident(i: AiIncident) -> dict:
    return {
        "id": i.id,
        "ref": i.ref,
        "kind": i.kind,
        "severity": i.severity,
        "status": i.status,
        "title": i.title,
        "description": i.description,
        "detectedAt": iso(i.detected_at),
        "detectedBy": i.detected_by,
        "detectionMethod": i.detection_method,
        "affectedRequirementRefs": i.affected_requirement_refs or [],
        "affectedArtifactIds": i.affected_artifact_ids or [],
        "model": i.model,
        "modelVersion": i.model_version,
        "reportable": i.reportable,
        "reportableRationale": i.reportable_rationale,
        "disclosedAt": iso(i.disclosed_at),
        "disclosedTo": i.disclosed_to,
        "correctiveAction": i.corrective_action,
        "resolvedAt": iso(i.resolved_at),
        "notes": i.notes or [],
    }


def policy(p: Policy) -> dict:
    return {
        "id": p.id,
        "ref": p.ref,
        "name": p.name,
        "description": p.description,
        "severity": p.severity,
        "scope": p.scope,
        "enabled": p.enabled,
        "triggeredCount": p.triggered_count,
    }


def artifact(a: Any) -> dict:
    return {
        "id": a.id,
        "kind": a.kind,
        "label": a.label,
        "sizeLabel": a.size_label,
        "sha256": a.sha256,
    }

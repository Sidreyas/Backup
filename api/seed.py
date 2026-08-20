"""
Seed a working set.

Run with `python -m api.seed`.

This exists so a fresh install is explorable rather than an empty shell. What
it seeds is deliberately limited: organisational scope, environments, policies,
connector definitions and a graph small enough to read. It does **not**
manufacture test evidence, passed runs, or a cost history.

That restraint is the point. Fabricated evidence in a product whose entire
claim is that evidence means something would be self-defeating — and a seeded
"verified" run would satisfy a real approval gate, which is precisely the
failure mode the gate exists to prevent. The evidence, approvals and analytics
pages start empty and fill as the system is actually used.

The audit chain seeded here is genuine: entries are appended through
`chain.append`, so their hashes are computed and `/api/audit/verify` reports a
real result from the first run.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from api.core.db import Base, SessionLocal, engine
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.governance import Policy
from api.domain.models import (
    Assertion,
    Connection,
    GraphNode,
    KnowledgeSource,
    Project,
    User,
    Workspace,
)
from api.domain.stlc import Criterion, TestEnvironment
from api.ledger import chain

WORKSPACE_ID = "ws-acme"
PROJECT_ID = "pj-hcm"


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if db.execute(select(Workspace).limit(1)).scalar_one_or_none() is not None:
            print("Already seeded. Drop the database to re-seed.")
            return

        now = utcnow()

        # --- organisation --------------------------------------------------

        db.add(
            Workspace(
                id=WORKSPACE_ID,
                name="Acme Group",
                slug="acme",
                compliance=["SOX", "GDPR", "EU AI Act"],
                region="EMEA",
                member_count=48,
            )
        )
        db.add(
            Project(
                id=PROJECT_ID,
                workspace_id=WORKSPACE_ID,
                name="HCM Platform",
                key="HCM",
                description=(
                    "Workday HCM configuration and the integrations that depend on it."
                ),
                status=enums.ProjectStatus.ACTIVE,
                platform="Workday",
                lead="Sathish Kumar",
                monthly_spend_usd=0.0,
            )
        )
        db.add(
            User(
                id=new_id("u"),
                name="Sathish Kumar",
                email="sathish.kumar@acme.example",
                role="QA Lead",
                initials="AR",
            )
        )

        # --- sources -------------------------------------------------------

        source = KnowledgeSource(
            id="src-jira",
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            name="Jira — HCM project",
            kind=enums.SourceKind.TICKETING,
            provider="Jira",
            # Nothing has synced. Claiming 'connected' before a first sync
            # would be a lie the very next screen exposes.
            status=enums.IngestStatus.DISCONNECTED,
            staleness_threshold_days=7,
            entities=0,
            documents=0,
            coverage=0,
            size_label="—",
            owner="Sathish Kumar",
        )
        db.add(source)

        db.add(
            Connection(
                id="cn-jira",
                connector_id="cx-jira",
                label="Jira Cloud",
                status=enums.IngestStatus.DISCONNECTED,
                auth_method=enums.AuthMethod.API_KEY,
                granted_scopes=["read.configuration", "read.issues"],
                cadence=enums.SyncCadence.DAILY,
                owner="Sathish Kumar",
                connected_by="Sathish Kumar",
                record_count=0,
                source_id="src-jira",
                secret_ref="JIRA_API_TOKEN",
                workspace_id=WORKSPACE_ID,
                # No `error`. The status is already DISCONNECTED, and a
                # never-configured connection has not failed at anything —
                # putting "not yet configured" in the error field renders a red
                # alert that makes a clean install look broken.
            )
        )

        # --- a small, readable graph ---------------------------------------
        #
        # Enough structure that traversal and impact analysis have something to
        # work on. Every node carries real provenance pointing at where it
        # would have come from, because a node with no traceable origin is the
        # kind of thing this product exists to make impossible.

        nodes = [
            GraphNode(
                id="n-bp-timeoff",
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                label="Time Off Request",
                kind=enums.NodeKind.BUSINESS_PROCESS,
                source_id="src-jira",
                provenance="Workday › BP Definition › TIMEOFF_REQ (v14)",
                source_ref="https://acme.workday.example/bp/TIMEOFF_REQ",
                criticality=enums.Criticality.HIGH,
                owner="HR Operations",
                description=(
                    "Absence request process for EMEA employees. Routes to the "
                    "line manager, then to HR when the balance is negative."
                ),
                natural_key="seed:bp:timeoff",
                x=0.28,
                y=0.32,
            ),
            GraphNode(
                id="n-cfg-approval",
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                label="BP Approval Chain — TIMEOFF_APPR",
                kind=enums.NodeKind.CONFIG_OBJECT,
                source_id="src-jira",
                provenance="Workday › BP Definition › TIMEOFF_APPR (v14)",
                source_ref="https://acme.workday.example/bp/TIMEOFF_APPR",
                criticality=enums.Criticality.CRITICAL,
                owner="HR Operations",
                description=(
                    "Two-step approval. Manager approves; Compensation Partner is "
                    "added when the absence exceeds 10 consecutive days."
                ),
                natural_key="seed:cfg:approval",
                x=0.52,
                y=0.24,
            ),
            GraphNode(
                id="n-data-balance",
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                label="Absence Balance",
                kind=enums.NodeKind.DATA_ENTITY,
                source_id="src-jira",
                provenance="Workday › Calculated Field › ABSENCE_BAL",
                source_ref="https://acme.workday.example/field/ABSENCE_BAL",
                criticality=enums.Criticality.HIGH,
                owner="HR Operations",
                description=(
                    "Calculated field. Accrual minus taken, evaluated at request "
                    "submission. Feeds the negative-balance routing condition."
                ),
                natural_key="seed:data:balance",
                x=0.72,
                y=0.44,
            ),
            GraphNode(
                id="n-int-payroll",
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                label="Payroll Outbound Integration",
                kind=enums.NodeKind.INTEGRATION,
                source_id="src-jira",
                provenance="Workday › Integration System › PAYROLL_OUT",
                source_ref="https://acme.workday.example/integration/PAYROLL_OUT",
                criticality=enums.Criticality.CRITICAL,
                owner="Payroll Systems",
                description=(
                    "Nightly outbound file to the payroll provider. Carries "
                    "approved absence records; a schema change here is breaking."
                ),
                natural_key="seed:int:payroll",
                x=0.46,
                y=0.68,
            ),
            GraphNode(
                id="n-screen-request",
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                label="Request Time Off (self-service)",
                kind=enums.NodeKind.SCREEN,
                source_id="src-jira",
                provenance="Workday › Task › Request Time Off",
                source_ref="https://acme.workday.example/task/request-time-off",
                criticality=enums.Criticality.MEDIUM,
                owner="HR Operations",
                description="Employee-facing form. Date range, type and comment.",
                natural_key="seed:screen:request",
                x=0.16,
                y=0.62,
            ),
            GraphNode(
                id="n-policy-sod",
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                label="Segregation of Duties — absence approval",
                kind=enums.NodeKind.POLICY,
                source_id="src-jira",
                provenance="Acme Controls Register › SOD-114",
                source_ref="https://acme.example/controls/SOD-114",
                criticality=enums.Criticality.CRITICAL,
                owner="Internal Audit",
                description=(
                    "An employee may not approve their own absence, nor that of a "
                    "person who approves theirs. SOX-relevant."
                ),
                natural_key="seed:policy:sod",
                x=0.80,
                y=0.16,
            ),
        ]
        for node in nodes:
            db.add(node)
        db.flush()

        # Relationships. Confidence is honest: structure read from a source
        # system is 'high', a link inferred from naming is 'medium', and
        # nothing is 'confirmed' because no human has reviewed any of it yet.
        edges = [
            ("n-bp-timeoff", "HAS_STEP", "n-cfg-approval", enums.LinkConfidence.HIGH,
             "The approval chain is declared as a step of the process definition."),
            ("n-cfg-approval", "READS", "n-data-balance", enums.LinkConfidence.HIGH,
             "The routing condition references the calculated balance field."),
            ("n-bp-timeoff", "WRITES", "n-int-payroll", enums.LinkConfidence.MEDIUM,
             "Approved absences appear in the payroll outbound payload; inferred "
             "from the field overlap, not from a declared dependency."),
            ("n-screen-request", "IMPLEMENTS", "n-bp-timeoff", enums.LinkConfidence.HIGH,
             "The task initiates this business process."),
            ("n-cfg-approval", "GOVERNED_BY", "n-policy-sod", enums.LinkConfidence.MEDIUM,
             "The control names absence approval; the mapping to this specific "
             "chain has not been confirmed by a human."),
            ("n-int-payroll", "READS", "n-data-balance", enums.LinkConfidence.MEDIUM,
             "The outbound payload includes a balance column."),
        ]
        for subject, predicate, obj, confidence, rationale in edges:
            db.add(
                Assertion(
                    id=new_id("as"),
                    workspace_id=WORKSPACE_ID,
                    subject_id=subject,
                    predicate=predicate,
                    object_id=obj,
                    label=predicate.replace("_", " ").lower(),
                    confidence=confidence,
                    status=enums.AssertionStatus.PROPOSED,
                    rationale=rationale,
                    asserted_by="Meridian seed",
                    asserted_by_type=enums.ActorType.SYSTEM,
                    valid_from=now,
                )
            )

        # --- environments --------------------------------------------------

        env = TestEnvironment(
            id="env-wd-sandbox",
            name="Workday Sandbox (Implementation)",
            kind="sandbox",
            platform="Workday",
            status=enums.EnvironmentStatus.READY,
            fingerprint={
                "environment": "Sandbox (Implementation)",
                "tenant": "acme_hcm_impl",
                "release": "Workday 2026R1",
                "refreshedAt": (now - timedelta(days=28)).isoformat(),
                # Honest: a sandbox refreshed a month ago does not represent
                # production's scenario spread, and a gate should be able to
                # see that.
                "dataCoverage": 41,
            },
            last_refreshed_at=now - timedelta(days=28),
            owned_by="HR Operations",
            hourly_cost_usd=0.0,
            notes="Refreshed monthly. Payroll integration points at a stub endpoint.",
            workspace_id=WORKSPACE_ID,
        )
        db.add(env)
        db.flush()

        readiness = [
            ("Tenant is reachable and the integration user can authenticate.", True),
            ("Absence configuration matches the production baseline.", None),
            ("Payroll outbound endpoint is stubbed, not live.", True),
        ]
        for i, (text, met) in enumerate(readiness):
            db.add(
                Criterion(
                    id=new_id("cr"),
                    text=text,
                    met=met,
                    evaluated_by="system" if met is not None else None,
                    owner_type="environment",
                    owner_id=env.id,
                    role="readiness",
                    position=i,
                )
            )

        # --- policies ------------------------------------------------------

        policies = [
            (
                "POL-001",
                "Verified evidence required for production sign-off",
                "A gate marked as requiring verified evidence cannot be satisfied by "
                "an agent's assertion. Enforced server-side at decision time.",
                "blocking",
                "All workspaces",
            ),
            (
                "POL-002",
                "Breaking-severity impact requires test coverage",
                "A node assessed as breaking must be covered by at least one approved "
                "test case before its requirement can reach approval.",
                "blocking",
                "All workspaces",
            ),
            (
                "POL-003",
                "Unconfirmed graph links are not treated as facts",
                "Impact analysis reports the weakest confidence on the path and states "
                "when a node was reached only through unconfirmed assertions.",
                "warning",
                "All workspaces",
            ),
            (
                "POL-004",
                "Model version drift must be re-validated",
                "An artefact generated under a different pinned model version than the "
                "one now in force is flagged; approval under the old version does not "
                "carry over.",
                "warning",
                "All workspaces",
            ),
        ]
        for ref, name, description, severity, scope in policies:
            db.add(
                Policy(
                    id=new_id("pol"),
                    ref=ref,
                    name=name,
                    description=description,
                    severity=severity,
                    scope=scope,
                    enabled=True,
                    triggered_count=0,
                    workspace_id=WORKSPACE_ID,
                )
            )

        db.flush()

        # --- a genuine opening chain ---------------------------------------
        # Appended through the real ledger, so these hashes are computed and
        # /api/audit/verify reports a true result immediately.

        chain.append(
            db,
            chain.RecordInput(
                action="settings.changed",
                actor="Meridian",
                actor_type=enums.ActorType.SYSTEM,
                summary=(
                    "Workspace initialised. Model pinned to "
                    "claude-opus-5 @ 2026-07-14."
                ),
                workspace_id=WORKSPACE_ID,
            ),
        )
        chain.append(
            db,
            chain.RecordInput(
                action="graph.built",
                actor="Meridian seed",
                actor_type=enums.ActorType.SYSTEM,
                summary=(
                    f"Seed graph written — {len(nodes)} nodes, {len(edges)} proposed "
                    "assertions, none confirmed."
                ),
                workspace_id=WORKSPACE_ID,
            ),
        )

        db.commit()

        print(f"Seeded workspace {WORKSPACE_ID} / project {PROJECT_ID}.")
        print(f"  {len(nodes)} graph nodes, {len(edges)} proposed assertions")
        print(f"  {len(policies)} policies, 1 environment, 1 connection (unconfigured)")
        print("  No test evidence, approvals or cost history — those accrue from use.")

    finally:
        db.close()


if __name__ == "__main__":
    seed()

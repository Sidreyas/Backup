"""
Read endpoints for the working set: sources, connectors, graph, policies.

These mirror the corresponding functions in `src/lib/api.ts` one for one, so
swapping the frontend over is a change to that file and nothing else.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.connectors import registry
from api.core import secrets
from api.core.db import get_db
from api.core.ids import utcnow
from api.services import connections as connections_service
from api.domain import enums
from api.domain.governance import Policy
from api.domain.models import (
    Connection,
    CustomConnector,
    GraphBuildRun,
    IngestJob,
    KnowledgeSource,
    Project,
    Requirement,
    Workspace,
)
from api.graph import queries
from api.ledger import chain
from api.routers.deps import Actor, current_actor, current_workspace
from api.schemas import wire

router = APIRouter(tags=["catalog"])


@router.get("/workspaces")
def get_workspaces(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for ws in db.execute(select(Workspace)).scalars():
        project_ids = [
            p.id
            for p in db.execute(
                select(Project).where(Project.workspace_id == ws.id)
            ).scalars()
        ]
        out.append(wire.workspace(ws, project_ids))
    return out


@router.get("/projects")
def get_projects(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for p in db.execute(select(Project)).scalars():
        source_ids = [
            s.id
            for s in db.execute(
                select(KnowledgeSource).where(KnowledgeSource.project_id == p.id)
            ).scalars()
        ]
        open_reqs = [
            r.id
            for r in db.execute(
                select(Requirement).where(
                    Requirement.project_id == p.id,
                    Requirement.stage.notin_(
                        [
                            enums.RequirementStage.SIGNED_OFF,
                            enums.RequirementStage.REJECTED,
                        ]
                    ),
                )
            ).scalars()
        ]
        out.append(wire.project(p, source_ids, open_reqs))
    return out


@router.get("/sources")
def get_sources(db: Session = Depends(get_db)) -> list[dict]:
    """Knowledge sources, with staleness evaluated at read time.

    A source goes stale by the passage of time, not by an event, so nothing
    would ever write that transition. Computing it here means the status is
    right whenever anyone looks, rather than right only just after a sync.
    """
    now = utcnow()
    out = []
    for s in db.execute(select(KnowledgeSource)).scalars():
        if (
            s.status == enums.IngestStatus.CONNECTED
            and s.last_synced_at is not None
            and (now - s.last_synced_at).days > s.staleness_threshold_days
        ):
            s.status = enums.IngestStatus.STALE
        out.append(wire.source(s))
    db.commit()
    return out


@router.get("/connectors")
def get_connectors(db: Session = Depends(get_db)) -> list[dict]:
    """Built-in connectors from the registry, plus customer-authored ones."""
    out = [wire.connector_definition(e) for e in registry.all_entries()]
    for c in db.execute(select(CustomConnector)).scalars():
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "vendor": c.vendor,
                "category": c.category,
                "kind": c.kind,
                "description": c.description,
                "authMethods": c.auth_methods or [],
                "provides": c.provides or [],
                "scopes": c.scopes or [],
                "custom": True,
            }
        )
    return out


@router.get("/connectors/{connector_id}/setup")
def get_connector_setup(connector_id: str) -> dict:
    """Everything the UI needs to walk someone through connecting this system.

    Served from the connector's own declaration rather than hardcoded in the
    frontend: the help text explaining where to find a Workday token endpoint
    belongs next to the code that knows why the field exists, and a new
    connector should not require a frontend change to become connectable.
    """
    entry = registry.get(connector_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown connector")

    return {
        "id": entry.id,
        "name": entry.name,
        "vendor": entry.vendor,
        "implemented": entry.implemented,
        "authMethods": entry.auth_methods,
        "credentialFields": [
            {
                "id": f.id,
                "label": f.label,
                "help": f.help,
                "kind": f.kind,
                "required": f.required,
                "placeholder": f.placeholder,
                "authMethods": f.auth_methods,
                "options": [
                    {"id": o[0], "label": o[1], "description": o[2]} for o in f.options
                ],
            }
            for f in entry.credential_fields
        ],
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
        # Work the customer does in their own system, before connecting.
        "setupSteps": entry.setup_steps,
        # Artefacts they must build — Workday's report pack.
        "requiredArtifacts": entry.required_artifacts,
        # How to build one, in the source system. Same for every artefact.
        "artifactBuildSteps": entry.artifact_build_steps,
        # Stated before they invest a day in setup, not after.
        "limitations": entry.limitations,
        "secretsConfigured": secrets.available(),
    }


@router.get("/connections")
def get_connections(db: Session = Depends(get_db)) -> list[dict]:
    return [wire.connection(c) for c in db.execute(select(Connection)).scalars()]


@router.get("/connections/{connection_id}")
def get_connection(connection_id: str, db: Session = Depends(get_db)) -> dict:
    """One connection, including its non-secret settings."""
    cn = db.get(Connection, connection_id)
    if cn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return {
        **wire.connection(cn),
        "settings": connections_service.redacted_settings(cn),
    }


class ConnectInput(BaseModel):
    connectorId: str
    label: str = ""
    authMethod: str = "oauth2"
    grantedScopes: list[str] = Field(default_factory=list)
    cadence: str = "daily"
    owner: str = ""
    #: Credential and settings values, keyed by the connector's field ids.
    values: dict[str, Any] = Field(default_factory=dict)


@router.post("/connections", status_code=201)
def create_connection(
    body: ConnectInput,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Register a connection.

    Credentials are validated for completeness and encrypted before storage.
    The connection is *not* tested here — testing is a separate, explicit
    action, so a slow or unreachable tenant does not make the form appear
    broken.
    """
    try:
        connection = connections_service.create(
            db,
            connector_id=body.connectorId,
            label=body.label,
            auth_method=body.authMethod,
            granted_scopes=body.grantedScopes,
            cadence=body.cadence,
            owner=body.owner or actor.name,
            values=body.values,
            connected_by=actor.name,
            workspace_id=workspace_id,
        )
    except connections_service.CredentialsRequired as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Some required values are missing.",
                "reasons": exc.missing,
            },
        ) from exc
    except secrets.SecretsUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": str(exc), "reasons": []},
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    chain.append(
        db,
        chain.RecordInput(
            action="source.connected",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            summary=(
                f"{registry.get(body.connectorId).name} connected as "
                f"'{connection.label}' with {len(connection.granted_scopes)} scope(s)."
            ),
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.connection(connection)


@router.patch("/connections/{connection_id}/credentials")
def update_connection_credentials(
    connection_id: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Update credentials or settings on an existing connection."""
    cn = db.get(Connection, connection_id)
    if cn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        connections_service.update_credentials(db, cn, body)
    except secrets.SecretsUnavailable as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc), "reasons": []}) from exc

    chain.append(
        db,
        chain.RecordInput(
            action="settings.changed",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            summary=f"Credentials updated for connection '{cn.label}'.",
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return {**wire.connection(cn), "settings": connections_service.redacted_settings(cn)}


@router.get("/connections/{connection_id}/capabilities")
def get_connection_capabilities(connection_id: str, db: Session = Depends(get_db)) -> dict:
    """What this connection can actually extract right now.

    Distinct from the connector's *declared* capabilities: this reflects the
    scopes granted and, for Workday, which discovery reports actually exist in
    the tenant. It is how the UI can say "business process logic is not
    reachable yet" instead of silently producing a thin graph.
    """
    cn = db.get(Connection, connection_id)
    if cn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    entry = registry.get(cn.connector_id)
    if entry is None or not entry.implemented:
        raise HTTPException(status_code=501, detail="Connector not implemented")

    connector = connections_service.build_from_connection(cn, db)
    return {
        "configured": connector.is_configured(),
        "capabilities": [
            {
                "id": c.id,
                "label": c.label,
                "layer": c.layer,
                "nodeKinds": c.node_kinds,
                "requiresScopes": c.requires_scopes,
            }
            for c in connector.discover_capabilities()
        ],
    }


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: str, db: Session = Depends(get_db)) -> dict:
    """Test a connection without changing it.

    Separate from connecting because "does this still work" is the question
    people actually have, and answering it should never risk credentials that
    are already working. A connector in error stays in error — the test
    reports, it does not repair.
    """
    cn = db.get(Connection, connection_id)
    if cn is None:
        return {"ok": False, "message": "Connection not found."}

    cn.last_tested_at = utcnow()

    entry = registry.get(cn.connector_id)
    if entry is None or not entry.implemented:
        db.commit()
        return {
            "ok": False,
            "message": (
                f"The {entry.name if entry else cn.connector_id} connector is declared "
                "but not yet implemented, so this connection cannot be tested."
            ),
        }

    try:
        connector = connections_service.build_from_connection(cn, db)
        check = connector.validate_access()
    except secrets.SecretsUnavailable as exc:
        db.commit()
        return {"ok": False, "message": str(exc)}
    except ValueError as exc:
        # A credential blob that will not decrypt. Reported as itself rather
        # than as a connection failure, because the fix is entirely different.
        db.commit()
        return {"ok": False, "message": str(exc)}

    message = check.message
    if check.missing_scopes:
        message += f" Missing scopes: {', '.join(check.missing_scopes)}."

    # A test that succeeds against a connection previously in error clears the
    # error: leaving stale error text on a working connection sends people
    # chasing a problem that is already fixed.
    if check.ok:
        cn.error = None
        if cn.status == enums.IngestStatus.ERROR:
            cn.status = enums.IngestStatus.CONNECTED
    else:
        cn.error = message
        cn.status = enums.IngestStatus.ERROR

    db.commit()
    return {
        "ok": check.ok,
        "message": message,
        "effectiveScopes": check.effective_scopes,
        "missingScopes": check.missing_scopes,
    }


@router.post("/connections/{connection_id}/sync")
def sync_connection(
    connection_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Pull from a connection and write the result into the graph."""
    from api.ingest.pipeline import ingest

    cn = db.get(Connection, connection_id)
    if cn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    entry = registry.get(cn.connector_id)
    if entry is None or not entry.implemented:
        raise HTTPException(
            status_code=501,
            detail=(
                f"The {entry.name if entry else cn.connector_id} connector is declared "
                "but not yet implemented."
            ),
        )

    source = (
        db.get(KnowledgeSource, cn.source_id) if cn.source_id else None
    )
    try:
        connector = connections_service.build_from_connection(cn, db)
    except (secrets.SecretsUnavailable, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    outcome = ingest(
        db,
        connector,
        connection=cn,
        source=source,
        workspace_id=workspace_id,
        actor=actor.name,
    )
    db.commit()

    return {
        "connection": wire.connection(cn),
        "outcome": {
            "runId": outcome.run_id,
            "status": outcome.status,
            "recordsCollected": outcome.records_collected,
            "nodesCreated": outcome.nodes_created,
            "nodesUpdated": outcome.nodes_updated,
            "assertionsProposed": outcome.assertions_proposed,
            "rejectedCount": len(outcome.rejected),
            "truncated": outcome.truncated,
            "error": outcome.error,
        },
    }


@router.post("/connections/{connection_id}/disconnect")
def disconnect(connection_id: str, db: Session = Depends(get_db)) -> dict:
    """Disconnect, keeping indexed data.

    Deliberately not a delete: evidence already gathered under this connection
    is cited by approvals that have been signed. Removing it would rewrite
    history to make a past decision unverifiable.
    """
    cn = db.get(Connection, connection_id)
    if cn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    cn.status = enums.IngestStatus.DISCONNECTED
    cn.next_sync_at = None
    db.commit()
    return wire.connection(cn)


@router.get("/graph")
def get_graph(
    db: Session = Depends(get_db), workspace_id: str = Depends(current_workspace)
) -> dict:
    """The graph as the UI draws it: nodes plus flattened live assertions."""
    nodes = queries.nodes_for(db, workspace_id)
    edges = queries.live_assertions(db, workspace_id)
    return {
        "nodes": [wire.graph_node(n) for n in nodes],
        "edges": [wire.graph_edge(a) for a in edges],
    }


@router.post("/graph/edges/{assertion_id}/confirm")
def confirm_edge(
    assertion_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Confirm a proposed link.

    This is the human judgement the graph is waiting for. Only after it does an
    edge stop being a hypothesis, which is why it is audited rather than being
    a silent state change.
    """
    from api.domain.models import Assertion

    assertion = db.get(Assertion, assertion_id)
    if assertion is None:
        raise HTTPException(status_code=404, detail="Assertion not found")

    before = assertion.status
    assertion.status = enums.AssertionStatus.CONFIRMED
    assertion.confidence = enums.LinkConfidence.CONFIRMED
    assertion.confirmed_by = actor.name
    assertion.confirmed_at = utcnow()

    chain.append(
        db,
        chain.RecordInput(
            action="graph.link_confirmed",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            summary=f"Link confirmed: {assertion.predicate} ({assertion.id}).",
            changes=[
                {
                    "field": "status",
                    "label": "Status",
                    "before": before,
                    "after": assertion.status,
                }
            ],
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.graph_edge(assertion)


@router.get("/graph/search")
def search_graph(
    q: str,
    db: Session = Depends(get_db),
    workspace_id: str = Depends(current_workspace),
) -> list[dict]:
    return [wire.graph_node(n) for n in queries.search(db, q, workspace_id=workspace_id)]


@router.get("/ingest-jobs")
def get_ingest_jobs(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(IngestJob).order_by(IngestJob.uploaded_at.desc())).scalars()
    return [wire.ingest_job(j) for j in rows]


@router.get("/graph-build")
def get_graph_build(db: Session = Depends(get_db)) -> dict | None:
    build = db.execute(
        select(GraphBuildRun).order_by(GraphBuildRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    return wire.graph_build(build) if build else None


@router.get("/policies")
def get_policies(db: Session = Depends(get_db)) -> list[dict]:
    return [wire.policy(p) for p in db.execute(select(Policy)).scalars()]


@router.post("/policies/{policy_id}/toggle")
def toggle_policy(
    policy_id: str,
    enabled: bool,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    before = policy.enabled
    policy.enabled = enabled

    chain.append(
        db,
        chain.RecordInput(
            action="policy.toggled",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            summary=f"Policy {policy.ref} {'enabled' if enabled else 'disabled'}.",
            changes=[
                {
                    "field": "enabled",
                    "label": "Enabled",
                    "before": "true" if before else "false",
                    "after": "true" if enabled else "false",
                }
            ],
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.policy(policy)

"""
The ingestion pipeline.

One path from a connector to the graph:

    validate access → collect raw records → store evidence → normalise → audit

Evidence is written *before* normalisation, deliberately. If normalisation
fails or produces something suspicious, the raw record it came from is still on
disk to check against. Transforming first and storing after would mean the only
copy of the truth is the interpretation of it.

The pipeline is failure-tolerant in one specific way and intolerant in another.
A connector that dies halfway leaves the records it did collect — a partial
graph with a stated reason is more useful than nothing. But a record that fails
validation is never written, and the rejection is reported on the run, because
a graph that quietly accepts malformed nodes is worse than one that is visibly
incomplete.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from api.connectors.base import (
    ConnectorError,
    EnterpriseConnector,
    NotConfigured,
    RawRecord,
)
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import (
    Connection,
    EvidenceArtifact,
    ExtractionRun,
    KnowledgeSource,
)
from api.graph.normalize import Normalizer
from api.ledger import chain

# Where raw evidence lands. Object storage in a real deployment; a local
# directory here. The interface is the same either way — content-addressed
# writes and a hash recorded alongside.
EVIDENCE_ROOT = Path("evidence")

# A run collects at most this many records. A tenant larger than this is not an
# error, but an unbounded run is: it would hold the transaction open for hours.
# When the cap is hit it is *reported*, never silently applied.
MAX_RECORDS = 20_000


@dataclass(slots=True)
class IngestOutcome:
    run_id: str
    status: str
    records_collected: int = 0
    nodes_created: int = 0
    nodes_updated: int = 0
    assertions_proposed: int = 0
    rejected: list[dict] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


def _store_evidence(records: list[RawRecord], run_id: str) -> tuple[str, str]:
    """Write the raw records and return (path, sha256).

    Content-hashed so the stored evidence is tamper-evident: an artifact
    swapped on disk no longer matches the hash the run committed to.
    """
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        [
            {
                "kind": r.kind,
                "naturalKey": r.natural_key,
                "label": r.label,
                "payload": r.payload,
                "sourceRef": r.source_ref,
                "provenance": r.provenance,
                "layer": r.layer,
                "observedAt": r.observed_at,
                "relations": [list(rel) for rel in r.relations],
            }
            for r in records
        ],
        indent=2,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    path = EVIDENCE_ROOT / f"{run_id}-{digest[:16]}.json"
    path.write_text(payload, encoding="utf-8")
    return str(path), digest


def ingest(
    db: Session,
    connector: EnterpriseConnector,
    *,
    connection: Connection | None = None,
    source: KnowledgeSource | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    include_runtime: bool = True,
    actor: str = "Meridian ingestion",
) -> IngestOutcome:
    """Run one connector end to end."""
    run = ExtractionRun(
        id=new_id("xr"),
        connection_id=connection.id if connection else None,
        connector_id=connector.id,
        extractor_version=connector.extractor_version,
        started_at=utcnow(),
        status="running",
        workspace_id=workspace_id,
    )
    db.add(run)
    db.flush()

    outcome = IngestOutcome(run_id=run.id, status="running")

    check = connector.validate_access()
    if not check.ok:
        run.status = "failed"
        run.error = check.message
        run.finished_at = utcnow()
        if connection is not None:
            connection.status = enums.IngestStatus.ERROR
            connection.error = check.message
        db.flush()
        outcome.status = "failed"
        outcome.error = check.message
        return outcome

    records: list[RawRecord] = []
    collect_error: str | None = None

    try:
        for record in connector.snapshot():
            records.append(record)
            if len(records) >= MAX_RECORDS:
                outcome.truncated = True
                break

        if include_runtime and not outcome.truncated:
            for record in connector.observe():
                records.append(record)
                if len(records) >= MAX_RECORDS:
                    outcome.truncated = True
                    break

    except NotConfigured as exc:
        collect_error = str(exc)
    except ConnectorError as exc:
        collect_error = str(exc)
    except Exception as exc:  # noqa: BLE001
        # An unexpected connector fault must not take the request down. It is
        # recorded on the run with its type so it is debuggable, and whatever
        # was collected before the fault is still normalised below.
        collect_error = f"{type(exc).__name__}: {exc}"

    outcome.records_collected = len(records)

    if records:
        path, digest = _store_evidence(records, run.id)
        db.add(
            EvidenceArtifact(
                id=new_id("ev"),
                kind="log",
                label=f"{connector.name} extraction {run.id}",
                size_label=f"{len(records)} records",
                sha256=digest,
                storage_uri=path,
            )
        )

        normalizer = Normalizer(
            db,
            run,
            source_id=source.id if source else None,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        result = normalizer.ingest(records)

        outcome.nodes_created = result.nodes_created
        outcome.nodes_updated = result.nodes_updated
        outcome.assertions_proposed = result.assertions_proposed
        outcome.rejected = result.rejected

    if collect_error:
        run.status = "partial" if records else "failed"
        run.error = collect_error
        outcome.error = collect_error
    else:
        run.status = "complete"

    if outcome.truncated:
        run.error = (
            f"{run.error + ' ' if run.error else ''}"
            f"Collection stopped at the {MAX_RECORDS:,}-record cap; "
            "this extraction is incomplete."
        )

    run.finished_at = utcnow()
    outcome.status = run.status

    if source is not None:
        source.status = (
            enums.IngestStatus.CONNECTED
            if run.status == "complete"
            else enums.IngestStatus.ERROR
        )

        # Only a run that collected something may restate what the source holds.
        #
        # A failed run collects nothing, and writing that through unconditionally
        # did three separate kinds of damage: it reset `entities` to zero while
        # the previously extracted nodes were still sitting in the graph, it
        # stamped `last_synced_at` so configuration that had not been re-read
        # looked freshly verified, and it computed coverage from
        # `records_collected or 1` — turning zero records into one accepted record
        # and reporting 100%.
        #
        # The third was the most misleading, sitting directly under a comment
        # about not producing flattering numbers. The first two matter more,
        # because a failed sync marking data fresh defeats the staleness check
        # that feasibility refuses on: a 503 from the token endpoint would have
        # silently made a six-week-old tenant snapshot eligible to plan against.
        if outcome.records_collected:
            source.entities = outcome.nodes_created + outcome.nodes_updated
            source.last_synced_at = utcnow()
            # Coverage is what the parser could actually use, not what it saw.
            # Reporting 100% while rejecting records would be the kind of
            # flattering number this product exists to avoid.
            total = outcome.records_collected
            accepted = total - len(outcome.rejected)
            source.coverage = max(0, min(100, round(accepted / total * 100)))

    if connection is not None:
        # The connection's own timestamp records the attempt rather than the
        # result — "we tried and it failed at 04:12" is what an operator watching
        # a connection needs. The source's timestamp is the one that must mean
        # "this data was verified against the live system", because that is the
        # one feasibility reads.
        connection.last_synced_at = utcnow()
        connection.record_count = outcome.records_collected
        connection.status = (
            enums.IngestStatus.CONNECTED
            if run.status in {"complete", "partial"}
            else enums.IngestStatus.ERROR
        )
        connection.error = collect_error

    chain.append(
        db,
        chain.RecordInput(
            action="source.synced",
            actor=actor,
            actor_type=enums.ActorType.SYSTEM,
            summary=(
                f"{connector.name} extraction {run.status} — "
                f"{outcome.records_collected} records, "
                f"{outcome.nodes_created} nodes created, "
                f"{outcome.assertions_proposed} assertions proposed"
                + (f". {len(outcome.rejected)} record(s) rejected." if outcome.rejected else ".")
            ),
            workspace_id=workspace_id,
        ),
    )

    db.flush()
    return outcome

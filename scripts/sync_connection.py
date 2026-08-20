"""
Run one connection's extraction through the real ingestion pipeline.

Equivalent to `POST /api/connections/{id}/sync`, without needing the API running.
It exists because the alternative — calling `Normalizer` directly, as
`ingest_absence_fixtures.py` does — skips everything the pipeline is responsible
for, and the skipping is silent:

  - `source.last_synced_at`, `entities` and `coverage` stay unset, so the graph
    reports as never extracted no matter how much data it holds.
  - `ExtractionRun.status` stays "running" forever, so the run count on the
    activity dashboard drifts up and never resolves.
  - Evidence is not stored before normalising, which is the ordering the audit
    story depends on.

Nodes are identified by `(source_id, natural_key)`, so this updates in place when
the source already holds the configuration and creates only what is new. Pointing
a connection at a different source than its data would silently double the graph
instead of erroring, which is why the source is printed before anything runs.

Usage:

    python scripts/sync_connection.py --connection cn-xxxx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.core.db import SessionLocal
from api.core.ids import utcnow
from api.domain.models import Connection, KnowledgeSource
from api.ingest.pipeline import ingest
from api.services import browser_sessions, connections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True, help="Connection id")
    parser.add_argument(
        "--no-runtime",
        action="store_true",
        help="Skip observed runtime records; extract configuration only.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        cn = db.get(Connection, args.connection)
        if cn is None:
            print(f"No connection {args.connection}")
            return 1

        source = db.get(KnowledgeSource, cn.source_id) if cn.source_id else None
        print(f"connection : {cn.id}  {cn.label}")
        print(f"connector  : {cn.connector_id}")
        print(f"scopes     : {', '.join(cn.granted_scopes or []) or '(none)'}")
        print(f"source     : {source.id if source else '(none)'}"
              f"  {source.name if source else ''}")

        # Reported rather than enforced. A run with no session is legitimate for a
        # connector that reaches everything over an API; it is only fatal for
        # screen discovery, and the connector is what knows the difference.
        status = browser_sessions.status(db, cn.id)
        print(f"session    : {status.message}")

        connector = connections.build_from_connection(cn, db)
        outcome = ingest(
            db,
            connector,
            connection=cn,
            source=source,
            workspace_id=cn.workspace_id,
            include_runtime=not args.no_runtime,
            actor="scripts/sync_connection.py",
        )
        db.commit()

        print()
        print(f"run        : {outcome.run_id}")
        print(f"status     : {outcome.status}")
        print(f"records    : {outcome.records_collected}")
        print(f"created    : {outcome.nodes_created}")
        print(f"updated    : {outcome.nodes_updated}")
        print(f"assertions : {outcome.assertions_proposed}")
        print(f"rejected   : {len(outcome.rejected)}")
        if outcome.truncated:
            print("truncated  : yes — the record cap was reached")
        if outcome.error:
            print(f"error      : {outcome.error}")
        for bad in outcome.rejected[:10]:
            print(f"  rejected: {bad}")

        if source is not None:
            db.refresh(source)
            age = (
                (utcnow() - source.last_synced_at).total_seconds()
                if source.last_synced_at
                else None
            )
            print()
            print(f"source now : entities={source.entities} "
                  f"coverage={source.coverage}% "
                  f"last_synced={'just now' if age is not None and age < 120 else source.last_synced_at}")

        return 0 if outcome.status in {"complete", "partial"} else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

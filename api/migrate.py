"""
Additive schema migrations.

`create_all` in `main.py` creates missing *tables* and silently ignores missing
*columns* on tables that already exist. That is exactly how a schema change
reaches production without applying: the app starts, the query fails at
runtime, and nothing in the startup path complained.

This module closes that gap for additive changes — new nullable columns and new
indexes — which is what every migration so far has been. It is deliberately not
a general migration framework: a rename or a type change needs Alembic and a
considered data-migration plan, and pretending otherwise here would invite
someone to attempt one.

Every statement is `IF NOT EXISTS`, so running this repeatedly is safe and it
can run on startup as well as by hand:

    python -m api.migrate
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from api.core.db import engine as default_engine

logger = logging.getLogger("meridian.migrate")

#: Each entry is (description, SQL). Order matters — a partial index cannot be
#: created before the columns it references.
MIGRATIONS: list[tuple[str, str]] = [
    (
        "assertions.sequence",
        "ALTER TABLE assertions ADD COLUMN IF NOT EXISTS sequence INTEGER",
    ),
    (
        "assertions.sequence_scope",
        "ALTER TABLE assertions ADD COLUMN IF NOT EXISTS sequence_scope VARCHAR(200)",
    ),
    (
        "assertions.condition",
        "ALTER TABLE assertions ADD COLUMN IF NOT EXISTS condition JSON",
    ),
    (
        # Ordered relations are read by scope, so the scope leads the index.
        "ix_assertion_sequence",
        """
        CREATE INDEX IF NOT EXISTS ix_assertion_sequence
            ON assertions (sequence_scope, sequence)
            WHERE sequence IS NOT NULL
        """,
    ),
    (
        # The transcript's `step_order_unique`, as a database guarantee.
        # Partial on superseded_at so correcting a step's position stays
        # possible — superseded rows keep their old position by design.
        "uq_assertion_sequence_live",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_assertion_sequence_live
            ON assertions (sequence_scope, predicate, sequence)
            WHERE superseded_at IS NULL
              AND sequence IS NOT NULL
              AND sequence_scope IS NOT NULL
        """,
    ),
    (
        "connections.credentials_encrypted",
        # Added when credential encryption landed, but never given a migration
        # — so it existed on any database created afterwards and was missing
        # from every one created before. The test database, which persists
        # between runs, was in the second category, and the failure surfaced as
        # an unrelated feature's tests erroring on insert.
        """
        ALTER TABLE connections
            ADD COLUMN IF NOT EXISTS credentials_encrypted TEXT
        """,
    ),
    (
        "connections.settings",
        """
        ALTER TABLE connections
            ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb
        """,
    ),
    (
        "browser_sessions",
        # Sessions, not credentials. See BrowserSessionRecord for why that
        # distinction carries the security argument.
        """
        CREATE TABLE IF NOT EXISTS browser_sessions (
            id              VARCHAR(64) PRIMARY KEY,
            connection_id   VARCHAR(64) NOT NULL,
            workspace_id    VARCHAR(64),
            state_encrypted TEXT NOT NULL,
            captured_by     VARCHAR(200) NOT NULL DEFAULT '',
            captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at      TIMESTAMPTZ,
            revoked_at      TIMESTAMPTZ,
            revoked_reason  VARCHAR(200),
            last_used_at    TIMESTAMPTZ
        )
        """,
    ),
    (
        "browser_sessions.indexes",
        """
        CREATE INDEX IF NOT EXISTS ix_browser_session_live
            ON browser_sessions (connection_id, revoked_at)
        """,
    ),
    (
        "graph_nodes.attributes",
        # Before this the normaliser kept only `description` from a connector's
        # payload and dropped everything else, so the graph knew that two nodes
        # were related but not what either one was.
        #
        # Backfilled to '{}' rather than left NULL: every read path would
        # otherwise need a null guard, and "no attributes" and "attributes not
        # yet extracted" are the same thing for a node that predates this.
        """
        ALTER TABLE graph_nodes
            ADD COLUMN IF NOT EXISTS attributes JSONB NOT NULL DEFAULT '{}'::jsonb
        """,
    ),
]


def run(engine: Engine | None = None) -> list[str]:
    """Apply every pending migration. Returns what was executed.

    `engine` is injectable so the test database gets the same treatment as the
    application one — it persists between runs, so `create_all` alone leaves it
    missing any column added since it was first created.
    """
    target = engine if engine is not None else default_engine
    applied: list[str] = []
    with target.begin() as conn:
        for name, sql in MIGRATIONS:
            conn.execute(text(sql))
            applied.append(name)
    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in run():
        logger.info("applied %s", name)
    logger.info("Schema up to date.")

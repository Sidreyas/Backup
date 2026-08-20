"""
The persistent domain model.

This schema is the server-side counterpart of `src/lib/types.ts`. Where the two
differ, the difference is deliberate and commented — mostly because the wire
format flattens something the database keeps normalised (criteria, steps,
results), or because the database records something the UI never shows (the
provenance spine).

Three design decisions run through the whole file:

1. **Nothing governance-bearing is deleted.** Superseding rows are added and
   the old ones marked, so "what did the graph believe in March" stays an
   answerable question. Deletes exist only for genuinely ephemeral things
   (a saved suite the user removed).

2. **Assertions are reified.** A graph edge is not a foreign key between two
   nodes; it is a row with its own evidence, confidence, author and validity
   window. The transcript asks for this and it is the difference between a
   graph that can be audited and one that can only be browsed.

3. **Bi-temporality where it earns its keep.** Assertions and configuration
   snapshots carry both `valid_from/valid_to` (when the fact was true of the
   world) and `recorded_at/superseded_at` (when the system believed it). Rows
   without a meaningful world-time — an audit entry, a test result — carry only
   the system time, because inventing a validity window for an event that
   happened once would be noise.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.db import Base
from api.core.ids import new_id, utcnow
from api.domain import enums

# JSONB is used for genuinely schemaless leaf data — a connector's raw payload,
# a list of warning strings, a rubric's citations. It is never used to avoid
# modelling something the application queries or joins on.
JSON = JSONB


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ----------------------------------------------------------------- org scope


class Workspace(Base, TimestampMixin):
    """A governance boundary — a business unit or regulated entity.

    Policies, gates and the audit chain are scoped here, so a change approved
    in one workspace can never satisfy a gate in another.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ws"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    compliance: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    region: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    projects: Mapped[list[Project]] = relationship(back_populates="workspace")


class Project(Base, TimestampMixin):
    """Scopes the working set inside a workspace."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pj"))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=enums.ProjectStatus.ACTIVE)
    platform: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    lead: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    monthly_spend_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="projects")


class User(Base, TimestampMixin):
    """A person who can act. Actors are recorded by name and email on the audit
    entry itself rather than by foreign key, so the record stays readable if a
    user row is later removed — an audit trail that breaks when someone leaves
    the company is not an audit trail."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("u"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    initials: Mapped[str] = mapped_column(String(8), default="", nullable=False)


# -------------------------------------------------------------- connectors


class Connection(Base, TimestampMixin):
    """An installed connection to an external system.

    Separate from KnowledgeSource because a connector can be healthy while its
    source is empty, and a source can hold good data long after its credentials
    expired. Collapsing them would make "is this working?" and "is this useful?"
    the same question, and they are not.

    Credentials are *not* stored here. `secret_ref` names an entry in the
    process environment or a secret manager; the database holds the pointer so
    a database dump is not a credential leak.
    """

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cn"))
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=enums.IngestStatus.INDEXING)
    auth_method: Mapped[str] = mapped_column(String(32), default=enums.AuthMethod.OAUTH2)
    granted_scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    cadence: Mapped[str] = mapped_column(String(32), default=enums.SyncCadence.DAILY)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    connected_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[str | None] = mapped_column(String(64))
    secret_ref: Mapped[str | None] = mapped_column(String(200))
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # Encrypted credential blob — see api/core/secrets.py. Opaque here on
    # purpose: nothing that reads this table can accidentally log a secret,
    # because there is nothing readable in the column to log.
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)

    # Non-secret connector settings (report names, API version, host). Kept
    # separate from the encrypted blob so they can be shown, searched and
    # edited without a decryption round-trip.
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class CustomConnector(Base, TimestampMixin):
    """A connector the customer registered themselves.

    Built-in connector *definitions* live in code (`api/connectors/registry.py`)
    because they ship with the product and are versioned with it. Only
    customer-authored ones need rows.
    """

    __tablename__ = "custom_connectors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cx"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    vendor: Mapped[str] = mapped_column(String(200), default="Internal", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="custom")
    kind: Mapped[str] = mapped_column(String(32), default=enums.SourceKind.PLATFORM)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    auth_methods: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    provides: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class KnowledgeSource(Base, TimestampMixin):
    """What was indexed once a connection succeeded."""

    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("src"))
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=enums.IngestStatus.CONNECTED)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    staleness_threshold_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    entities: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coverage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_label: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    owner: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


# ------------------------------------------------------------- provenance


class EvidenceArtifact(Base):
    """Heavy evidence lives outside the database; this row is the handle.

    `sha256` is the point of the table. The artifact bytes sit in object
    storage, and the hash recorded here is what makes the pair tamper-evident:
    an artifact swapped in storage no longer matches the row that an approval
    cited.
    """

    __tablename__ = "evidence_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ev"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    size_label: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_uri: Mapped[str | None] = mapped_column(Text)
    case_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("case_results.id", ondelete="CASCADE"), index=True
    )
    test_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ExtractionRun(Base):
    """One execution of a connector against one connection.

    The PROV-O `Activity`: every node and assertion the run produced points
    back here, so "where did this come from" resolves to a specific run of a
    specific extractor version at a specific time — not merely to a source
    system.
    """

    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("xr"))
    connection_id: Mapped[str | None] = mapped_column(String(64), index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), default="1", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    nodes_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assertions_proposed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)


# ------------------------------------------------------------------- graph


class GraphNode(Base, TimestampMixin):
    """An entity in the knowledge graph.

    `source_ref` is a deep link back into the origin system and `provenance` is
    the human-readable citation shown in the UI. Both are required rather than
    optional: a node nobody can trace back to something real is exactly the
    kind of confident-looking fabrication this product exists to prevent.
    """

    __tablename__ = "graph_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("n"))
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(400), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(String(64), index=True)
    provenance: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, default="", nullable=False)
    criticality: Mapped[str] = mapped_column(String(16), default=enums.Criticality.MEDIUM)
    owner: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Layout hint, normalised 0–1. Persisted rather than recomputed so a graph
    # a user has arranged stays arranged between sessions; a real layout engine
    # would seed these on first build.
    x: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    y: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    # --- entity resolution ------------------------------------------------
    # The stable identifier this node has *in its source system* (a Workday
    # WID, a Jira issue key, a file path). Resolution matches on this plus
    # source, never on the display label — merging two nodes because they are
    # both called "Approval" would corrupt the graph silently.
    natural_key: Mapped[str | None] = mapped_column(String(500), index=True)
    extraction_run_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # What the connector extracted, beyond label and description. Until this
    # existed the normaliser kept only `description` and dropped every other
    # field a connector had gone to the trouble of reading — a step's type, a
    # report's data source, whether an observed step appears in no definition.
    # The graph could say two nodes were related but not what either one *was*,
    # which pushed every such question back to re-reading the source system.
    #
    # Deliberately schemaless: the shape differs per connector and per kind,
    # and a column per attribute would mean a migration per connector. Anything
    # the product reasons over structurally earns a real column instead.
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_id", "natural_key", name="uq_node_source_natural_key"),
        Index("ix_node_workspace_kind", "workspace_id", "kind"),
    )


class Assertion(Base):
    """A reified graph edge.

    The transcript's key structural request, and the reason this is a table
    rather than a `graph_edges` join: a claim that A relates to B is itself a
    thing with an author, evidence, a confidence and a validity window. Storing
    it as a bare foreign key throws all of that away and leaves you unable to
    answer "who said so, and what did they look at".

    The frontend still receives these flattened into its simpler `GraphEdge`
    shape — see `api/schemas/graph.py`. That is a presentation choice, not a
    modelling one; the extra fields are queryable here whether or not the
    current UI draws them.
    """

    __tablename__ = "assertions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("as"))
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    subject_id: Mapped[str] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    predicate: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_id: Mapped[str] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    confidence: Mapped[str] = mapped_column(
        String(16), default=enums.LinkConfidence.MEDIUM, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=enums.AssertionStatus.PROPOSED, nullable=False, index=True
    )

    # Why the system proposed this. Shown to the human who is asked to confirm
    # it — a link with no rationale cannot be meaningfully reviewed.
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # PROV-O agent: who or what asserted this.
    asserted_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    asserted_by_type: Mapped[str] = mapped_column(String(16), default=enums.ActorType.SYSTEM)
    extraction_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    evidence_artifact_id: Mapped[str | None] = mapped_column(String(64))

    confirmed_by: Mapped[str | None] = mapped_column(String(200))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- ordering ----------------------------------------------------------
    # Most relations have no order: GOVERNED_BY is not third of anything. But
    # an approval chain does, and position is the whole question a change-impact
    # analysis asks — "what breaks if we add a Regional HR approval above 15
    # days" is unanswerable if the graph knows only that the steps are
    # connected, not where in the sequence each one sits.
    #
    # Nullable throughout, because inventing a position for an unordered
    # relation would be worse than omitting one.
    sequence: Mapped[int | None] = mapped_column(Integer)
    #: What this is ordered *within* — the business process definition, the
    #: pipeline. Position 3 is only meaningful relative to a scope, and two
    #: processes both having a step 3 is not a conflict.
    sequence_scope: Mapped[str | None] = mapped_column(String(200))
    #: The branch rule, as the source system states it. Stored as given and
    #: rendered as text rather than parsed into an expression tree: making
    #: conditions evaluable is a much larger piece of work and nothing asks
    #: for it yet.
    condition: Mapped[dict | None] = mapped_column(JSON)

    # --- bi-temporality ---------------------------------------------------
    # valid_*: when this was true of the world. recorded_at/superseded_at: when
    # Meridian believed it. Both are needed to answer "what did we think was
    # true, as of a date" — the question every drift and audit conversation
    # eventually becomes.
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_assertion_triple", "subject_id", "predicate", "object_id"),
        Index("ix_assertion_live", "workspace_id", "superseded_at"),
        # The transcript's `step_order_unique` validation, enforced by the
        # database rather than by a checker that can be bypassed. Two live
        # steps claiming position 3 of the same process is a contradiction,
        # and catching it at ingest beats discovering it in a traversal.
        #
        # Partial on `superseded_at IS NULL`: superseded rows keep their old
        # position by design, so a full unique index would make correcting a
        # step's order impossible.
        Index(
            "uq_assertion_sequence_live",
            "sequence_scope",
            "predicate",
            "sequence",
            unique=True,
            postgresql_where=text(
                "superseded_at IS NULL AND sequence IS NOT NULL "
                "AND sequence_scope IS NOT NULL"
            ),
        ),
    )


class GraphBuildRun(Base):
    """A graph build, shown as a live pipeline on the ingestion page."""

    __tablename__ = "graph_builds"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("gb"))
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    nodes_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    edges_proposed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    edges_confirmed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unresolved: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class IngestJob(Base):
    """One artefact pushed into Meridian, tracked through staged ingestion.

    Staged rather than a single done-flag because each stage fails differently:
    a PDF may parse but yield no requirements; a repo may index but resolve no
    links to the business layer. The stage is what tells a user why the graph
    looks thin.
    """

    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ing"))
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(400), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default=enums.SourceKind.DOCUMENT)
    doc_kind: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(120), default="Upload", nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default=enums.UploadStage.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_label: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    uploaded_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    entities_extracted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    links_proposed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_coverage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    storage_uri: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)


class BrowserSessionRecord(Base):
    """An administrator-captured browser session for a connection.

    Some enterprise configuration exists only on screens — validation rules,
    conditional visibility, picklist values, the lookup tables behind a leave
    calculation. Reading it needs an authenticated browser, and the only
    honest way to get one is for a human to sign in themselves.

    So this table holds *sessions*, never credentials. The distinction is the
    whole security argument:

      - Meridian never receives the password, so it cannot replay a login.
      - Multi-factor is satisfied by the person, natively, not worked around.
      - The session expires and discovery stops until someone signs in again.
        That is a feature. A capture that worked forever would be a permanent
        unattended grant to the customer's tenant, which is a much worse thing
        to hold than a short-lived cookie.

    `state_encrypted` is a bearer credential — whoever holds it *is* the
    signed-in administrator until it lapses — so it is encrypted at rest with
    the same machinery as connector credentials and is never returned by the
    API. Only presence, capturer and expiry are readable.
    """

    __tablename__ = "browser_sessions"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: new_id("bs")
    )
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    #: Playwright `storageState`, encrypted. Opaque on purpose: nothing that
    #: reads this table can accidentally log a session, because there is
    #: nothing readable in the column to log.
    state_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    #: Who signed in. Recorded because a session carries that person's
    #: permissions — what discovery can read is exactly what they could see,
    #: and an auditor asking "whose access produced this data" needs an answer.
    captured_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    #: When the session stops working. Estimated from the tenant's idle timeout
    #: rather than known — Workday does not publish it — so treated as a hint
    #: for the UI, never as a guarantee. Replay still fails gracefully on an
    #: expiry that arrives early.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Cleared when superseded or revoked, rather than deleted. A session that
    #: was used to extract configuration is part of that data's provenance, and
    #: deleting the row would leave extracted nodes attributed to nothing.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(200))

    #: Last time replay actually used this session. Distinguishes "captured and
    #: forgotten" from "captured and working", which look identical otherwise.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_browser_session_live", "connection_id", "revoked_at"),
    )


# ------------------------------------------------------------ requirements


class Requirement(Base, TimestampMixin):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("req"))
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stage: Mapped[str] = mapped_column(
        String(32), default=enums.RequirementStage.DRAFT, nullable=False, index=True
    )
    requested_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    requested_by_role: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    platform: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    system_kind: Mapped[str] = mapped_column(String(32), default=enums.SystemKind.VENDOR_PLATFORM)

    # Urgency, distinct from risk_level. A low-risk change can be urgent and a
    # high-risk one can be nice-to-have; collapsing them would let urgency
    # argue its way past a risk gate.
    priority: Mapped[str] = mapped_column(String(16), default=enums.Criticality.MEDIUM)
    risk_level: Mapped[str] = mapped_column(String(16), default=enums.Criticality.MEDIUM)

    impacted_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """A turn in the requirement discussion.

    Token counts and cost sit on the message because per-turn attribution is a
    product feature, not telemetry: the platform claims to account for what AI
    work cost, and that claim needs a per-turn number behind it.
    """

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("m"))
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    citations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    dissent: Mapped[dict | None] = mapped_column(JSON)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String(120))
    crawl: Mapped[dict | None] = mapped_column(JSON)
    generated_cases: Mapped[list | None] = mapped_column(JSON)
    run_summary: Mapped[dict | None] = mapped_column(JSON)
    tool_calls: Mapped[list | None] = mapped_column(JSON)

    requirement: Mapped[Requirement] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_chat_requirement_at", "requirement_id", "at"),)


class ImpactAnalysis(Base):
    __tablename__ = "impact_analyses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ia"))
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Stated blind spots. An analysis that lists nothing it could not reason
    # about is claiming omniscience, which is the failure mode this field
    # exists to make visible.
    blind_spots: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    environment_fingerprint: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # Set when the analysis came from the stub path rather than a live model,
    # so nothing downstream mistakes placeholder reasoning for the real thing.
    source: Mapped[str] = mapped_column(String(16), default="llm", nullable=False)

    items: Mapped[list[ImpactItem]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class ImpactItem(Base):
    __tablename__ = "impact_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ii"))
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("impact_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_label: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    node_kind: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default=enums.ImpactSeverity.MINOR)
    confidence: Mapped[str] = mapped_column(String(16), default=enums.LinkConfidence.MEDIUM)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provenance: Mapped[str] = mapped_column(Text, default="", nullable=False)
    owner: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    covered_by_test_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    coverage_gap: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    analysis: Mapped[ImpactAnalysis] = relationship(back_populates="items")

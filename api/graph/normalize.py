"""
Normalisation: raw records into graph nodes and assertions.

This is where the transcript's central engineering principle is enforced:

    the extractor navigates and captures
    → a deterministic parser produces the values
    → a schema validator checks them
    → only then does anything reach the graph

No LLM runs in this path. A model may later *propose* an assertion, but it does
so as a candidate with a confidence and an author, on the same footing as any
other proposal — it never writes a node directly.

Two rules govern writes:

  1. **Resolve on natural key, never on label.** Two nodes merge only when they
     carry the same source-system identifier. Merging on display name would
     silently fuse every object called "Approval" across a tenant.

  2. **Supersede, never overwrite.** A changed fact produces a new assertion
     and marks the old one superseded, so "what did the graph believe last
     quarter" stays answerable. Node *attributes* are updated in place, because
     a node is an identity and its label changing is not a new identity — but
     every relationship between nodes is versioned.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.connectors.base import RawRecord, RelationOrder
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import Assertion, ExtractionRun, GraphNode

# Which node kind a raw record maps to. The connector proposes a kind; this is
# the allow-list that keeps a connector from inventing one the UI cannot draw.
VALID_KINDS = {k.value for k in enums.NodeKind}

# Predicates the graph understands. Drawn from the transcript's edge taxonomy,
# restricted to what the current product actually reasons over — an unbounded
# predicate vocabulary makes traversal queries impossible to write correctly.
VALID_PREDICATES = {
    # structure
    "HAS_STEP",
    "NEXT_STEP",
    # Distinct from NEXT_STEP rather than the same edge with a footnote:
    # "always goes here" and "goes here only when the change exceeds 10%" are
    # different claims, and collapsing them loses the branch that makes an
    # approval chain worth modelling.
    "CONDITIONAL_NEXT_STEP",
    # What a process run *actually did*, as against what HAS_STEP says it was
    # configured to do. A separate predicate rather than a flag because the two
    # are different claims with different authors — one is the tenant's
    # configuration, the other is an observation of a single execution — and
    # the entire drift analysis is the comparison between them. Sharing an
    # edge would make "configured but never runs" unaskable.
    "HAS_OBSERVED_STEP",
    "ROUTES_TO",
    "HAS_FIELD",
    "REFERENCES_OBJECT",
    # implementation
    "IMPLEMENTS",
    "IMPLEMENTED_BY",
    "CONFIGURES",
    "MODIFIES",
    "DEPLOYED_TO",
    # integration
    "EXPOSES",
    "CALLS",
    "READS",
    "WRITES",
    "INTEGRATES_WITH",
    # An API operation carrying a business object, from the OpenAPI spec or the
    # Graph schema. Distinct from READS/WRITES, which describe an integration
    # this tenant *built*: this says the platform exposes the object at all,
    # which is the question behind "could anything have read this field".
    "EXPOSES_OBJECT",
    # governance
    "SECURED_BY",
    "APPROVED_BY",
    "GOVERNED_BY",
    "TESTED_BY",
    "DEPENDS_ON",
    "DOCUMENTED_IN",
}


@dataclass(slots=True)
class NormalizeResult:
    nodes_created: int = 0
    nodes_updated: int = 0
    assertions_proposed: int = 0
    assertions_superseded: int = 0
    # Records the normaliser refused, with the reason. Surfaced on the
    # extraction run rather than logged and forgotten: a connector emitting
    # records the graph rejects is a bug someone needs to see.
    rejected: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.rejected is None:
            self.rejected = []


class Normalizer:
    """Writes records into the graph for one extraction run."""

    def __init__(
        self,
        db: Session,
        run: ExtractionRun,
        *,
        source_id: str | None,
        workspace_id: str | None,
        project_id: str | None = None,
    ) -> None:
        self.db = db
        self.run = run
        self.source_id = source_id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.result = NormalizeResult()

        # natural_key → node id, for resolving relations within this run
        # without a query per edge.
        self._resolved: dict[str, str] = {}

    # --- nodes -------------------------------------------------------------

    def _validate(self, record: RawRecord) -> str | None:
        """Return a rejection reason, or None if the record is acceptable."""
        if record.kind not in VALID_KINDS:
            return f"unknown node kind '{record.kind}'"
        if not record.natural_key:
            return "missing natural key"
        if not record.label.strip():
            return "missing label"
        return None

    def upsert_node(self, record: RawRecord) -> GraphNode | None:
        reason = self._validate(record)
        if reason:
            self.result.rejected.append(
                {"naturalKey": record.natural_key, "reason": reason}
            )
            return None

        existing = self.db.execute(
            select(GraphNode).where(
                GraphNode.source_id == self.source_id,
                GraphNode.natural_key == record.natural_key,
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Attributes update in place: a node is an identity, and a renamed
            # object is the same object. The *relationships* are what get
            # versioned, below.
            existing.label = record.label
            existing.provenance = record.provenance or existing.provenance
            existing.source_ref = record.source_ref or existing.source_ref
            existing.description = str(record.payload.get("description") or "") or (
                existing.description
            )
            # Replaced wholesale rather than merged: the payload is what the
            # source says *now*, and merging would let an attribute the source
            # has removed survive indefinitely as a fact nobody can trace.
            existing.attributes = dict(record.payload or {})
            existing.last_verified_at = utcnow()
            existing.extraction_run_id = self.run.id
            self.result.nodes_updated += 1
            self._resolved[record.natural_key] = existing.id
            return existing

        node = GraphNode(
            id=new_id("n"),
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            label=record.label,
            kind=record.kind,
            source_id=self.source_id,
            provenance=record.provenance,
            source_ref=record.source_ref,
            description=str(record.payload.get("description") or ""),
            attributes=dict(record.payload or {}),
            natural_key=record.natural_key,
            extraction_run_id=self.run.id,
            last_verified_at=utcnow(),
            # Seeded deterministically from the key so a graph without a layout
            # pass still renders as something other than a single point. A real
            # layout engine overwrites these on first draw.
            x=_spread(record.natural_key, salt=17),
            y=_spread(record.natural_key, salt=31),
        )
        self.db.add(node)
        self.db.flush()
        self.result.nodes_created += 1
        self._resolved[record.natural_key] = node.id
        return node

    # --- assertions --------------------------------------------------------

    def _resolve(self, natural_key: str) -> str | None:
        """Find the node id for a natural key, within this source.

        Cross-source resolution (the Jira issue a GitHub PR mentions) is
        deliberately *not* attempted here — that is a mapping question with its
        own confidence, handled in `resolve.py`. Silently linking across
        sources on a string match is how a graph acquires confident nonsense.
        """
        if natural_key in self._resolved:
            return self._resolved[natural_key]
        node = self.db.execute(
            select(GraphNode).where(
                GraphNode.source_id == self.source_id,
                GraphNode.natural_key == natural_key,
            )
        ).scalar_one_or_none()
        if node is not None:
            self._resolved[natural_key] = node.id
            return node.id
        return None

    def assert_relation(
        self,
        subject_id: str,
        predicate: str,
        object_id: str,
        *,
        rationale: str,
        confidence: str = enums.LinkConfidence.MEDIUM,
        asserted_by: str = "",
        asserted_by_type: str = enums.ActorType.SYSTEM,
        order: RelationOrder | None = None,
    ) -> Assertion | None:
        """Propose a relationship, superseding any live claim it replaces.

        Idempotent on re-extraction: if the identical live assertion already
        exists, nothing is written. Without that check every sync would append
        a duplicate and the graph would grow without changing.
        """
        if predicate not in VALID_PREDICATES:
            self.result.rejected.append(
                {"predicate": predicate, "reason": "unknown predicate"}
            )
            return None

        live = self.db.execute(
            select(Assertion).where(
                Assertion.subject_id == subject_id,
                Assertion.predicate == predicate,
                Assertion.object_id == object_id,
                Assertion.superseded_at.is_(None),
            )
        ).scalar_one_or_none()

        seq = order.sequence if order else None
        scope = order.scope if order else None
        condition = order.condition if order else None

        if live is not None:
            # Same claim, still current. Re-observing it is not new
            # information; touching valid_from records that we saw it again.
            #
            # Position is part of the claim: a step that moved from third to
            # fourth is a different assertion about the world, and treating it
            # as "already known" would leave the graph asserting an ordering
            # the source system no longer has.
            unchanged = (
                live.confidence == confidence
                and live.sequence == seq
                and live.sequence_scope == scope
                and live.condition == condition
            )
            if unchanged:
                return live
            # Something changed — that *is* new information, so the old claim
            # is superseded rather than edited.
            live.superseded_at = utcnow()
            live.status = enums.AssertionStatus.SUPERSEDED
            self.result.assertions_superseded += 1
            # Flushed before the replacement is added: the live-uniqueness
            # index on (scope, predicate, sequence) would otherwise see both
            # rows unsuperseded at once and reject the correction.
            self.db.flush()

        assertion = Assertion(
            id=new_id("as"),
            workspace_id=self.workspace_id,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            label=predicate.replace("_", " ").lower(),
            confidence=confidence,
            status=enums.AssertionStatus.PROPOSED,
            rationale=rationale,
            asserted_by=asserted_by or f"{self.run.connector_id} extractor",
            asserted_by_type=asserted_by_type,
            extraction_run_id=self.run.id,
            valid_from=utcnow(),
            sequence=seq,
            sequence_scope=scope,
            condition=condition,
        )
        self.db.add(assertion)
        if live is not None:
            self.db.flush()
            live.superseded_by_id = assertion.id

        self.result.assertions_proposed += 1
        return assertion

    # --- driving -----------------------------------------------------------

    def _retire_displaced_orderings(self, records: list[RawRecord]) -> None:
        """Supersede live positions this batch is about to reassign.

        Only those whose occupant is changing: a step that stays where it is
        keeps its assertion, so re-extracting an unchanged process writes
        nothing. Retiring every position unconditionally would churn the whole
        chain on every sync and bury real changes in noise.
        """
        incoming: dict[tuple[str, str, int], str] = {}
        for record in records:
            subject_id = self._resolved.get(record.natural_key)
            if subject_id is None:
                continue
            for (predicate, _), order in record.ordering.items():
                incoming[(order.scope, predicate, order.sequence)] = subject_id

        if not incoming:
            return

        for (scope, predicate, sequence), subject_id in incoming.items():
            live = self.db.execute(
                select(Assertion).where(
                    Assertion.sequence_scope == scope,
                    Assertion.predicate == predicate,
                    Assertion.sequence == sequence,
                    Assertion.superseded_at.is_(None),
                )
            ).scalar_one_or_none()

            # Unchanged occupant: leave it alone so re-extraction is a no-op.
            if live is None or live.subject_id == subject_id:
                continue

            live.superseded_at = utcnow()
            live.status = enums.AssertionStatus.SUPERSEDED
            self.result.assertions_superseded += 1

        # Flushed so the index sees the vacancies before replacements arrive.
        self.db.flush()

    def ingest(self, records: list[RawRecord]) -> NormalizeResult:
        """Three passes: nodes, then displaced orderings, then relations.

        Two passes are needed because a record can reference a target that
        appears later in the stream; one pass would drop those edges depending
        on emission order, which is the kind of bug that makes a graph quietly
        incomplete.

        The third exists because positions are *exclusive*. When two steps swap
        places, processing them one at a time means the first tries to claim a
        position the second still holds — the batch deadlocks against the
        live-uniqueness index even though the end state is perfectly valid. So
        every position this batch is about to reassign is retired first, and
        the batch is treated as one reordering rather than a series of moves.
        """
        for record in records:
            self.upsert_node(record)

        self._retire_displaced_orderings(records)

        for record in records:
            subject_id = self._resolved.get(record.natural_key)
            if subject_id is None:
                continue
            for predicate, target_key in record.relations:
                object_id = self._resolve(target_key)
                if object_id is None:
                    # The target is not in this source. Recorded as unresolved
                    # so cross-source mapping can pick it up later, rather than
                    # invented or dropped.
                    self.result.rejected.append(
                        {
                            "subject": record.natural_key,
                            "predicate": predicate,
                            "target": target_key,
                            "reason": "target not found in this source",
                        }
                    )
                    continue
                self.assert_relation(
                    subject_id,
                    predicate,
                    object_id,
                    rationale=(
                        f"Declared by {self.run.connector_id} in "
                        f"{record.provenance or record.natural_key}."
                    ),
                    # Structure a source system states about itself is strong
                    # evidence, but still a claim about what the extractor read
                    # rather than a human-confirmed fact.
                    confidence=enums.LinkConfidence.HIGH,
                    order=record.ordering.get((predicate, target_key)),
                )

        self.run.nodes_created = self.result.nodes_created
        self.run.assertions_proposed = self.result.assertions_proposed
        self.run.stats = {
            "nodesCreated": self.result.nodes_created,
            "nodesUpdated": self.result.nodes_updated,
            "assertionsProposed": self.result.assertions_proposed,
            "assertionsSuperseded": self.result.assertions_superseded,
            "rejected": self.result.rejected[:100],
            "rejectedCount": len(self.result.rejected),
        }
        self.db.flush()
        return self.result


def _spread(key: str, salt: int) -> float:
    """Deterministic 0.08–0.92 coordinate from a string.

    Kept off the edges so nodes do not render clipped against the viewport
    border before a layout pass runs.
    """
    h = 0
    for ch in key:
        h = (h * 31 + ord(ch) + salt) & 0xFFFFFFFF
    return 0.08 + (h % 1000) / 1000 * 0.84

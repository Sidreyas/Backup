"""
Graph traversal and retrieval.

Postgres, not Neo4j. The traversals this product actually performs are bounded
blast-radius walks — "what does this node reach within N hops" — and a
recursive CTE does that well at the scale a single tenant's configuration
reaches. A second datastore would buy deeper traversal at the cost of keeping
two systems consistent, which is a real operational tax to pay for a query
shape nobody has needed yet. If traversal depth becomes the bottleneck, this
module is the seam to swap.

Every traversal here is confidence-aware. An unconfirmed assertion is a
hypothesis, and a blast radius computed as though hypotheses were facts would
overstate impact — which trains people to ignore impact analysis, the worst
possible outcome for a product built on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.domain import enums
from api.domain.models import Assertion, GraphNode

# Confidence ordering, strongest first. Used to decide whether a path is strong
# enough to report at a given threshold.
_RANK = {
    enums.LinkConfidence.CONFIRMED: 3,
    enums.LinkConfidence.HIGH: 2,
    enums.LinkConfidence.MEDIUM: 1,
    enums.LinkConfidence.LOW: 0,
}


@dataclass(slots=True)
class Reached:
    """A node reached by traversal, with how it was reached."""

    node: GraphNode
    depth: int
    #: Weakest confidence on the path — a chain is only as strong as its
    #: weakest link, and reporting the strongest would overstate certainty.
    path_confidence: str
    #: Assertion ids traversed, so the UI can show why this node is implicated.
    via: list[str]
    #: Position within its ordered scope, when the assertion that reached this
    #: node carried one. None for the majority of relations, which have no
    #: order — `GOVERNED_BY` is not third of anything.
    sequence: int | None = None
    #: What `sequence` is relative to: a business process definition, a
    #: pipeline. Position 3 is meaningless without it.
    sequence_scope: str | None = None


def live_assertions(db: Session, workspace_id: str | None = None) -> list[Assertion]:
    """Assertions that have not been superseded or refuted.

    The graph's current belief. Superseded rows stay in the table — that is the
    history — but they are not what anyone means by "the graph".
    """
    stmt = select(Assertion).where(
        Assertion.superseded_at.is_(None),
        Assertion.status != enums.AssertionStatus.REFUTED,
    )
    if workspace_id:
        stmt = stmt.where(Assertion.workspace_id == workspace_id)
    return list(db.execute(stmt).scalars())


def nodes_for(db: Session, workspace_id: str | None = None) -> list[GraphNode]:
    stmt = select(GraphNode)
    if workspace_id:
        stmt = stmt.where(GraphNode.workspace_id == workspace_id)
    return list(db.execute(stmt).scalars())


@dataclass(slots=True)
class OrderedStep:
    """One position in an ordered chain."""

    node: GraphNode
    sequence: int
    predicate: str
    #: The branch rule gating this step, or None if it always runs. Present
    #: only on CONDITIONAL_NEXT_STEP.
    condition: dict | None
    assertion_id: str


def ordered_chain(
    db: Session,
    scope: str,
    *,
    predicate: str = "HAS_STEP",
    workspace_id: str | None = None,
) -> list[OrderedStep]:
    """The steps of one process, in the order the source system defines.

    Separate from `neighbours` on purpose. A blast radius is a *set* — the
    things a change touches, which have no inherent order — while a process is
    a *sequence*. Sorting the blast radius by sequence would impose an order on
    nodes that mostly have none, and reading a chain by traversing adjacency
    would return it in whatever order the walk happened to reach things.

    This is what answers "what is the third approval" and "what sits above the
    15-day threshold", which adjacency alone cannot.
    """
    stmt = (
        select(Assertion, GraphNode)
        .join(GraphNode, GraphNode.id == Assertion.subject_id)
        .where(
            Assertion.sequence_scope == scope,
            Assertion.predicate == predicate,
            Assertion.sequence.is_not(None),
            Assertion.superseded_at.is_(None),
            Assertion.status != enums.AssertionStatus.REFUTED,
        )
        .order_by(Assertion.sequence)
    )
    if workspace_id:
        stmt = stmt.where(Assertion.workspace_id == workspace_id)

    return [
        OrderedStep(
            node=node,
            sequence=assertion.sequence,
            predicate=assertion.predicate,
            condition=assertion.condition,
            assertion_id=assertion.id,
        )
        for assertion, node in db.execute(stmt).all()
    ]


def neighbours(
    db: Session,
    node_ids: list[str],
    *,
    max_depth: int = 3,
    min_confidence: str = enums.LinkConfidence.MEDIUM,
    workspace_id: str | None = None,
) -> list[Reached]:
    """Blast radius: everything reachable from `node_ids` within `max_depth`.

    Traverses assertions in both directions. A change to a field affects the
    process that reads it (forward) and is constrained by the API that exposes
    it (backward); a directional-only walk would miss half of any real impact.

    Returns the *shortest* path to each node, and among equal-length paths the
    strongest. Reporting a node once, by its best evidence, is what keeps the
    result reviewable — the same node appearing five times by five weak paths
    is noise dressed as thoroughness.
    """
    if not node_ids:
        return []

    threshold = _RANK.get(min_confidence, 1)

    # Recursive CTE. Written as raw SQL rather than assembled in the ORM
    # because SQLAlchemy's recursive-CTE surface obscures what is a
    # performance-critical query, and this one benefits from being readable.
    sql = text(
        """
        WITH RECURSIVE reachable(node_id, depth, weakest, via, seq, seq_scope) AS (
            SELECT
                CAST(:seed AS text) AS node_id,
                0 AS depth,
                3 AS weakest,
                ARRAY[]::text[] AS via,
                CAST(NULL AS integer) AS seq,
                CAST(NULL AS varchar) AS seq_scope
            UNION ALL
            SELECT
                nxt.other_id,
                r.depth + 1,
                LEAST(r.weakest, nxt.rank),
                r.via || nxt.assertion_id,
                -- Position of the edge that reached this node, so a step
                -- knows where it sits without a second query. Null for the
                -- majority of relations, which carry no order.
                nxt.seq,
                nxt.seq_scope
            FROM reachable r
            JOIN (
                SELECT
                    a.subject_id AS from_id,
                    a.object_id  AS other_id,
                    a.id         AS assertion_id,
                    a.sequence       AS seq,
                    a.sequence_scope AS seq_scope,
                    CASE a.confidence
                        WHEN 'confirmed' THEN 3 WHEN 'high' THEN 2
                        WHEN 'medium' THEN 1 ELSE 0 END AS rank
                FROM assertions a
                WHERE a.superseded_at IS NULL AND a.status <> 'refuted'
                UNION ALL
                SELECT
                    a.object_id  AS from_id,
                    a.subject_id AS other_id,
                    a.id         AS assertion_id,
                    a.sequence       AS seq,
                    a.sequence_scope AS seq_scope,
                    CASE a.confidence
                        WHEN 'confirmed' THEN 3 WHEN 'high' THEN 2
                        WHEN 'medium' THEN 1 ELSE 0 END AS rank
                FROM assertions a
                WHERE a.superseded_at IS NULL AND a.status <> 'refuted'
            ) nxt ON nxt.from_id = r.node_id
            WHERE r.depth < :max_depth
              AND nxt.rank >= :threshold
              -- Cycle guard. Configuration graphs are full of them, and
              -- without this the CTE never terminates.
              AND NOT (nxt.assertion_id = ANY(r.via))
        )
        -- DISTINCT ON rather than GROUP BY: the paths in `via` have different
        -- lengths, and Postgres cannot ARRAY_AGG arrays of differing
        -- dimensionality. This picks the single best row per node (shortest
        -- path, then strongest) and keeps its actual path intact.
        SELECT DISTINCT ON (node_id) node_id, depth, weakest, via, seq, seq_scope
        FROM reachable
        WHERE depth > 0
        ORDER BY node_id, depth ASC, weakest DESC
        """
    )

    found: dict[str, tuple[int, int, list[str], int | None, str | None]] = {}
    for seed in node_ids:
        rows = db.execute(
            sql, {"seed": seed, "max_depth": max_depth, "threshold": threshold}
        ).all()
        for node_id, depth, weakest, via, seq, seq_scope in rows:
            prior = found.get(node_id)
            # Prefer the shorter path; break ties on the stronger one.
            if prior is None or (depth, -weakest) < (prior[0], -prior[1]):
                found[node_id] = (depth, weakest, list(via or []), seq, seq_scope)

    # Seeds themselves are the change, not its blast radius.
    for seed in node_ids:
        found.pop(seed, None)
    if not found:
        return []

    stmt = select(GraphNode).where(GraphNode.id.in_(list(found)))
    if workspace_id:
        stmt = stmt.where(GraphNode.workspace_id == workspace_id)
    nodes = {n.id: n for n in db.execute(stmt).scalars()}

    rank_to_name = {v: k for k, v in _RANK.items()}
    out = [
        Reached(
            node=nodes[node_id],
            depth=depth,
            path_confidence=rank_to_name.get(weakest, enums.LinkConfidence.LOW),
            via=via,
            sequence=seq,
            sequence_scope=seq_scope,
        )
        for node_id, (depth, weakest, via, seq, seq_scope) in found.items()
        if node_id in nodes
    ]
    # Nearest and strongest first: the order a reviewer should read them in.
    out.sort(key=lambda r: (r.depth, -_RANK.get(r.path_confidence, 0), r.node.label))
    return out


def search(
    db: Session,
    query: str,
    *,
    workspace_id: str | None = None,
    limit: int = 25,
) -> list[GraphNode]:
    """Find nodes by label or description.

    Trigram/vector search is the eventual answer here; `ILIKE` is honest about
    being a first pass. pgvector is installed for when descriptions are
    embedded — the seam is this function and nothing else.
    """
    pattern = f"%{query.strip()}%"
    stmt = select(GraphNode).where(
        GraphNode.label.ilike(pattern) | GraphNode.description.ilike(pattern)
    )
    if workspace_id:
        stmt = stmt.where(GraphNode.workspace_id == workspace_id)
    return list(db.execute(stmt.limit(limit)).scalars())


def assertions_between(
    db: Session, node_ids: list[str], *, include_superseded: bool = False
) -> list[Assertion]:
    """Every assertion whose subject and object are both in `node_ids`."""
    if not node_ids:
        return []
    stmt = select(Assertion).where(
        Assertion.subject_id.in_(node_ids), Assertion.object_id.in_(node_ids)
    )
    if not include_superseded:
        stmt = stmt.where(Assertion.superseded_at.is_(None))
    return list(db.execute(stmt).scalars())


def assertion_history(db: Session, subject_id: str, object_id: str) -> list[Assertion]:
    """Everything the graph has ever believed about one pair of nodes.

    The bi-temporal payoff: not just what is true now, but when each claim was
    recorded, what replaced it, and who confirmed it.
    """
    return list(
        db.execute(
            select(Assertion)
            .where(Assertion.subject_id == subject_id, Assertion.object_id == object_id)
            .order_by(Assertion.recorded_at.desc())
        ).scalars()
    )

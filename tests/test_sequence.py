"""
Ordered relations.

Most graph edges have no order — `GOVERNED_BY` is not third of anything. But an
approval chain does, and position is what a change-impact analysis actually
asks about: "what is the third approval", "what sits above the 15-day
threshold". Deriving `NEXT_STEP` edges by sorting and then discarding the
number leaves those questions unanswerable, which is what these tests guard.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from api.connectors.base import RawRecord, RelationOrder
from api.core.ids import new_id
from api.domain import enums
from api.domain.models import Assertion, ExtractionRun, GraphNode, KnowledgeSource
from api.graph.normalize import VALID_PREDICATES, Normalizer
from api.graph.queries import ordered_chain


@pytest.fixture
def run(db) -> ExtractionRun:
    r = ExtractionRun(
        id=new_id("xr"), connector_id="cx-test", extractor_version="1", workspace_id="ws-seq"
    )
    db.add(r)
    db.flush()
    return r


@pytest.fixture
def source(db) -> KnowledgeSource:
    s = KnowledgeSource(
        id=new_id("src"),
        workspace_id="ws-seq",
        name="Test source",
        kind=enums.SourceKind.PLATFORM,
        provider="Test",
    )
    db.add(s)
    db.flush()
    return s


def _process_records() -> list[RawRecord]:
    """A three-step approval chain with a conditional third step.

    Modelled on the transcript's Change Job example: manager approves, then
    compensation approval only when the change exceeds a threshold.
    """
    scope = "workday:bp:change_job"
    definition = RawRecord(
        kind="business_process",
        natural_key=scope,
        label="Change Job",
        payload={},
        provenance="Workday › BP › Change Job",
    )

    steps = []
    for position, (key, label, condition) in enumerate(
        [
            ("initiate", "Initiation (HR Partner)", None),
            ("manager", "Approval (Manager)", None),
            ("comp", "Approval (Compensation Partner)", "salary_change > 10%"),
        ],
        start=1,
    ):
        record = RawRecord(
            kind="config_object",
            natural_key=f"workday:bpstep:{key}",
            label=label,
            payload={"conditionRule": condition},
            provenance=f"Workday › Step › {key}",
            relations=[("HAS_STEP", scope)],
        )
        record.ordering[("HAS_STEP", scope)] = RelationOrder(
            sequence=position,
            scope=scope,
            condition={"rule": condition} if condition else None,
        )
        steps.append(record)

    return [definition, *steps]


def _ingest(db, run, source, records) -> None:
    Normalizer(db, run, source_id=source.id, workspace_id="ws-seq").ingest(records)
    db.flush()


# --- the predicate ---------------------------------------------------------


def test_conditional_next_step_is_a_distinct_predicate():
    """"Always goes here" and "goes here only above 10%" are different claims.

    Collapsing them into one predicate asserts that a gated approval always
    runs, which is exactly what a conditional approval does not do.
    """
    assert "CONDITIONAL_NEXT_STEP" in VALID_PREDICATES
    assert "NEXT_STEP" in VALID_PREDICATES


# --- ordering survives ingestion ------------------------------------------


def test_sequence_is_stored_not_discarded(db, run, source):
    _ingest(db, run, source, _process_records())

    rows = (
        db.query(Assertion)
        .filter(Assertion.predicate == "HAS_STEP", Assertion.sequence.is_not(None))
        .order_by(Assertion.sequence)
        .all()
    )
    assert [r.sequence for r in rows] == [1, 2, 3]
    assert {r.sequence_scope for r in rows} == {"workday:bp:change_job"}


def test_condition_is_kept_on_the_gated_step_only(db, run, source):
    _ingest(db, run, source, _process_records())

    rows = (
        db.query(Assertion)
        .filter(Assertion.predicate == "HAS_STEP")
        .order_by(Assertion.sequence)
        .all()
    )
    assert rows[0].condition is None
    assert rows[1].condition is None
    assert rows[2].condition == {"rule": "salary_change > 10%"}


def test_ordered_chain_reads_the_process_in_order(db, run, source):
    """The question adjacency alone cannot answer: which step is third."""
    _ingest(db, run, source, _process_records())

    chain = ordered_chain(db, "workday:bp:change_job", workspace_id="ws-seq")

    assert [s.sequence for s in chain] == [1, 2, 3]
    assert "Compensation Partner" in chain[2].node.label
    assert chain[2].condition == {"rule": "salary_change > 10%"}


def test_ordered_chain_is_scoped(db, run, source):
    """Two processes each having a step 3 is not a conflict."""
    _ingest(db, run, source, _process_records())
    assert ordered_chain(db, "workday:bp:other_process", workspace_id="ws-seq") == []


# --- re-extraction ---------------------------------------------------------


def test_reingesting_unchanged_order_does_not_duplicate(db, run, source):
    records = _process_records()
    _ingest(db, run, source, records)
    before = db.query(Assertion).filter(Assertion.predicate == "HAS_STEP").count()

    _ingest(db, run, source, _process_records())
    after = db.query(Assertion).filter(Assertion.predicate == "HAS_STEP").count()

    assert before == after == 3


def test_a_step_that_moves_supersedes_rather_than_silently_keeping_its_place(
    db, run, source
):
    """Position is part of the claim.

    Treating a moved step as "already known" would leave the graph asserting an
    ordering the source system no longer has — the exact silent-staleness the
    supersession chain exists to prevent.
    """
    _ingest(db, run, source, _process_records())

    # The compensation approval moves from third to second.
    moved = _process_records()
    scope = "workday:bp:change_job"
    for record in moved:
        if record.natural_key == "workday:bpstep:comp":
            record.ordering[("HAS_STEP", scope)] = RelationOrder(
                sequence=2, scope=scope, condition={"rule": "salary_change > 10%"}
            )
        elif record.natural_key == "workday:bpstep:manager":
            record.ordering[("HAS_STEP", scope)] = RelationOrder(sequence=3, scope=scope)
    _ingest(db, run, source, moved)

    chain = ordered_chain(db, scope, workspace_id="ws-seq")
    assert [s.sequence for s in chain] == [1, 2, 3]
    assert "Compensation Partner" in chain[1].node.label
    assert "Manager" in chain[2].node.label

    # The old positions are retained as history, not deleted.
    superseded = (
        db.query(Assertion)
        .filter(
            Assertion.predicate == "HAS_STEP",
            Assertion.superseded_at.is_not(None),
        )
        .count()
    )
    assert superseded == 2


# --- the database guarantee ------------------------------------------------


def test_two_live_steps_cannot_claim_the_same_position(db, run, source):
    """The transcript's `step_order_unique`, enforced by Postgres.

    A checker in application code can be bypassed by any other write path; a
    partial unique index cannot.
    """
    _ingest(db, run, source, _process_records())

    subject = db.query(GraphNode).filter(GraphNode.label.like("%Manager%")).one()
    obj = db.query(GraphNode).filter(GraphNode.label == "Change Job").one()

    db.add(
        Assertion(
            id=new_id("as"),
            workspace_id="ws-seq",
            subject_id=subject.id,
            predicate="HAS_STEP",
            object_id=obj.id,
            sequence=1,  # already taken by the initiation step
            sequence_scope="workday:bp:change_job",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_superseded_rows_may_reuse_a_position(db, run, source):
    """Otherwise correcting a step's order would be impossible: the old row
    holds the position forever."""
    _ingest(db, run, source, _process_records())

    subject = db.query(GraphNode).filter(GraphNode.label.like("%Manager%")).one()
    obj = db.query(GraphNode).filter(GraphNode.label == "Change Job").one()

    from api.core.ids import utcnow

    db.add(
        Assertion(
            id=new_id("as"),
            workspace_id="ws-seq",
            subject_id=subject.id,
            predicate="HAS_STEP",
            object_id=obj.id,
            sequence=1,
            sequence_scope="workday:bp:change_job",
            superseded_at=utcnow(),
            status=enums.AssertionStatus.SUPERSEDED,
        )
    )
    db.flush()  # must not raise


def test_workday_gates_the_edge_entering_the_conditional_step():
    """The condition belongs to the step being *entered*.

    "Compensation Partner approves when the change exceeds 10%" gates arrival
    at that step; the preceding manager approval runs unconditionally. Putting
    the rule on the outgoing edge would assert the opposite — that leaving the
    compensation step is conditional — which is a different process.
    """
    from api.connectors.workday.connector import WorkdayConnector

    connector = WorkdayConnector(
        {
            "host": "https://x",
            "tenant": "t",
            "method": "isu_basic",
            "username": "u",
            "password": "p",
        }
    )
    rows = [
        {"Definition_ID": "CJ", "Step_Order": "1", "Step_Name": "Manager"},
        {
            "Definition_ID": "CJ",
            "Step_Order": "2",
            "Step_Name": "Compensation",
            "Condition_Rule": "salary_change > 10%",
        },
    ]

    hops = {
        predicate: record.ordering[(predicate, target)]
        for record in connector._rows_bp_steps(rows)
        for predicate, target in record.relations
        if "NEXT" in predicate
    }

    assert "CONDITIONAL_NEXT_STEP" in hops
    assert hops["CONDITIONAL_NEXT_STEP"].condition == {"rule": "salary_change > 10%"}
    assert "NEXT_STEP" not in hops


def test_workday_step_order_tolerates_suffixed_positions():
    """Workday step order can be "2a". Position must stay dense and integral
    regardless, because it is what the uniqueness index keys on."""
    from api.connectors.workday.connector import WorkdayConnector

    connector = WorkdayConnector(
        {
            "host": "https://x",
            "tenant": "t",
            "method": "isu_basic",
            "username": "u",
            "password": "p",
        }
    )
    rows = [
        {"Definition_ID": "CJ", "Step_Order": order, "Step_Name": f"Step {order}"}
        for order in ("1", "2", "2a", "3")
    ]

    positions = [
        order.sequence
        for record in connector._rows_bp_steps(rows)
        for (predicate, _), order in record.ordering.items()
        if predicate == "HAS_STEP"
    ]
    assert sorted(positions) == [1, 2, 3, 4]


def test_unordered_relations_are_unaffected(db, run, source):
    """Most edges have no order and must not be forced to invent one."""
    record = RawRecord(
        kind="config_object",
        natural_key="workday:bpstep:solo",
        label="A step",
        payload={},
        provenance="test",
        relations=[("GOVERNED_BY", "workday:bp:change_job")],
    )
    _ingest(db, run, source, [*_process_records(), record])

    governed = (
        db.query(Assertion).filter(Assertion.predicate == "GOVERNED_BY").one()
    )
    assert governed.sequence is None
    assert governed.sequence_scope is None

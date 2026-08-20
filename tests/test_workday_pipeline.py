"""
The Workday pipeline, end to end.

Everything else tests a surface in isolation. This tests the join: connector
output → normaliser → Postgres → the queries the product actually runs. That
join is where the interesting failures live, because each half can be correct
while the contract between them is not — a predicate the ontology rejects, an
ordering scope that collides, a record whose relation target no connector ever
emits.

No live tenant. The connector's HTTP surfaces are replaced with recorded rows,
which is the same discipline `test_workday.py` uses; what is exercised here is
everything downstream of the bytes arriving.

The payoff test is `test_configured_and_observed_chains_can_be_compared`: the
transcript's headline use case, where a process configured as Manager → HR
Partner is observed running an undocumented payroll correction, and the graph
can be asked about both.
"""

from __future__ import annotations

import pytest

from api.connectors.base import RawRecord
from api.connectors.workday.events import mark_undocumented, parse_instances
from api.core.ids import new_id
from api.domain import enums
from api.domain.models import Assertion, ExtractionRun, GraphNode, KnowledgeSource
from api.graph.normalize import Normalizer
from api.graph.queries import neighbours, ordered_chain

WORKSPACE = "ws-wd-pipeline"


@pytest.fixture
def run(db) -> ExtractionRun:
    r = ExtractionRun(
        id=new_id("xr"),
        connector_id="cx-workday",
        extractor_version="1",
        workspace_id=WORKSPACE,
    )
    db.add(r)
    db.flush()
    return r


@pytest.fixture
def source(db) -> KnowledgeSource:
    s = KnowledgeSource(
        id=new_id("src"),
        workspace_id=WORKSPACE,
        name="Workday",
        kind=enums.SourceKind.PLATFORM,
        provider="Workday, Inc.",
    )
    db.add(s)
    db.flush()
    return s


def _ingest(db, run, source, records: list[RawRecord]):
    normalizer = Normalizer(db, run, source_id=source.id, workspace_id=WORKSPACE)
    result = normalizer.ingest(records)
    db.flush()
    return result


# --- the configured side ----------------------------------------------------


CONFIGURED_STEPS = [
    {
        "Definition_ID": "CJ",
        "Step_Order": "1",
        "Step_Name": "Initiation",
        "Step_Type": "Action",
    },
    {
        "Definition_ID": "CJ",
        "Step_Order": "2",
        "Step_Name": "Approval (Manager)",
        "Step_Type": "Approval",
        "Group": "Manager",
    },
    {
        "Definition_ID": "CJ",
        "Step_Order": "3",
        "Step_Name": "Approval (HR Partner)",
        "Step_Type": "Approval",
        "Group": "HR Partner",
        "Condition_Rule": "salary_change > 10%",
    },
]

CONFIGURED_DEFINITION = [
    {
        "Definition_ID": "CJ",
        "Business_Process_Definition": "Change Job",
        "Business_Process_Type": "Change Job",
    }
]

# The same process as it actually ran: the HR Partner approval never happened,
# and a payroll correction that appears in no definition did.
OBSERVED_ROWS = [
    {
        "Business_Process_Instance_ID": "BP-77",
        "Business_Process_Type": "Change Job",
        "Definition_ID": "CJ",
        "Step_Order": "1",
        "Step_Name": "Initiation",
        "Completed_By": "Priya Nair",
        "Overall_Status": "Completed",
    },
    {
        "Business_Process_Instance_ID": "BP-77",
        "Business_Process_Type": "Change Job",
        "Definition_ID": "CJ",
        "Step_Order": "2",
        "Step_Name": "Approval (Manager)",
        "Completed_By": "Wei Chen",
        "Overall_Status": "Completed",
    },
    {
        "Business_Process_Instance_ID": "BP-77",
        "Business_Process_Type": "Change Job",
        "Definition_ID": "CJ",
        "Step_Order": "3",
        "Step_Name": "Manual Payroll Correction",
        "Completed_By": "Wei Chen",
        "Overall_Status": "Completed",
    },
]


@pytest.fixture
def connector():
    from api.connectors.workday.connector import WorkdayConnector

    return WorkdayConnector(
        {
            "host": "https://wd2-impl-services1.workday.com",
            "tenant": "acme_preview",
            "method": "isu_basic",
            "username": "isu",
            "password": "pw",
        }
    )


#: The steps above route to these groups. Included because the normaliser
#: rejects a relation whose target no record in the batch defines — a real run
#: extracts all of them together, so a fixture that omits them tests a
#: situation the product never produces.
SECURITY_GROUPS = [
    {"Security_Group": "Manager"},
    {"Security_Group": "HR Partner"},
]

#: The gated step is GOVERNED_BY this rule, so it must be in the batch too.
CONDITION_RULES = [
    {
        "Condition_Rule": "salary_change > 10%",
        "Return_Type": "Boolean",
        "Description": "Comp change above the approval threshold.",
    }
]


def _configured_records(connector) -> list[RawRecord]:
    return [
        *connector._rows_bp_definitions(CONFIGURED_DEFINITION),
        *connector._rows_bp_steps(CONFIGURED_STEPS),
        *connector._rows_security_groups(SECURITY_GROUPS),
        *connector._rows_condition_rules(CONDITION_RULES),
    ]


#: Step labels as the connector builds them — it appends the step type, which
#: is what distinguishes an Approval from an Action of the same name.
CONFIGURED_LABELS = [
    "Initiation (Action)",
    "Approval (Manager) (Approval)",
    "Approval (HR Partner) (Approval)",
]


def _observed_records(connector) -> list[RawRecord]:
    instances = parse_instances(OBSERVED_ROWS)
    mark_undocumented(
        instances,
        {"workday:bp:CJ": {"initiation", "approval (manager)", "approval (hr partner)"}},
    )
    out: list[RawRecord] = []
    for instance in instances:
        out.extend(connector._records_for_run(instance))
    return out


# --- the tests --------------------------------------------------------------


def test_connector_output_passes_the_ontology(db, run, source, connector):
    """Every record a connector emits must survive validation.

    A rejected record is silent data loss: the run reports success and the
    graph is simply missing something.
    """
    result = _ingest(db, run, source, _configured_records(connector))
    assert result.rejected == []
    assert result.nodes_created > 0


def test_runtime_records_also_pass_the_ontology(db, run, source, connector):
    # The configured side first: a run IMPLEMENTS its definition, and the
    # normaliser resolves targets within the source, so ingesting runs alone
    # would leave that edge dangling. A real extraction always has both.
    _ingest(db, run, source, _configured_records(connector))
    result = _ingest(db, run, source, _observed_records(connector))
    assert result.rejected == []


def test_configured_chain_reads_in_order_after_a_full_ingest(
    db, run, source, connector
):
    _ingest(db, run, source, _configured_records(connector))

    chain = ordered_chain(db, "workday:bp:CJ", workspace_id=WORKSPACE)
    assert [s.sequence for s in chain] == [1, 2, 3]
    assert [s.node.label for s in chain] == CONFIGURED_LABELS


def test_the_gated_step_carries_its_condition_through_the_pipeline(
    db, run, source, connector
):
    """The condition survives connector → normaliser → Postgres → query.

    Losing it anywhere turns a conditional approval into one that always runs,
    which is a different process.
    """
    _ingest(db, run, source, _configured_records(connector))

    # The condition sits on the hop *entering* the gated step, not on the
    # step's membership of the process. "The HR Partner approves when comp
    # changes by more than 10%" gates arrival at that step; the step still
    # belongs to the definition unconditionally.
    gated = (
        db.query(Assertion)
        .filter(
            Assertion.workspace_id == WORKSPACE,
            Assertion.predicate == "CONDITIONAL_NEXT_STEP",
            Assertion.superseded_at.is_(None),
        )
        .one()
    )
    assert gated.condition == {"rule": "salary_change > 10%"}

    # And the membership edges carry no condition at all.
    chain = ordered_chain(db, "workday:bp:CJ", workspace_id=WORKSPACE)
    assert [s.condition for s in chain] == [None, None, None]


def test_configured_and_observed_chains_can_be_compared(db, run, source, connector):
    """The transcript's headline finding, asked of the real graph.

    Configured: Initiation → Manager → HR Partner.
    Observed:   Initiation → Manager → Manual Payroll Correction.

    Both chains must be readable *separately* — that is what the distinct
    HAS_STEP / HAS_OBSERVED_STEP predicates buy — and the drift has to be
    visible without re-deriving it from the source reports.
    """
    _ingest(db, run, source, _configured_records(connector))
    _ingest(db, run, source, _observed_records(connector))

    configured = ordered_chain(db, "workday:bp:CJ", workspace_id=WORKSPACE)
    observed = ordered_chain(
        db,
        "workday:bpinstance:BP-77",
        predicate="HAS_OBSERVED_STEP",
        workspace_id=WORKSPACE,
    )

    assert [s.node.label for s in configured] == CONFIGURED_LABELS
    assert [s.node.label for s in observed] == [
        "Initiation",
        "Approval (Manager)",
        "Manual Payroll Correction",
    ]

    # The drift is recorded on the node, not recomputed by the reader.
    drifted = (
        db.query(GraphNode)
        .filter(
            GraphNode.workspace_id == WORKSPACE,
            GraphNode.label == "Manual Payroll Correction",
        )
        .one()
    )
    assert drifted.attributes["undocumented"] is True


def test_two_runs_of_one_process_do_not_collide_on_position(
    db, run, source, connector
):
    """Both runs have a step 2, and the partial unique index must permit it.

    Scoping observed order to the definition rather than the instance would
    make the second run of any process fail to ingest — which would look like a
    Meridian bug and be discovered only in production.
    """
    _ingest(db, run, source, _configured_records(connector))
    _ingest(db, run, source, _observed_records(connector))

    second = [dict(row, Business_Process_Instance_ID="BP-78") for row in OBSERVED_ROWS]
    instances = parse_instances(second)
    records: list[RawRecord] = []
    for instance in instances:
        records.extend(connector._records_for_run(instance))
    result = _ingest(db, run, source, records)

    assert result.rejected == []
    first = ordered_chain(
        db, "workday:bpinstance:BP-77", predicate="HAS_OBSERVED_STEP",
        workspace_id=WORKSPACE,
    )
    other = ordered_chain(
        db, "workday:bpinstance:BP-78", predicate="HAS_OBSERVED_STEP",
        workspace_id=WORKSPACE,
    )
    assert [s.sequence for s in first] == [1, 2, 3]
    assert [s.sequence for s in other] == [1, 2, 3]


def test_the_run_links_back_to_the_definition_it_implements(
    db, run, source, connector
):
    """Without this edge the two chains are unrelated islands and no impact
    analysis can travel from a configuration change to the runs it affects."""
    _ingest(db, run, source, _configured_records(connector))
    _ingest(db, run, source, _observed_records(connector))

    definition = (
        db.query(GraphNode)
        .filter(
            GraphNode.workspace_id == WORKSPACE,
            GraphNode.natural_key == "workday:bp:CJ",
        )
        .one()
    )
    reached = {
        r.node.natural_key
        for r in neighbours(
            db,
            [definition.id],
            max_depth=2,
            min_confidence=enums.LinkConfidence.LOW,
            workspace_id=WORKSPACE,
        )
    }
    assert "workday:bpinstance:BP-77" in reached


def test_re_extraction_is_idempotent(db, run, source, connector):
    """A second identical run must not double the graph.

    Extraction runs on a schedule, so a non-idempotent pipeline grows without
    bound and every count in the product becomes meaningless.
    """
    _ingest(db, run, source, _configured_records(connector))
    before = (
        db.query(Assertion)
        .filter(
            Assertion.workspace_id == WORKSPACE,
            Assertion.superseded_at.is_(None),
        )
        .count()
    )

    _ingest(db, run, source, _configured_records(connector))
    after = (
        db.query(Assertion)
        .filter(
            Assertion.workspace_id == WORKSPACE,
            Assertion.superseded_at.is_(None),
        )
        .count()
    )
    assert before == after


def test_capability_records_are_kept_distinct_from_configuration(
    db, run, source, connector
):
    """"The platform exposes Worker" and "this tenant configured Worker" are
    different claims, and the layer is what keeps them apart."""
    from api.connectors.workday.rest import parse_schemas

    spec = {
        "components": {
            "schemas": {"Worker": {"properties": {"id": {"type": "string"}}}}
        }
    }
    records = [
        RawRecord(
            kind="data_entity",
            natural_key=schema.natural_key,
            label=schema.name,
            payload={"properties": schema.properties},
            provenance="Workday › REST › staffing",
            layer="capability",
        )
        for schema in parse_schemas("staffing", spec)
    ]
    result = _ingest(db, run, source, records)

    assert result.rejected == []
    node = (
        db.query(GraphNode)
        .filter(
            GraphNode.workspace_id == WORKSPACE,
            GraphNode.natural_key == "workday:apischema:staffing:Worker",
        )
        .one()
    )
    assert node.label == "Worker"

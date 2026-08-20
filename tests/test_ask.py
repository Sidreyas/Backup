"""
Asking the graph questions.

This is the surface a client actually touches, and the one where being wrong is
most expensive: a fluent, confident, fabricated answer about someone's leave
policy is worse than no product. So most of what is tested here is not "does it
answer" but "does it refuse to answer from anything except extracted data".

The fixtures are the real Workday absence graph — plans, accruals, calculated
fields and a lookup table with the actual Hong Kong service bands — because a
retrieval test against synthetic nodes proves retrieval works on synthetic
nodes.

Tests run with no API key, so `llm()` returns its stub. That is deliberate for
the grounding tests: the stub cannot hallucinate, which isolates whether the
*retrieval and citation* machinery is correct. The fabrication guard is tested
by feeding a forged model response directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.agents import ask as ask_agent
from api.connectors.base import RawRecord
from api.connectors.workday.absence_screen import (
    attach_accrual_detail,
    attach_calculations,
    parse_plan_screen,
)
from api.connectors.workday.connector import WorkdayConnector
from api.core.ids import new_id
from api.domain import enums
from api.domain.models import ExtractionRun, GraphNode, KnowledgeSource
from api.graph.normalize import Normalizer

FIXTURES = Path(__file__).parent / "fixtures"
WORKSPACE = "ws-ask"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def graph(db):
    """The real absence graph, ingested."""
    run = ExtractionRun(
        id=new_id("xr"),
        connector_id="cx-workday",
        extractor_version="1",
        workspace_id=WORKSPACE,
    )
    source = KnowledgeSource(
        id=new_id("src"),
        workspace_id=WORKSPACE,
        name="Workday",
        kind=enums.SourceKind.PLATFORM,
        provider="Workday, Inc.",
    )
    db.add_all([run, source])
    db.flush()

    connector = WorkdayConnector(
        {
            "host": "https://x",
            "tenant": "t",
            "method": "isu_basic",
            "username": "u",
            "password": "p",
        }
    )
    accruals = _load("workday_accruals.json")
    lookups = _load("workday_lookups.json")

    records: list[RawRecord] = []
    for key, plan_id, name in (
        ("hkg_annual_leave", "HKG", "HKG Annual Leave"),
        ("gbr_statutory_holiday", "GBR", "GBR Statutory Holiday (Days)"),
    ):
        plan = parse_plan_screen(
            _load(f"workday_timeoffplan_{key}.json"),
            plan_id=plan_id,
            name=name,
            unit_of_time="Days",
        )
        plan = attach_accrual_detail(plan, accruals[key])
        plan = attach_calculations(plan, lookups[key])
        records.extend(connector._records_for_plan(plan))

    result = Normalizer(
        db, run, source_id=source.id, workspace_id=WORKSPACE
    ).ingest(records)
    db.flush()
    assert result.rejected == [], result.rejected
    return db


# --- term extraction ---------------------------------------------------------


def test_noise_words_are_dropped_but_domain_words_survive():
    got = ask_agent.terms("How much annual leave do Hong Kong staff get?")
    lowered = [t.lower() for t in got]
    assert "annual" in lowered
    assert "leave" in lowered
    assert "kong" in lowered
    assert "much" not in lowered
    assert "how" not in lowered


def test_quoted_phrases_are_kept_whole():
    """"GBR Statutory Holiday" is one thing, not three common words."""
    got = ask_agent.terms('what is "GBR Statutory Holiday" capped at')
    assert "GBR Statutory Holiday" in got


# --- retrieval ---------------------------------------------------------------


def test_a_plan_question_retrieves_the_plan(graph):
    nodes = ask_agent.retrieve(graph, "HKG Annual Leave", workspace_id=WORKSPACE)
    labels = [n.label for n in nodes]
    assert "HKG Annual Leave" in labels


def test_retrieval_expands_to_the_chain_that_answers_the_question(graph):
    """A question about a plan is usually a question about its accruals.

    Stopping at the plan node would be grounded and useless — the entitlement
    lives two hops away on the lookup table.
    """
    nodes = ask_agent.retrieve(graph, "HKG Annual Leave", workspace_id=WORKSPACE)
    keys = {n.natural_key for n in nodes}
    assert any(k and "accrual" in k for k in keys)
    assert any(k and k.startswith("workday:lookup:") for k in keys)


def test_the_node_the_question_names_outranks_ones_sharing_a_word(graph):
    """Ranking is by how many of the question's terms a node matched.

    Without it, "what breaks if I change the HKG Annual Leave Days Entitlement
    calculation" retrieved every node containing "leave" — the whole GBR plan
    included — with the same standing as the one node the question names. The
    model then cited them, correctly by its own rules, and answered about
    things nobody asked about. A grounded answer can still be a misleading one.
    """
    nodes = ask_agent.retrieve(
        graph,
        "what breaks if I change the HKG Annual Leave Days Entitlement calculation",
        workspace_id=WORKSPACE,
    )
    top = [n.label for n in nodes[:3]]
    assert "HKG Annual Leave Days Entitlement" in top
    assert not any("GBR" in label for label in top)


def test_retrieval_is_bounded(graph):
    nodes = ask_agent.retrieve(
        graph, "leave holiday plan accrual", workspace_id=WORKSPACE, limit=3
    )
    assert len(nodes) <= 3


def test_an_unrelated_question_retrieves_nothing(graph):
    assert ask_agent.retrieve(graph, "zxqv nonexistent", workspace_id=WORKSPACE) == []


# --- the grounding guarantee -------------------------------------------------


def test_a_question_the_graph_cannot_answer_is_refused(graph):
    """The most important test here.

    With no retrieval, the model is never called at all. Letting it answer
    from training data would produce a confident description of Workday in
    general, presented as this customer's configuration.
    """
    answer = ask_agent.ask(
        graph, "what is our SAP payroll retention policy", workspace_id=WORKSPACE
    )
    assert answer.grounded is False
    assert answer.cited == []
    assert "has not been" in answer.text or "Nothing in the extracted" in answer.text


def test_an_empty_question_does_not_reach_retrieval(graph):
    answer = ask_agent.ask(graph, "   ", workspace_id=WORKSPACE)
    assert answer.cited == []


def test_an_answer_cites_the_nodes_it_used(graph):
    answer = ask_agent.ask(
        graph, "HKG Annual Leave entitlement", workspace_id=WORKSPACE
    )
    assert answer.grounded is True
    assert all(node.id for node in answer.cited)


def test_fabricated_citations_are_dropped_and_reported(graph, monkeypatch):
    """A model citing a node that was not in its input is an AI incident.

    Showing it would put an id in front of a user that resolves to nothing;
    silently dropping it would hide the event. Both are wrong.
    """
    from api.agents.llm import LlmResult

    def forged(**kwargs):
        return LlmResult(
            text=json.dumps(
                {
                    "answer": "Staff get 30 days.",
                    "cited": ["n-does-not-exist", "n-also-fake"],
                    "confident": True,
                }
            ),
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            model="test",
            model_version="test",
            prompt_hash="x",
            source="stub",
        )

    monkeypatch.setattr(
        ask_agent, "llm", type("C", (), {"complete": staticmethod(forged)})()
    )
    answer = ask_agent.ask(graph, "HKG Annual Leave", workspace_id=WORKSPACE)

    assert set(answer.fabricated) == {"n-does-not-exist", "n-also-fake"}
    assert all(node.id not in answer.fabricated for node in answer.cited)


# --- honesty about what is missing -------------------------------------------


def test_unresolved_references_are_reported_as_gaps(graph):
    """GBR's mid-year branches point at calculations nobody has read.

    The graph records them as unresolved stubs; the answer must surface that
    rather than let a partial extraction read as complete.
    """
    answer = ask_agent.ask(
        graph, "GBR Statutory Holiday accrual", workspace_id=WORKSPACE
    )
    assert any("has not been extracted" in gap for gap in answer.gaps)


def test_the_lookup_bands_reach_the_answer_context(graph):
    """The actual numbers must be in what the model sees.

    A context of labels alone would let it name the right lookup table and
    invent the bands inside it.
    """
    node = (
        graph.query(GraphNode)
        .filter(
            GraphNode.workspace_id == WORKSPACE,
            GraphNode.natural_key == "workday:lookup:annual-leave-accrual-hong-kong",
        )
        .one()
    )
    context = ask_agent._node_context(node)
    bands = context["attributes"]["bands"]
    assert len(bands) == 8
    assert bands[0] == {"search": "1", "result": "7"}
    assert bands[-1] == {"search": "9", "result": "14"}
    assert "Years of Service" in context["attributes"]["keyedOn"]


def test_the_stub_answer_states_facts_rather_than_guessing(graph):
    """With no model configured the answer must still be true.

    A stub that improvised prose would be the same failure this module exists
    to prevent, with no model involved.
    """
    nodes = ask_agent.retrieve(
        graph, "Annual Leave Accrual Hong Kong", workspace_id=WORKSPACE
    )
    text = ask_agent._stub_answer("q", nodes)
    assert "7" in text and "14" in text


# --- the graph shape the answers depend on ----------------------------------


def test_the_calculation_is_a_node_not_a_string(graph):
    """"What breaks if I change this calculation" needs it to be a node."""
    node = (
        graph.query(GraphNode)
        .filter(
            GraphNode.workspace_id == WORKSPACE,
            GraphNode.natural_key
            == "workday:field:hkg-annual-leave-days-entitlement",
        )
        .one()
    )
    assert node.kind == "data_entity"
    assert node.attributes["resolved"] is True


def test_the_dependency_chain_is_traversable(graph):
    """accrual → calculation → lookup table, as edges."""
    from api.domain import enums as domain_enums
    from api.graph.queries import neighbours

    accrual = (
        graph.query(GraphNode)
        .filter(
            GraphNode.workspace_id == WORKSPACE,
            GraphNode.natural_key.like("%accrual:hkg-annual-leave-accrual"),
        )
        .one()
    )
    reached = {
        r.node.natural_key
        for r in neighbours(
            graph,
            [accrual.id],
            max_depth=2,
            min_confidence=domain_enums.LinkConfidence.LOW,
            workspace_id=WORKSPACE,
        )
    }
    assert "workday:field:hkg-annual-leave-days-entitlement" in reached
    assert "workday:lookup:annual-leave-accrual-hong-kong" in reached

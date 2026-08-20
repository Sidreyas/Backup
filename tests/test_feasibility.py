"""
Feasibility.

The property under test throughout is that the verdict is *computed*. A model
cannot talk its way to feasible, and neither can a caller: there is no override
parameter, so the tests that matter here are the ones that try to get past the
gate and fail.

The graph is built by hand rather than ingested. Feasibility turns on where a
node came from, how stale that source is, and what scopes the owning connection
holds — three things a fixture should set precisely rather than inherit from a
realistic extraction.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api.agents import feasibility as feasibility_agent
from api.agents.llm import LlmResult
from api.connectors import registry
from api.connectors.base import ConnectorOperation
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.feasibility import FeasibilityAssessment
from api.domain.models import Connection, GraphNode, KnowledgeSource, Requirement
from api.main import app
from api.services import gate

WORKSPACE = "ws-feas"


# ------------------------------------------------------------------ helpers


def _model(monkeypatch, payload: dict) -> None:
    """Replace the agent's model with one that returns `payload`."""

    def complete(*, system, prompt, max_tokens=4096, grounded_node_ids=None, stub=None):
        return LlmResult(
            text=json.dumps(payload),
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
            model="test",
            model_version="1",
            prompt_hash="h",
            source="llm",
            grounded_node_ids=list(grounded_node_ids or []),
        )

    monkeypatch.setattr(
        feasibility_agent,
        "llm",
        type("C", (), {"complete": staticmethod(complete)})(),
    )


def _writable(monkeypatch, *, scopes: list[str], intents=("modify",), kinds=("config_object",)):
    """Make every connector claim it can write, with `scopes` required.

    Nothing in the real product does this yet — that is the point of the
    read-only tests. This exists so the feasible path can be exercised at all,
    and it goes through `ConnectorOperation` rather than around it.
    """

    class Writable:
        operations = [
            ConnectorOperation(
                id="op-write",
                label="Change configuration",
                intents=list(intents),
                node_kinds=list(kinds),
                requires_scopes=list(scopes),
            )
        ]

    monkeypatch.setattr(registry, "build", lambda cid, cfg=None: Writable())


@pytest.fixture
def world(db):
    """A requirement, one fresh source, one connection that owns it, two nodes."""
    source = KnowledgeSource(
        id=new_id("src"),
        workspace_id=WORKSPACE,
        name="Workday",
        kind=enums.SourceKind.PLATFORM,
        provider="Workday, Inc.",
        last_synced_at=utcnow(),
        staleness_threshold_days=7,
    )
    db.add(source)
    db.flush()

    connection = Connection(
        id=new_id("cn"),
        connector_id="cx-workday",
        label="Implementation Tenant",
        workspace_id=WORKSPACE,
        source_id=source.id,
        granted_scopes=["read.absence"],
    )
    plan = GraphNode(
        id=new_id("n"),
        workspace_id=WORKSPACE,
        label="HKG Annual Leave",
        kind="config_object",
        source_id=source.id,
        natural_key="plan:HKG",
        description="Hong Kong annual leave plan.",
        attributes={"accrualSchedule": "Annual - 1st Period of Calendar Year"},
    )
    accrual = GraphNode(
        id=new_id("n"),
        workspace_id=WORKSPACE,
        label="HKG Annual Leave Accrual",
        kind="config_object",
        source_id=source.id,
        natural_key="accrual:HKG",
        description="Seven days rising to fourteen by years of service.",
        attributes={"lookupTable": "HKG Annual Leave Days Entitlement"},
    )
    requirement = Requirement(
        id=new_id("req"),
        workspace_id=WORKSPACE,
        ref="MER-9001",
        title="Change the timing in Hong Kong leave",
        summary="",
        stage=enums.RequirementStage.DISCUSSING,
    )
    db.add_all([connection, plan, accrual, requirement])
    db.flush()
    return {
        "db": db,
        "source": source,
        "connection": connection,
        "plan": plan,
        "accrual": accrual,
        "requirement": requirement,
    }


def _payload(world, **over):
    base = {
        "intent": "modify",
        "understoodAs": "Change the accrual schedule on the Hong Kong annual leave plan.",
        "targetNodeIds": [world["plan"].id],
        "questions": [],
        "budgetRequest": {"count": 0, "why": ""},
    }
    base.update(over)
    return base


# --------------------------------------------------------- verdict is computed


def test_the_model_cannot_declare_a_change_feasible(world, monkeypatch):
    """A model returning a clean, confident answer does not produce FEASIBLE.

    This is the whole design in one test. The connector declares no write
    operations, so the change cannot be made, and no amount of model confidence
    changes that. If this ever passes as feasible, the gate has become
    decorative.
    """
    _model(
        monkeypatch,
        _payload(
            world,
            # Fields the contract does not define, included on purpose: a model
            # volunteering a verdict must not be read as one.
            verdict="feasible",
            feasible=True,
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED
    assert not assessment.is_feasible
    assert [g.kind for g in assessment.blocking_gaps] == [enums.GapKind.ACCESS]


def test_a_read_only_connector_blocks_with_the_reason_stated(world, monkeypatch):
    """The refusal names the system and says Meridian reads it."""
    _model(monkeypatch, _payload(world))

    assessment = feasibility_agent.assess(world["db"], world["requirement"])
    gap = assessment.blocking_gaps[0]

    assert "Implementation Tenant" in gap.summary
    assert "cannot change it" in gap.summary
    assert gap.remedy, "a gap without a remedy is a complaint"
    assert gap.risk, "a blocking gap must say what the risk of ignoring it is"
    assert gap.subject == world["connection"].id


def test_a_missing_scope_is_named_rather_than_summarised(world, monkeypatch):
    """The remedy has to be actionable, which means naming the scope."""
    _model(monkeypatch, _payload(world))
    _writable(monkeypatch, scopes=["write.absence"])

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED
    gap = assessment.blocking_gaps[0]
    assert "write.absence" in gap.summary
    assert "write.absence" in gap.remedy


def test_everything_present_is_feasible(world, monkeypatch):
    """The positive case, so the negative ones mean something."""
    _model(monkeypatch, _payload(world))
    _writable(monkeypatch, scopes=["write.absence"])
    world["connection"].granted_scopes = ["read.absence", "write.absence"]
    world["db"].flush()

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.FEASIBLE
    assert assessment.gaps == []
    assert assessment.intent == enums.ChangeIntent.MODIFY
    assert assessment.owning_connection_ids == [world["connection"].id]


def test_an_operation_for_a_different_intent_does_not_count(world, monkeypatch):
    """A connector that can create cannot therefore remove.

    The failure this prevents is a half-completed removal: the change is
    attempted because "the connector supports writes", and stops at the first
    thing it has no verb for.
    """
    _model(monkeypatch, _payload(world, intent="remove"))
    _writable(monkeypatch, scopes=[], intents=("new",))

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED
    assert "remove" in assessment.blocking_gaps[0].summary


def test_an_operation_for_a_different_node_kind_does_not_count(world, monkeypatch):
    """Being able to change a plan is not being able to change an approval chain."""
    _model(monkeypatch, _payload(world))
    _writable(monkeypatch, scopes=[], kinds=("business_process",))

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED


# ----------------------------------------------------------------- the axes


def test_an_empty_graph_is_a_data_gap_not_a_question(db, monkeypatch):
    """Nothing retrieved means nothing to ask about.

    The tempting failure is to interrogate the requester when the real problem
    is that the system was never extracted.
    """
    requirement = Requirement(
        id=new_id("req"),
        workspace_id="ws-empty",
        ref="MER-9002",
        title="Change something nobody extracted",
        summary="",
    )
    db.add(requirement)
    db.flush()
    _model(monkeypatch, {"intent": "modify", "targetNodeIds": [], "questions": []})

    assessment = feasibility_agent.assess(db, requirement)

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED
    assert [g.kind for g in assessment.gaps] == [enums.GapKind.DATA]


def test_stale_configuration_blocks(world, monkeypatch):
    """Past its own threshold, a source cannot be planned against."""
    _model(monkeypatch, _payload(world))
    _writable(monkeypatch, scopes=[])
    world["source"].last_synced_at = utcnow() - timedelta(days=30)
    world["db"].flush()

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED
    stale = [g for g in assessment.gaps if g.kind == enums.GapKind.FRESHNESS]
    assert len(stale) == 1
    assert "30 days ago" in stale[0].summary
    assert "7-day threshold" in stale[0].summary


def test_a_never_extracted_source_blocks(world, monkeypatch):
    _model(monkeypatch, _payload(world))
    _writable(monkeypatch, scopes=[])
    world["source"].last_synced_at = None
    world["db"].flush()

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    stale = [g for g in assessment.gaps if g.kind == enums.GapKind.FRESHNESS]
    assert "never completed an extraction" in stale[0].summary


def test_a_node_no_connection_owns_is_an_access_gap(world, monkeypatch):
    """Meridian knows the setting exists and cannot say where to change it."""
    _model(monkeypatch, _payload(world))
    world["connection"].source_id = None
    world["db"].flush()

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED
    gap = assessment.blocking_gaps[0]
    assert gap.kind == enums.GapKind.ACCESS
    assert "No connected system owns" in gap.summary


def test_unclear_intent_is_incomplete_not_blocked(world, monkeypatch):
    """An unclear request is answerable by the requester, so it is not BLOCKED."""
    _model(monkeypatch, _payload(world, intent="unclear"))
    _writable(monkeypatch, scopes=[])

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.INCOMPLETE
    assert assessment.blocking_gaps[0].kind == enums.GapKind.UNDERSTANDING


def test_blocked_outranks_incomplete(world, monkeypatch):
    """When access is missing, more detail is not the obstacle.

    Reporting INCOMPLETE here would send the requester off to write a longer
    description of a change that still could not be made.
    """
    _model(
        monkeypatch,
        _payload(
            world,
            intent="unclear",
            questions=[{"text": "Which timing?", "about": world["plan"].id, "options": ["A", "B"]}],
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.BLOCKED
    kinds = {g.kind for g in assessment.blocking_gaps}
    assert enums.GapKind.UNDERSTANDING in kinds
    assert enums.GapKind.ACCESS in kinds


# ------------------------------------------------------------------ questions


def test_a_fabricated_target_is_dropped_and_recorded(world, monkeypatch):
    """A fabricated target is worse than a fabricated citation.

    A citation misattributes a claim; a target is the thing the change would be
    applied to.
    """
    _model(monkeypatch, _payload(world, targetNodeIds=[world["plan"].id, "n-invented"]))

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.target_node_ids == [world["plan"].id]
    assert any(d["value"] == "n-invented" for d in assessment.discarded)


def test_a_question_about_something_not_retrieved_is_dropped(world, monkeypatch):
    """A question about a field that does not exist sends the user hunting."""
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[
                {"text": "What is the carryover cap?", "about": "carryoverCap", "options": []},
                {"text": "Which schedule?", "about": "accrualSchedule", "options": ["Annual"]},
            ],
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert [q.text for q in assessment.questions] == ["Which schedule?"]
    assert any("carryover" in d["value"] for d in assessment.discarded)


def test_a_question_may_be_about_a_node_or_an_attribute_key(world, monkeypatch):
    """Both are things the graph actually returned.

    `accrualSchedule` sits on the plan node rather than the accrual node,
    deliberately: the accrual is cut by retrieval's relevance floor for this
    request, so a question about its attributes would be correctly dropped.
    """
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[
                {"text": "Which plan?", "about": world["plan"].id, "options": []},
                {"text": "Which schedule?", "about": "accrualSchedule", "options": []},
            ],
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert len(assessment.questions) == 2


def test_questions_over_budget_are_dropped_and_recorded(world, monkeypatch):
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[
                {"text": f"Q{i}", "about": world["plan"].id, "options": []} for i in range(6)
            ],
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"], question_budget=2)

    assert len(assessment.questions) == 2
    assert sum(1 for d in assessment.discarded if d["reason"] == "over question budget") == 4


def test_the_budget_can_be_raised_with_a_reason(world, monkeypatch):
    """Adjustable, but the adjustment is on the record."""
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[
                {"text": f"Q{i}", "about": world["plan"].id, "options": []} for i in range(5)
            ],
            budgetRequest={"count": 5, "why": "A removal has more to establish."},
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"], question_budget=3)

    assert len(assessment.questions) == 5
    assert assessment.question_budget == 3
    assert assessment.budget_raised_to == 5
    assert "removal" in assessment.budget_reason


def test_a_budget_raise_without_a_reason_is_refused(world, monkeypatch):
    """A reason is what makes the ceiling a ceiling rather than a suggestion."""
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[
                {"text": f"Q{i}", "about": world["plan"].id, "options": []} for i in range(5)
            ],
            budgetRequest={"count": 5, "why": ""},
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"], question_budget=3)

    assert len(assessment.questions) == 3
    assert assessment.budget_raised_to is None


def test_a_budget_raise_is_capped_at_the_hard_ceiling(world, monkeypatch):
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[
                {"text": f"Q{i}", "about": world["plan"].id, "options": []} for i in range(40)
            ],
            budgetRequest={"count": 40, "why": "Everything is uncertain."},
        ),
    )

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert len(assessment.questions) == feasibility_agent.HARD_QUESTION_CEILING
    assert assessment.budget_raised_to == feasibility_agent.HARD_QUESTION_CEILING
    assert any("above ceiling" in d["reason"] for d in assessment.discarded)


def test_a_settled_question_is_not_asked_again(world, monkeypatch):
    """Rounds move outward. Re-asking is how an interview becomes a loop."""
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[{"text": "Which schedule?", "about": "accrualSchedule", "options": []}],
        ),
    )
    first = feasibility_agent.assess(world["db"], world["requirement"])
    first.questions[0].answered_as = "The accrual schedule"
    first.questions[0].answered_at = utcnow()
    world["db"].flush()

    second = feasibility_agent.assess(world["db"], world["requirement"])

    assert second.questions == []
    assert any(d["reason"] == "already settled" for d in second.discarded)


def test_an_accepted_unknown_counts_as_settled(world, monkeypatch):
    """Proceeding on a stated assumption is a decision, and it stays decided."""
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[{"text": "Which schedule?", "about": "accrualSchedule", "options": []}],
        ),
    )
    first = feasibility_agent.assess(world["db"], world["requirement"])
    first.questions[0].accepted_unknown = True
    first.questions[0].answered_at = utcnow()
    world["db"].flush()

    second = feasibility_agent.assess(world["db"], world["requirement"])

    assert second.questions == []


def test_unanswered_questions_make_it_incomplete(world, monkeypatch):
    _model(
        monkeypatch,
        _payload(
            world,
            questions=[{"text": "Which schedule?", "about": "accrualSchedule", "options": []}],
        ),
    )
    _writable(monkeypatch, scopes=[])

    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.verdict == enums.FeasibilityVerdict.INCOMPLETE
    assert "1 question(s)" in assessment.blocking_gaps[0].summary


# --------------------------------------------------------------- the stub path


def test_with_no_model_nothing_is_declared_understood(world):
    """The autouse fixture leaves no provider configured.

    The honest outcome is that the request has not been interpreted — not that it
    is fine.
    """
    assessment = feasibility_agent.assess(world["db"], world["requirement"])

    assert assessment.source == "stub"
    assert assessment.intent == enums.ChangeIntent.UNCLEAR
    assert not assessment.is_feasible
    assert "not been interpreted" in assessment.understood_as


# ---------------------------------------------------------------------- gate


def test_non_acting_stages_are_not_gated(world):
    """Discussion is where the gaps get resolved. Gating it would deadlock."""
    for stage in (
        enums.RequirementStage.DISCUSSING,
        enums.RequirementStage.IMPACT_REVIEW,
        enums.RequirementStage.TEST_PLANNING,
        enums.RequirementStage.REJECTED,
    ):
        gate.require_feasible(world["db"], world["requirement"], stage)


def test_acting_stages_refuse_without_an_assessment(world):
    """Never assessed is not the same as assessed and fine."""
    for stage in (
        enums.RequirementStage.AWAITING_APPROVAL,
        enums.RequirementStage.BUILDING,
        enums.RequirementStage.EVIDENCE,
        enums.RequirementStage.SIGNED_OFF,
    ):
        with pytest.raises(gate.NotFeasible) as raised:
            gate.require_feasible(world["db"], world["requirement"], stage)
        assert "has not been assessed" in raised.value.headline()


def test_the_refusal_carries_every_gap_and_its_remedy(world, monkeypatch):
    """A refusal reduced to a sentence loses the part that makes it actionable."""
    _model(monkeypatch, _payload(world))
    feasibility_agent.assess(world["db"], world["requirement"])

    with pytest.raises(gate.NotFeasible) as raised:
        gate.require_feasible(
            world["db"], world["requirement"], enums.RequirementStage.BUILDING
        )

    detail = raised.value.detail()
    assert detail["verdict"] == enums.FeasibilityVerdict.BLOCKED
    assert detail["gaps"], "the refusal must list what is missing"
    assert all(g["remedy"] for g in detail["gaps"])
    assert all(g["risk"] for g in detail["gaps"])


def test_a_feasible_assessment_opens_the_gate(world, monkeypatch):
    _model(monkeypatch, _payload(world))
    _writable(monkeypatch, scopes=["write.absence"])
    world["connection"].granted_scopes = ["write.absence"]
    world["db"].flush()

    feasibility_agent.assess(world["db"], world["requirement"])
    gate.require_feasible(world["db"], world["requirement"], enums.RequirementStage.BUILDING)


def test_the_latest_assessment_is_the_one_that_counts(world, monkeypatch):
    """A later refusal overrides an earlier pass.

    Otherwise a requirement that was feasible on Monday stays feasible after a
    connection loses its scopes.
    """
    _model(monkeypatch, _payload(world))
    _writable(monkeypatch, scopes=[])
    world["db"].flush()
    feasibility_agent.assess(world["db"], world["requirement"])
    gate.require_feasible(world["db"], world["requirement"], enums.RequirementStage.BUILDING)

    _writable(monkeypatch, scopes=["write.absence"])
    feasibility_agent.assess(world["db"], world["requirement"])

    with pytest.raises(gate.NotFeasible):
        gate.require_feasible(
            world["db"], world["requirement"], enums.RequirementStage.BUILDING
        )


def test_there_is_no_way_to_force_past_the_gate():
    """The absence of an override is the feature.

    Asserted structurally rather than by trying values: a keyword nobody can pass
    cannot be passed by accident later either.
    """
    import inspect

    params = set(inspect.signature(gate.require_feasible).parameters)
    assert params == {"db", "requirement", "stage"}
    assert not any(
        word in params for word in {"force", "override", "skip", "acknowledge_risk"}
    )


# ------------------------------------------------------------------- the API


def test_the_stage_endpoint_refuses_with_the_gaps_in_the_body(world, monkeypatch):
    """409, and the body says what would have to change.

    A refusal the UI has to paraphrase is a refusal the UI will paraphrase badly.
    """
    _model(monkeypatch, _payload(world))
    feasibility_agent.assess(world["db"], world["requirement"])
    world["db"].commit()

    from api.core.db import get_db

    app.dependency_overrides[get_db] = lambda: world["db"]
    try:
        client = TestClient(app)
        response = client.patch(
            f"/api/requirements/{world['requirement'].id}/stage",
            json={"stage": "building", "reason": "ship it"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["attemptedStage"] == "building"
    assert detail["gaps"]
    assert world["requirement"].stage == enums.RequirementStage.DISCUSSING


def test_an_assessment_is_written_even_when_the_answer_is_no(world, monkeypatch):
    """A refusal with no row behind it cannot be reviewed."""
    _model(monkeypatch, _payload(world))

    feasibility_agent.assess(world["db"], world["requirement"])

    rows = (
        world["db"]
        .query(FeasibilityAssessment)
        .filter(FeasibilityAssessment.requirement_id == world["requirement"].id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verdict == enums.FeasibilityVerdict.BLOCKED

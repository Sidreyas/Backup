"""
What the chat surface retrieves before it answers.

The failure this guards against is the quiet one: chat grounded on zero nodes
and replied "the configuration context does not contain any information
about..." — a *correct-looking refusal* for data that was sitting in the graph.
Nothing errored, nothing was fabricated, and the answer was wrong. A user
would conclude Meridian had not extracted their tenant.
"""

from __future__ import annotations

import pytest

from api.agents import ask as ask_agent
from api.core.ids import new_id
from api.domain.models import GraphNode
from api.graph import queries


@pytest.fixture
def leave_plan(db) -> GraphNode:
    node = GraphNode(
        id=new_id("n"),
        natural_key="workday:timeoffplan:HKG",
        kind="config_object",
        label="HKG Annual Leave",
        description="7 Days rising to 14 Days, by worker years of service.",
        provenance="Workday › Time Off Plan › HKG",
        workspace_id="ws-chat",
    )
    db.add(node)
    db.flush()
    return node


def test_a_whole_question_matches_nothing_as_a_literal_substring(db, leave_plan):
    """The mechanism of the bug, pinned so the fix is not undone.

    `queries.search` is a substring match and is right to be — the catalog
    search box wants exactly that. It is only wrong when a caller hands it a
    sentence.
    """
    found = queries.search(
        db, "What is the Hong Kong annual leave entitlement?", workspace_id="ws-chat"
    )
    assert found == []


def test_chat_retrieval_finds_the_plan_from_a_natural_question(db, leave_plan):
    """What the chat route must actually do.

    Same retrieval as `/api/ask`, so the two surfaces answer a question the
    same way. Two surfaces disagreeing about whether the data exists is worse
    than either being wrong alone.
    """
    found = ask_agent.retrieve(
        db, "What is the Hong Kong annual leave entitlement?", workspace_id="ws-chat"
    )
    assert leave_plan.id in {n.id for n in found}


def test_a_new_requirement_starts_with_an_empty_thread(db):
    """No canned opener.

    Creation used to seed two turns: the title echoed back as a user message,
    and a fixed assistant reply asking which population is affected. The reply
    cited nothing, cost nothing and consulted no graph, while looking exactly
    like a grounded turn — which is the one impression this product cannot
    afford to give before it has answered anything.
    """
    from api.domain.models import ChatMessage
    from api.routers.deps import Actor
    from api.routers.requirements import CreateRequirement, create_requirement

    created = create_requirement(
        CreateRequirement(title="Add a regional approval step", platform="Workday"),
        db=db,
        actor=Actor(email="tester@acme.example", name="Tester", role="ba"),
        workspace_id="ws-chat",
    )

    thread = (
        db.query(ChatMessage)
        .filter(ChatMessage.requirement_id == created["id"])
        .all()
    )
    assert thread == []


@pytest.mark.parametrize(
    "message",
    ["Hi", "hello", "hey there", "thanks", "ok", "What can you do?", "how are you", ""],
)
def test_small_talk_does_not_go_through_retrieval(message):
    """"Hi" is not a question about a tenant.

    Answered under the grounding rules it produced "I don't have any relevant
    configuration data for MER-1003 in the knowledge graph" — true, absurd,
    and it teaches people the assistant cannot understand them.
    """
    from api.routers.requirements import _is_small_talk

    assert _is_small_talk(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "What is the Hong Kong annual leave entitlement?",
        "test coverage?",
        "Which approval chains depend on this?",
        "hi, what does this change touch?",
        "leave",
    ],
)
def test_a_real_question_is_never_treated_as_chit_chat(message):
    """The dangerous direction.

    Misclassifying small talk costs a slightly stiff greeting. Misclassifying
    a real question drops its grounding, and the assistant answers about a
    customer's configuration from nothing at all — which is the one thing this
    product must never do. Short questions and greetings-with-a-question
    attached both stay on the grounded path.
    """
    from api.routers.requirements import _is_small_talk

    assert _is_small_talk(message) is False


def _node(db, key: str, label: str, *, description: str = "") -> GraphNode:
    node = GraphNode(
        id=new_id("n"),
        natural_key=key,
        kind="config_object",
        label=label,
        description=description,
        workspace_id="ws-breadth",
    )
    db.add(node)
    db.flush()
    return node


def test_a_weak_match_does_not_ride_along_with_a_strong_one(db):
    """One shared common word is not relevance.

    "What is the HKG annual leave entitlement?" matched four terms on the node
    that answers it and one term — "leave" — on five British statutory holiday
    nodes. All six were sent to the model, which cited the lot, correctly by
    its own rules. A grounded answer about Hong Kong that discusses UK holiday
    is still a wrong answer.
    """
    hkg = _node(db, "wd:hkg", "HKG Annual Leave Days Entitlement")
    _node(db, "wd:gbr", "GBR Statutory Holiday Entitlement")

    found = ask_agent.retrieve(
        db, "What is the HKG annual leave entitlement?", workspace_id="ws-breadth"
    )
    labels = {n.label for n in found}
    assert hkg.label in labels
    assert "GBR Statutory Holiday Entitlement" not in labels


def test_breadth_follows_the_question_rather_than_a_constant(db):
    """How many nodes are relevant is a property of the question.

    A fixed count pads a narrow question with noise and truncates a broad one.
    The padding is the more damaging half: a model handed a weakly-related
    node writes about it.
    """
    for i in range(6):
        _node(db, f"wd:plan{i}", f"Leave Plan {i}")
    _node(db, "wd:unique", "Singular Bereavement Policy")

    narrow = ask_agent.retrieve(
        db, "Singular Bereavement Policy", workspace_id="ws-breadth"
    )
    broad = ask_agent.retrieve(db, "Leave Plan", workspace_id="ws-breadth")

    assert len(narrow) < len(broad)


def test_retrieval_is_scoped_to_the_workspace(db, leave_plan):
    """Grounding a customer's question in another customer's graph is the
    worst outcome available here."""
    found = ask_agent.retrieve(
        db, "Hong Kong annual leave", workspace_id="ws-someone-else"
    )
    assert found == []

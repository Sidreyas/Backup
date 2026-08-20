"""
The rules that make Meridian a governance product rather than a dashboard.

Each test here corresponds to a claim the product makes to a customer. If one
of these fails, the claim is false — which is a different order of problem from
a broken screen, so they are tested at the service layer where the rule lives
rather than through the UI where it is merely displayed.
"""

from __future__ import annotations

import pytest

from api.core.ids import new_id
from api.domain import enums
from api.domain.governance import ApprovalGate, ApprovalPackage
from api.domain.models import Assertion, GraphNode, Requirement
from api.domain.stlc import TestCase, TestEnvironment, TestRun
from api.graph import queries
from api.ledger import chain
from api.services import approvals, execution


@pytest.fixture
def requirement(db) -> Requirement:
    r = Requirement(
        id=new_id("req"),
        workspace_id="ws-test",
        ref=f"MER-{new_id('x')[-4:]}",
        title="Add Regional HR approval",
        summary="Absences over 15 days need Regional HR approval.",
        stage=enums.RequirementStage.AWAITING_APPROVAL,
        platform="Workday",
        impacted_node_ids=[],
    )
    db.add(r)
    db.flush()
    return r


@pytest.fixture
def package(db, requirement) -> ApprovalPackage:
    p = ApprovalPackage(
        id=new_id("ap"),
        requirement_id=requirement.id,
        requirement_ref=requirement.ref,
        title=requirement.title,
        submitted_by="Sathish Kumar",
        risk_level="high",
        workspace_id="ws-test",
        evidence_summary={},
    )
    db.add(p)
    db.flush()
    return p


def _gate(db, package, *, requires: str | None) -> ApprovalGate:
    g = ApprovalGate(
        id=new_id("gate"),
        package_id=package.id,
        name="Production Sign-off",
        role="QA Lead",
        requires_evidence_grade=requires,
        decision=enums.ApprovalDecision.PENDING,
        blocked_by=[],
        position=0,
    )
    db.add(g)
    db.flush()
    return g


def _run(db, requirement, *, grade: str, status: str) -> TestRun:
    r = TestRun(
        id=new_id("run"),
        ref=f"R-{new_id('x')[-4:]}",
        requirement_id=requirement.id,
        title="A run",
        grade=grade,
        status=status,
        runner="test",
        environment={},
        workspace_id="ws-test",
    )
    db.add(r)
    db.flush()
    return r


def _oversight(**overrides) -> dict:
    base = {
        "review_duration_seconds": 300,
        "artifacts_opened": [],
        "artifacts_available": 0,
        "ai_recommendation": "none",
        "human_decision": "approve",
        "override_rationale": None,
    }
    base.update(overrides)
    return approvals.oversight_record(**base)


# ------------------------------------------------- the verified/asserted rule


def test_asserted_evidence_cannot_satisfy_a_verified_gate(db, requirement, package):
    """The product's central claim, enforced server-side.

    An agent saying "it works" must not open a gate that demands a
    deterministic, replayable test. If this passes silently, every compliance
    statement the product makes is false.
    """
    gate = _gate(db, package, requires=enums.EvidenceGrade.VERIFIED)
    _run(db, requirement, grade=enums.EvidenceGrade.ASSERTED, status=enums.RunStatus.PASSED)

    with pytest.raises(approvals.GateBlocked) as exc:
        approvals.decide(
            db,
            package_id=package.id,
            gate_id=gate.id,
            decision=enums.ApprovalDecision.APPROVED,
            comment="looks fine",
            oversight=_oversight(),
            actor_name="Sathish Kumar",
            actor_email="a@acme.example",
        )

    assert "verified evidence" in exc.value.reasons[0]
    db.refresh(gate)
    assert gate.decision == enums.ApprovalDecision.PENDING


def test_verified_evidence_satisfies_the_gate(db, requirement, package):
    gate = _gate(db, package, requires=enums.EvidenceGrade.VERIFIED)
    _run(db, requirement, grade=enums.EvidenceGrade.VERIFIED, status=enums.RunStatus.PASSED)

    approvals.decide(
        db,
        package_id=package.id,
        gate_id=gate.id,
        decision=enums.ApprovalDecision.APPROVED,
        comment="verified evidence attached",
        oversight=_oversight(),
        actor_name="Sathish Kumar",
        actor_email="a@acme.example",
    )
    db.refresh(gate)
    assert gate.decision == enums.ApprovalDecision.APPROVED


def test_a_failed_run_blocks_even_with_verified_evidence(db, requirement, package):
    """A pass and a failure is not a pass."""
    gate = _gate(db, package, requires=enums.EvidenceGrade.VERIFIED)
    _run(db, requirement, grade=enums.EvidenceGrade.VERIFIED, status=enums.RunStatus.PASSED)
    _run(db, requirement, grade=enums.EvidenceGrade.VERIFIED, status=enums.RunStatus.FAILED)

    reasons = approvals.evaluate_blockers(db, package, gate)
    assert any("failed" in r for r in reasons)


def test_rejection_is_never_blocked(db, requirement, package):
    """Blockers are reasons not to approve.

    Using them to prevent a rejection would trap a package that should be sent
    back — the opposite of what they are for.
    """
    gate = _gate(db, package, requires=enums.EvidenceGrade.VERIFIED)
    approvals.decide(
        db,
        package_id=package.id,
        gate_id=gate.id,
        decision=enums.ApprovalDecision.REJECTED,
        comment="not enough evidence",
        oversight=_oversight(human_decision="reject"),
        actor_name="Sathish Kumar",
        actor_email="a@acme.example",
    )
    db.refresh(gate)
    assert gate.decision == enums.ApprovalDecision.REJECTED


# ------------------------------------------------------- human oversight


def test_override_requires_a_rationale(db, requirement, package):
    """EU AI Act Art. 14: an override with no stated reason is not oversight."""
    gate = _gate(db, package, requires=None)
    with pytest.raises(approvals.GateBlocked) as exc:
        approvals.decide(
            db,
            package_id=package.id,
            gate_id=gate.id,
            decision=enums.ApprovalDecision.APPROVED,
            comment="",
            oversight=_oversight(ai_recommendation="reject", human_decision="approve"),
            actor_name="Sathish Kumar",
            actor_email="a@acme.example",
        )
    assert "rationale" in exc.value.reasons[0]


def test_overridden_is_derived_not_claimed():
    """Whether a human went against the recommendation is a fact about the two
    values, not something the client gets to assert."""
    assert approvals.oversight_record(
        review_duration_seconds=1,
        artifacts_opened=[],
        artifacts_available=0,
        ai_recommendation="reject",
        human_decision="approve",
        override_rationale="business need",
    )["overridden"]

    assert not approvals.oversight_record(
        review_duration_seconds=1,
        artifacts_opened=[],
        artifacts_available=0,
        ai_recommendation="approve",
        human_decision="approve",
        override_rationale=None,
    )["overridden"]


# ------------------------------------------------------------- audit chain


def test_chain_verifies_and_detects_tampering(db):
    for i in range(4):
        chain.append(
            db,
            chain.RecordInput(
                action="requirement.created",
                actor="Sathish Kumar",
                actor_type=enums.ActorType.HUMAN,
                summary=f"Entry {i}",
                workspace_id="ws-test",
            ),
        )

    assert chain.verify(db).valid

    head = chain.head_seq(db)
    assert chain.simulate_tamper(db, head - 2)

    result = chain.verify(db)
    assert not result.valid
    # The earliest divergence, not merely some divergence — an auditor needs to
    # know where the record stopped being trustworthy.
    assert result.first_broken_seq == head - 2


def test_chain_commits_to_field_level_changes(db):
    """Omitting `changes` from the hash would let someone rewrite a prior value
    without breaking the chain, defeating the point of storing it."""
    entry = chain.append(
        db,
        chain.RecordInput(
            action="testcase.edited",
            actor="Sathish Kumar",
            actor_type=enums.ActorType.HUMAN,
            summary="Expectation weakened",
            changes=[
                {
                    "field": "expectedResult",
                    "label": "Expected result",
                    "before": "Rejected above 20%",
                    "after": "Rejected above 40%",
                }
            ],
            workspace_id="ws-test",
        ),
    )
    assert chain.verify(db).valid

    entry.changes = [
        {
            "field": "expectedResult",
            "label": "Expected result",
            "before": "Rejected above 40%",
            "after": "Rejected above 40%",
        }
    ]
    db.flush()
    assert not chain.verify(db).valid


def test_retention_defaults_reflect_the_obligation(db):
    approval = chain.append(
        db,
        chain.RecordInput(
            action="approval.granted",
            actor="Sathish Kumar",
            actor_type=enums.ActorType.HUMAN,
            summary="Approved",
        ),
    )
    assert approval.retention == enums.RetentionClass.SOX

    ai_entry = chain.append(
        db,
        chain.RecordInput(
            action="requirement.discussed",
            actor="agent",
            actor_type=enums.ActorType.AGENT,
            summary="A turn",
            ai={
                "model": "claude-opus-5",
                "modelVersion": "2026-07-14",
                "promptHash": "abc",
                "tokensIn": 1,
                "tokensOut": 1,
                "temperature": 0.2,
                "groundedNodeIds": [],
            },
        ),
    )
    assert ai_entry.retention == enums.RetentionClass.AI_ACT

    incident = chain.append(
        db,
        chain.RecordInput(
            action="incident.raised",
            actor="Sathish Kumar",
            actor_type=enums.ActorType.HUMAN,
            summary="An incident",
        ),
    )
    assert incident.retention == enums.RetentionClass.PERMANENT


# ------------------------------------------------------ graph traversal


@pytest.fixture
def graph(db):
    """A → B → C → A cycle, plus D off C, plus E behind a low-confidence edge."""
    ids = {}
    for key in "ABCDE":
        node = GraphNode(
            id=new_id("n"),
            workspace_id="ws-test",
            label=f"Node {key}",
            kind=enums.NodeKind.CONFIG_OBJECT,
            natural_key=f"test:{key}",
            source_id="src-test",
        )
        db.add(node)
        ids[key] = node.id
    db.flush()

    edges = [
        ("A", "B", enums.LinkConfidence.CONFIRMED),
        ("B", "C", enums.LinkConfidence.HIGH),
        ("C", "A", enums.LinkConfidence.MEDIUM),
        ("C", "D", enums.LinkConfidence.HIGH),
        ("D", "E", enums.LinkConfidence.LOW),
    ]
    for subject, obj, confidence in edges:
        db.add(
            Assertion(
                id=new_id("as"),
                workspace_id="ws-test",
                subject_id=ids[subject],
                predicate="DEPENDS_ON",
                object_id=ids[obj],
                confidence=confidence,
                status=enums.AssertionStatus.PROPOSED,
            )
        )
    db.flush()
    return ids


def test_traversal_terminates_on_a_cycle(db, graph):
    """Configuration graphs are full of cycles. Without a guard the recursive
    CTE never returns, which in production is an outage rather than a bug."""
    reached = queries.neighbours(db, [graph["A"]], max_depth=4)
    labels = {r.node.label for r in reached}
    assert "Node B" in labels
    assert "Node C" in labels
    # The seed is the change itself, not part of its blast radius.
    assert "Node A" not in labels


def test_traversal_respects_the_confidence_threshold(db, graph):
    """E sits behind a `low` edge and must not appear at the default threshold.

    A blast radius computed as though hypotheses were facts overstates impact,
    which trains people to ignore impact analysis — the worst outcome for a
    product built on it.
    """
    reached = queries.neighbours(db, [graph["A"]], max_depth=5)
    assert "Node E" not in {r.node.label for r in reached}

    permissive = queries.neighbours(
        db, [graph["A"]], max_depth=5, min_confidence=enums.LinkConfidence.LOW
    )
    assert "Node E" in {r.node.label for r in permissive}


def test_path_confidence_is_the_weakest_link(db, graph):
    """A chain is only as strong as its weakest edge. Reporting the strongest
    would overstate how much the graph actually knows."""
    reached = queries.neighbours(db, [graph["A"]], max_depth=4)
    by_label = {r.node.label: r for r in reached}
    # A→B is confirmed, B→C is high: the path to C is at best 'high'.
    assert by_label["Node C"].path_confidence != enums.LinkConfidence.CONFIRMED


def test_superseded_assertions_leave_the_live_graph(db, graph):
    from api.core.ids import utcnow

    live_before = len(queries.live_assertions(db, "ws-test"))
    assertion = queries.live_assertions(db, "ws-test")[0]
    assertion.superseded_at = utcnow()
    assertion.status = enums.AssertionStatus.SUPERSEDED
    db.flush()

    assert len(queries.live_assertions(db, "ws-test")) == live_before - 1


# ------------------------------------------------------------- execution


@pytest.fixture
def environment(db) -> TestEnvironment:
    env = TestEnvironment(
        id=new_id("env"),
        name="Sandbox",
        kind="sandbox",
        platform="Workday",
        status=enums.EnvironmentStatus.READY,
        fingerprint={"environment": "Sandbox", "release": "2026R1"},
        workspace_id="ws-test",
    )
    db.add(env)
    db.flush()
    return env


def _case(db, requirement, *, automatable: bool) -> TestCase:
    c = TestCase(
        id=new_id("tc"),
        ref=f"TC-{new_id('x')[-4:]}",
        requirement_id=requirement.id,
        title="A case",
        state=enums.ReviewState.APPROVED,
        automatable=automatable,
        expected_result="It works",
        steps=[],
    )
    db.add(c)
    db.flush()
    return c


def test_a_case_nobody_ran_is_skipped_not_passed(db, requirement, environment):
    """Meridian does not yet drive a system under test. Recording an unrun case
    as passed would be the single most damaging thing this product could do."""
    case = _case(db, requirement, automatable=True)
    ex = execution.run(
        db,
        case_ids=[case.id],
        environment_id=environment.id,
        suite_name="Ad-hoc",
        requirement_id=requirement.id,
        plan_id=None,
        suite_id=None,
        triggered_by="Sathish Kumar",
        triggered_by_type=enums.ActorType.HUMAN,
        reported=[],
        workspace_id="ws-test",
    )
    assert [r.status for r in ex.results] == [enums.RunStatus.SKIPPED]


def test_grade_is_mechanical_not_claimed(db, requirement, environment):
    """A runner that could declare its own output verified would make the
    distinction meaningless. Verified requires automatable *and* artifacts."""
    auto = _case(db, requirement, automatable=True)
    manual = _case(db, requirement, automatable=False)

    ex = execution.run(
        db,
        case_ids=[auto.id, manual.id],
        environment_id=environment.id,
        suite_name="Mixed",
        requirement_id=requirement.id,
        plan_id=None,
        suite_id=None,
        triggered_by="runner",
        triggered_by_type=enums.ActorType.AGENT,
        reported=[
            execution.ReportedResult(
                case_id=auto.id,
                status=enums.RunStatus.PASSED,
                actual="ok",
                artifacts=[{"kind": "trace", "label": "trace.zip", "sha256": "a" * 64}],
            ),
            # A manual case *with* artifacts is still only an assertion.
            execution.ReportedResult(
                case_id=manual.id,
                status=enums.RunStatus.PASSED,
                actual="ok",
                artifacts=[{"kind": "screenshot", "label": "s.png", "sha256": "b" * 64}],
            ),
        ],
        workspace_id="ws-test",
    )
    by_case = {r.case_id: r for r in ex.results}
    assert by_case[auto.id].grade == enums.EvidenceGrade.VERIFIED
    assert by_case[manual.id].grade == enums.EvidenceGrade.ASSERTED


def test_an_automatable_case_without_artifacts_is_only_asserted(
    db, requirement, environment
):
    case = _case(db, requirement, automatable=True)
    ex = execution.run(
        db,
        case_ids=[case.id],
        environment_id=environment.id,
        suite_name="No artifacts",
        requirement_id=requirement.id,
        plan_id=None,
        suite_id=None,
        triggered_by="runner",
        triggered_by_type=enums.ActorType.AGENT,
        reported=[
            execution.ReportedResult(
                case_id=case.id, status=enums.RunStatus.PASSED, actual="trust me"
            )
        ],
        workspace_id="ws-test",
    )
    assert ex.results[0].grade == enums.EvidenceGrade.ASSERTED

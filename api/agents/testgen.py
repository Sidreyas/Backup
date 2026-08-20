"""
Test plan and test case generation, with judging.

Generation is grounded in the impact analysis rather than in the requirement
text alone. A case written from prose tests what someone said; a case written
from the impacted configuration tests what will actually change — and can cite
the node it covers, which is what makes coverage measurable instead of
asserted.

The judge is deliberately advisory. Its verdict is recorded and shown, but
approval stays a human action: a model scoring another model's output is
evidence for a reviewer, not a substitute for one. Auto-approving on a high
score would put an unaccountable actor inside the control this whole system
exists to prove. `set_state` is the only path to `approved`, and it requires an
actor.

Generated cases start in `draft`, never `approved`. Anything else would let
machine output enter the record without review.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.agents.llm import extract_json, llm, record_cost
from api.core.ids import iso, new_id, utcnow
from api.domain import enums
from api.domain.models import ImpactAnalysis, ImpactItem, Requirement
from api.domain.stlc import TestCase, TestPlan

PLAN_SYSTEM = """You are the test planning agent of an enterprise change governance platform.

Given a change and its impact analysis, produce a test plan. The plan must be \
specific to this change — a plan that would fit any change is worthless.

Rules:
- Entry and exit criteria must be checkable. "Testing is complete" is not a \
criterion; "every breaking-severity node has at least one passing verified case" is.
- Scope out what you are deliberately not testing, and why.
- Risks must name what could go wrong in *this* change, with a mitigation.

Reply with JSON only:
{"objective": "...", "scopeIn": ["..."], "scopeOut": ["..."],
 "levels": ["unit|integration|system|uat|regression"],
 "types": ["functional|security|performance|accessibility|data_integrity|compliance"],
 "entryCriteria": ["..."], "exitCriteria": ["..."],
 "risks": [{"risk": "...", "likelihood": "high|medium|low", "mitigation": "..."}],
 "estimatedCases": 0, "estimatedDurationHours": 0}"""

CASE_SYSTEM = """You are the test design agent of an enterprise change governance platform.

Write test cases for the impacted configuration you are given. Each case must \
trace to at least one node id from the impact analysis.

Rules:
- Steps must be executable by someone who does not know the change. "Verify it \
works" is not a step.
- The expected result is the single assertion the case proves. One case, one claim.
- Mark `automatable` false when the case genuinely needs human judgement. Do not \
mark everything automatable to look thorough — a non-automatable case honestly \
labelled produces an assertion, and that is allowed.
- Cover breaking and major severity nodes first.

Reply with JSON only:
{"cases": [{"title": "...", "level": "...", "type": "...", "priority": "critical|high|medium|low",
  "automatable": true, "preconditions": ["..."],
  "steps": [{"action": "...", "expected": "..."}],
  "expectedResult": "...", "testData": "...", "coversNodeIds": ["..."],
  "rationale": "why this case exists"}]}"""

JUDGE_SYSTEM = """You are the review agent. Score a generated test case on five dimensions, \
1.0 to 5.0, to one decimal.

- specificity: could this case have been written without seeing this change? If yes, score low.
- traceability: does it cite the configuration it covers?
- testability: could someone execute it and get an unambiguous pass or fail?
- risk_coverage: does it exercise what is actually risky about the change?
- evidence_grounding: does it produce something that would convince a reviewer?

Every score needs a rationale saying why it is not higher. A bare number is an \
opinion; a number with its reason is something a reviewer can disagree with.

Reply with JSON only:
{"scores": [{"dimension": "...", "score": 0.0, "rationale": "...", "citations": ["..."]}],
 "verdict": "accept|revise|reject", "summary": "one line"}"""


def _next_ref(db: Session, model, prefix: str, width: int = 4) -> str:
    """Continue an existing ref series rather than restarting from 1."""
    count = db.execute(select(func.count()).select_from(model)).scalar_one()
    return f"{prefix}-{str(count + 1).zfill(width)}"


def generate_plan(
    db: Session, requirement: Requirement, analysis: ImpactAnalysis | None, actor: str
) -> TestPlan:
    """Author a test plan for a requirement."""
    items = list(analysis.items) if analysis else []
    prompt = _plan_prompt(requirement, items)

    result = llm.complete(
        system=PLAN_SYSTEM,
        prompt=prompt,
        max_tokens=3000,
        grounded_node_ids=[i.node_id for i in items],
        stub=_plan_stub(requirement, items),
    )
    record_cost(
        db,
        result,
        kind="plan_generation",
        requirement_id=requirement.id,
        workspace_id=requirement.workspace_id,
        detail=f"Test plan generated for {requirement.ref}.",
    )

    parsed = extract_json(result.text) or {}

    covered = [i.node_id for i in items if i.severity != enums.ImpactSeverity.NONE]
    plan = TestPlan(
        id=new_id("tp"),
        ref=_next_ref(db, TestPlan, "TP"),
        requirement_id=requirement.id,
        requirement_ref=requirement.ref,
        title=f"Test plan — {requirement.title}",
        origin=enums.ArtifactOrigin.AI_GENERATED,
        # Draft, never approved. Machine output does not enter the record
        # as reviewed.
        state=enums.ReviewState.DRAFT,
        version=1,
        author=actor,
        objective=parsed.get("objective", "")
        or "No objective was generated for this plan.",
        scope_in=_strings(parsed.get("scopeIn")),
        scope_out=_strings(parsed.get("scopeOut")),
        levels=_enum_list(parsed.get("levels"), enums.TestLevel),
        types=_enum_list(parsed.get("types"), enums.TestType),
        risks=[
            {
                "id": new_id("rk"),
                "risk": r.get("risk", ""),
                "likelihood": r.get("likelihood", "medium"),
                "mitigation": r.get("mitigation", ""),
            }
            for r in parsed.get("risks", [])
            if isinstance(r, dict)
        ],
        covered_node_ids=covered,
        # Gaps are computed, not taken from the model. A plan claiming full
        # coverage is a claim; this is the arithmetic.
        uncovered_node_ids=[],
        estimated_cases=int(parsed.get("estimatedCases") or 0),
        estimated_duration_hours=float(parsed.get("estimatedDurationHours") or 0),
        generation_cost_usd=result.cost_usd,
        model=result.model,
        model_version=result.model_version,
    )
    db.add(plan)
    db.flush()

    _write_criteria(db, plan.id, "plan", "entry", _strings(parsed.get("entryCriteria")))
    _write_criteria(db, plan.id, "plan", "exit", _strings(parsed.get("exitCriteria")))

    db.flush()
    return plan


def generate_cases(
    db: Session,
    requirement: Requirement,
    plan: TestPlan,
    analysis: ImpactAnalysis | None,
    actor: str,
    *,
    judge: bool = True,
) -> list[TestCase]:
    """Author test cases against a plan, and judge each one."""
    items = list(analysis.items) if analysis else []
    prompt = _case_prompt(requirement, plan, items)

    result = llm.complete(
        system=CASE_SYSTEM,
        prompt=prompt,
        max_tokens=8000,
        grounded_node_ids=[i.node_id for i in items],
        stub=_case_stub(items),
    )
    record_cost(
        db,
        result,
        kind="case_generation",
        requirement_id=requirement.id,
        workspace_id=requirement.workspace_id,
        detail=f"Test cases generated for {plan.ref}.",
    )

    parsed = extract_json(result.text) or {}
    allowed = {i.node_id for i in items}

    created: list[TestCase] = []
    for raw in parsed.get("cases", []):
        if not isinstance(raw, dict) or not raw.get("title"):
            continue

        # Only node ids the analysis actually contained. A case claiming to
        # cover a node that was never impacted inflates coverage against
        # something that does not exist.
        covers = [n for n in _strings(raw.get("coversNodeIds")) if n in allowed]

        case = TestCase(
            id=new_id("tc"),
            ref=_next_ref(db, TestCase, "TC"),
            plan_id=plan.id,
            requirement_id=requirement.id,
            title=raw["title"],
            origin=enums.ArtifactOrigin.AI_GENERATED,
            state=enums.ReviewState.DRAFT,
            level=_one_of(raw.get("level"), enums.TestLevel, enums.TestLevel.SYSTEM),
            type=_one_of(raw.get("type"), enums.TestType, enums.TestType.FUNCTIONAL),
            priority=_one_of(
                raw.get("priority"), enums.Criticality, enums.Criticality.MEDIUM
            ),
            automatable=bool(raw.get("automatable", True)),
            preconditions=_strings(raw.get("preconditions")),
            steps=[
                {
                    "id": new_id("st"),
                    "index": i + 1,
                    "action": s.get("action", ""),
                    "expected": s.get("expected", ""),
                }
                for i, s in enumerate(raw.get("steps", []))
                if isinstance(s, dict)
            ],
            expected_result=raw.get("expectedResult", ""),
            test_data=raw.get("testData", ""),
            covers_node_ids=covers,
            author=actor,
            rationale=raw.get("rationale", ""),
            estimated_duration_seconds=int(raw.get("estimatedDurationSeconds") or 120),
            tags=_strings(raw.get("tags")),
        )
        db.add(case)
        created.append(case)

    db.flush()

    if judge and llm.enabled:
        for case in created:
            case.rubric = judge_case(db, case, requirement)

    # Now the arithmetic: what the plan claimed to cover, minus what the cases
    # actually cover.
    actually = {n for c in created for n in c.covers_node_ids}
    plan.uncovered_node_ids = [n for n in plan.covered_node_ids if n not in actually]
    plan.estimated_cases = len(created)

    db.flush()
    return created


def judge_case(db: Session, case: TestCase, requirement: Requirement) -> dict | None:
    """Score one generated case.

    Returns the rubric to store on the case. Advisory only — nothing in this
    function can change a case's review state.
    """
    prompt = (
        f"CHANGE: {requirement.ref} — {requirement.title}\n"
        f"{requirement.summary}\n\n"
        f"TEST CASE\n"
        f"Title: {case.title}\n"
        f"Level: {case.level} | Type: {case.type} | Priority: {case.priority}\n"
        f"Automatable: {case.automatable}\n"
        f"Preconditions: {'; '.join(case.preconditions) or '(none)'}\n"
        "Steps:\n"
        + "\n".join(
            f"  {s.get('index')}. {s.get('action')} → {s.get('expected')}"
            for s in case.steps
        )
        + f"\nExpected result: {case.expected_result}\n"
        f"Covers node ids: {', '.join(case.covers_node_ids) or '(none)'}\n"
        f"Stated rationale: {case.rationale}\n"
    )

    result = llm.complete(
        system=JUDGE_SYSTEM,
        prompt=prompt,
        max_tokens=1500,
        grounded_node_ids=case.covers_node_ids,
    )
    record_cost(
        db,
        result,
        kind="case_judging",
        requirement_id=requirement.id,
        workspace_id=requirement.workspace_id,
        detail=f"Rubric scored for {case.ref}.",
    )

    parsed = extract_json(result.text)
    if not isinstance(parsed, dict) or not parsed.get("scores"):
        return None

    valid = {d.value for d in enums.RubricDimension}
    scores = [
        {
            "dimension": s.get("dimension"),
            "score": round(float(s.get("score", 0)), 1),
            "rationale": s.get("rationale", ""),
            "citations": _strings(s.get("citations")),
        }
        for s in parsed["scores"]
        if isinstance(s, dict) and s.get("dimension") in valid
    ]
    if not scores:
        return None

    overall = round(sum(s["score"] for s in scores) / len(scores), 1)
    verdict = parsed.get("verdict")
    if verdict not in {v.value for v in enums.RubricVerdict}:
        verdict = enums.RubricVerdict.REVISE

    return {
        "judgeModel": result.model,
        "judgedAt": iso(utcnow()),
        "scores": scores,
        "overall": overall,
        "verdict": verdict,
        "summary": parsed.get("summary", ""),
        # Without the inputs the score is unreproducible, and an unreproducible
        # score has no place in an audit trail.
        "inputs": [
            f"Requirement {requirement.ref}",
            f"Test case {case.ref}",
            *[f"Node {n}" for n in case.covers_node_ids],
        ],
    }


# --- prompt construction ---------------------------------------------------


def _impact_block(items: list[ImpactItem]) -> str:
    if not items:
        return "(no impact analysis available — nothing has been grounded against the graph)"
    return "\n".join(
        f"- id={i.node_id} | {i.node_label} ({i.node_kind})\n"
        f"    severity={i.severity} confidence={i.confidence}\n"
        f"    why: {i.reason}\n"
        f"    provenance: {i.provenance}"
        for i in items
    )


def _plan_prompt(requirement: Requirement, items: list[ImpactItem]) -> str:
    return (
        f"CHANGE ({requirement.ref})\n"
        f"Title: {requirement.title}\n"
        f"Summary: {requirement.summary}\n"
        f"Target system: {requirement.platform}\n"
        f"Risk level: {requirement.risk_level}\n\n"
        f"IMPACT ANALYSIS\n{_impact_block(items)}\n\n"
        "Produce the test plan. JSON only."
    )


def _case_prompt(requirement: Requirement, plan: TestPlan, items: list[ImpactItem]) -> str:
    ranked = sorted(
        items,
        key=lambda i: {"breaking": 0, "major": 1, "minor": 2, "none": 3}.get(i.severity, 3),
    )
    return (
        f"CHANGE ({requirement.ref})\n"
        f"Title: {requirement.title}\n"
        f"Summary: {requirement.summary}\n\n"
        f"PLAN OBJECTIVE\n{plan.objective}\n"
        f"In scope: {'; '.join(plan.scope_in) or '(unstated)'}\n"
        f"Out of scope: {'; '.join(plan.scope_out) or '(unstated)'}\n\n"
        f"IMPACTED CONFIGURATION, most severe first\n{_impact_block(ranked)}\n\n"
        "Write the test cases. JSON only."
    )


# --- stubs -----------------------------------------------------------------


def _plan_stub(requirement: Requirement, items: list[ImpactItem]) -> str:
    """A plan that is honest about not having been generated."""
    return json.dumps(
        {
            "objective": (
                f"Verify {requirement.ref} without regressing the configuration it "
                "touches. This objective is a placeholder — no language model is "
                "configured, so no plan has been authored."
            ),
            "scopeIn": [i.node_label for i in items[:10]],
            "scopeOut": [],
            "levels": ["system", "regression"],
            "types": ["functional"],
            "entryCriteria": [
                "A language model is configured so a real plan can be authored."
            ],
            "exitCriteria": [
                "Every impacted node has at least one passing case with verified evidence."
            ],
            "risks": [],
            "estimatedCases": 0,
            "estimatedDurationHours": 0,
        }
    )


def _case_stub(items: list[ImpactItem]) -> str:
    """No cases. Fabricating plausible-looking ones would be worse than none."""
    return json.dumps({"cases": []})


# --- coercion --------------------------------------------------------------


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str | int | float) and str(v).strip()]


def _one_of(value: object, enum_cls, default: str) -> str:
    allowed = {e.value for e in enum_cls}
    return value if isinstance(value, str) and value in allowed else default


def _enum_list(value: object, enum_cls) -> list[str]:
    allowed = {e.value for e in enum_cls}
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v in allowed]


def _write_criteria(
    db: Session, owner_id: str, owner_type: str, role: str, texts: list[str]
) -> None:
    from api.domain.stlc import Criterion

    for i, text in enumerate(texts):
        db.add(
            Criterion(
                id=new_id("cr"),
                text=text,
                # Unevaluated, not met. A criterion nobody has checked must not
                # read as satisfied.
                met=None,
                evaluated_by=None,
                owner_type=owner_type,
                owner_id=owner_id,
                role=role,
                position=i,
            )
        )

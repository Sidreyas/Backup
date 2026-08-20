"""
Feasibility assessment.

Three things have to be true before a requirement can be acted on, and this
module checks each one instead of asking a model whether it feels confident:

  1. **Understanding** — every material decision has been made.
  2. **Data** — the configuration the change touches is in the graph, and fresh.
  3. **Access** — Meridian can make the change in the system that owns it.

The verdict is computed from those three. It is never generated, and there is no
override. That is the whole design, and the reason is timing: the pressure to
proceed anyway arrives exactly when the answer matters most, phrased as "just do
it". A model asked "is this feasible?" under that pressure will say yes. A
function that counts blocking gaps will not.

So the model's job is narrow and checkable:

  - classify the intent,
  - restate the request so the requester can correct a misreading,
  - propose the next questions.

It never decides feasibility, never nominates a node that was not retrieved, and
never chooses which system gets written to. That last one is derived: a node
records the source it came from, and a change has to be made where the
configuration actually lives. Asking a model to name the target system would
invite it to name a plausible one.

**On questions.** Retrieval runs first, so most of what an interview would ask is
looked up instead. There is exactly one HKG annual leave plan, so "which plan?"
is not a question — it is a lookup with one answer, and asking it hands Meridian's
work back to the requester. What survives is the genuine residue: which of four
timing fields, what value, from when, and whether history recalculates. Each
question carries candidates drawn from the graph, because a four-way choice is
answerable in a click and an open question is not.

Answers accumulate across assessments. A question already settled is stated as
settled in the next prompt rather than asked again, so successive rounds move
outward instead of circling — the frontier idea, made durable by writing it down.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.agents import ask as ask_agent
from api.agents.llm import extract_json, llm, record_cost
from api.connectors import registry
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.feasibility import (
    ClarificationQuestion,
    FeasibilityAssessment,
    FeasibilityGap,
)
from api.domain.models import Connection, GraphNode, KnowledgeSource, Requirement

#: How many retrieved nodes are offered to the model as candidate targets. The
#: cap is about precision rather than cost: a change that appears to touch thirty
#: nodes has not been understood yet, and letting the model pick freely from
#: thirty produces a target list nobody can review.
MAX_TARGETS = 12

#: Questions per round, before any adjustment.
#:
#: Three, because a requester answering a form abandons it. `/grill-me` runs to
#: forty across four rounds and works, but its subject volunteered to be
#: interviewed about their own idea; a business analyst who typed one sentence
#: did not.
DEFAULT_QUESTION_BUDGET = 3

#: The ceiling on an adjustment. The model may ask for more than the default when
#: it can say why, which is the case that matters — a removal genuinely has more
#: to establish than a value change. Past this the extra questions are dropped
#: and the drop is recorded, so "it needed to ask more" stays a claim someone can
#: audit rather than an unbounded interrogation.
HARD_QUESTION_CEILING = 8

SYSTEM = """You are the requirement analyst of an enterprise change governance platform.

You will be given a change request, the configuration nodes a knowledge graph \
retrieved for it, and any decisions already settled in earlier rounds.

Your job is to classify the request, restate it, and decide what still needs \
asking. You do NOT decide whether the change is possible — permissions and data \
availability are checked elsewhere, and an opinion from you about them would be \
guesswork.

Rules you must follow:
- Classify intent as exactly one of: new, modify, remove, downgrade, unclear. \
Use "unclear" when the request does not say which of several things it means. \
"unclear" is a real answer; a confident wrong classification is worse.
- Nominate targets ONLY from the node ids given to you. Never introduce an id \
that is not in the list.
- Ask ONLY what the retrieved configuration cannot already answer. If exactly \
one node matches what the request names, that is settled — do not ask which one.
- Never re-ask something listed as already settled.
- Every question must set "about" to either a given node id or an attribute key \
that appears in the given nodes. A question about a field that does not exist \
sends the requester looking for it.
- Populate "options" from values visible in the given configuration whenever the \
question is a choice between existing things. An open question is a last resort.
- "rationale" must say what the answer changes. If you cannot say what it \
changes, the question is not needed.

Reply with JSON only, in this exact shape:
{"intent": "new|modify|remove|downgrade|unclear",
 "understoodAs": "one paragraph restating the request in your own words",
 "targetNodeIds": ["..."],
 "questions": [{"text": "...", "rationale": "...", "about": "...", "options": ["..."]}],
 "budgetRequest": {"count": 0, "why": ""}}

Set budgetRequest.count above the stated budget only when the request genuinely \
cannot be settled within it, and say why. Leave it 0 otherwise."""


@dataclass(slots=True)
class _Gap:
    """A gap before it is persisted."""

    kind: str
    summary: str
    remedy: str = ""
    subject: str = ""
    blocking: bool = True
    risk: str = ""


@dataclass(slots=True)
class Context:
    """What retrieval and the graph established, before the model saw anything."""

    nodes: list[GraphNode] = field(default_factory=list)
    settled: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------- gathering


def request_text(db: Session, requirement: Requirement) -> str:
    """What the requirement is asking, as text to retrieve and reason over.

    Title and summary plus the requester's own turns. The assistant's turns are
    excluded deliberately: feeding Meridian's previous wording back in makes it
    progressively more confident about its own paraphrase rather than the
    request.
    """
    parts = [requirement.title, requirement.summary]
    parts.extend(
        m.content
        for m in sorted(requirement.messages, key=lambda m: m.at)
        if m.role == "user"
    )
    return "\n".join(p for p in parts if p)


def settled_decisions(db: Session, requirement_id: str) -> list[tuple[str, str]]:
    """Questions already answered, across every earlier assessment.

    This is what stops round three re-asking round one. An accepted unknown
    counts as settled — the requester decided to proceed without it, and
    re-raising it would be arguing with a decision that was recorded.
    """
    rows = db.execute(
        select(ClarificationQuestion)
        .join(FeasibilityAssessment)
        .where(FeasibilityAssessment.requirement_id == requirement_id)
        .order_by(ClarificationQuestion.position)
    ).scalars()

    out: list[tuple[str, str]] = []
    for q in rows:
        if q.accepted_unknown:
            out.append((q.text, "accepted as unknown by the requester"))
        elif q.answered_as:
            out.append((q.text, q.answered_as))
    return out


def gather(db: Session, requirement: Requirement, *, text: str) -> Context:
    """Retrieval plus prior answers. No model involved."""
    return Context(
        nodes=ask_agent.retrieve(
            db,
            text,
            workspace_id=requirement.workspace_id,
            limit=ask_agent.MAX_CONTEXT_NODES,
        ),
        settled=settled_decisions(db, requirement.id),
    )


# ------------------------------------------------------------ deterministic


def owning_connections(
    db: Session, nodes: list[GraphNode]
) -> tuple[dict[str, Connection], list[GraphNode]]:
    """Which connection owns each target node, and which nodes have no owner.

    Derived from `GraphNode.source_id`, because a change has to be made in the
    system the configuration came from. An orphaned node is not a small problem:
    it means Meridian knows a setting exists and cannot say where to change it.
    """
    by_source: dict[str, Connection] = {}
    orphans: list[GraphNode] = []

    source_ids = {n.source_id for n in nodes if n.source_id}
    if source_ids:
        for conn in db.execute(
            select(Connection).where(Connection.source_id.in_(source_ids))
        ).scalars():
            if conn.source_id:
                by_source[conn.source_id] = conn

    resolved: dict[str, Connection] = {}
    for node in nodes:
        conn = by_source.get(node.source_id or "")
        if conn is None:
            orphans.append(node)
        else:
            resolved[node.id] = conn
    return resolved, orphans


def access_gaps(
    intent: str, nodes: list[GraphNode], owners: dict[str, Connection], orphans: list[GraphNode]
) -> list[_Gap]:
    """Whether the change could actually be made, per owning system.

    Answered by asking each connector what it can do, never by consulting a
    table of assumptions kept here. Today every connector declares no
    operations, so every change is refused with the reason stated plainly — which
    is the correct answer while the platform is read-only, and becomes the
    correct answer again the moment a connector declares otherwise.
    """
    gaps: list[_Gap] = []

    for node in orphans:
        gaps.append(
            _Gap(
                kind=enums.GapKind.ACCESS,
                summary=(
                    f"No connected system owns {node.label!r}, so there is nowhere "
                    "to apply the change."
                ),
                remedy=(
                    "Re-extract the source that produced this node, or connect the "
                    "system that owns it."
                ),
                subject=node.id,
                risk=(
                    "Proceeding would mean changing something in a system Meridian "
                    "cannot identify, with no way to verify the change landed."
                ),
            )
        )

    # One gap per connection rather than per node: an administrator granting a
    # scope acts on a connection, and nine gaps naming the same missing scope
    # reads as nine problems.
    kinds_by_conn: dict[str, set[str]] = {}
    conn_by_id: dict[str, Connection] = {}
    for node in nodes:
        conn = owners.get(node.id)
        if conn is None:
            continue
        conn_by_id[conn.id] = conn
        kinds_by_conn.setdefault(conn.id, set()).add(node.kind)

    for conn_id, node_kinds in kinds_by_conn.items():
        conn = conn_by_id[conn_id]
        entry = registry.get(conn.connector_id)
        label = conn.label or conn.connector_id

        if entry is None:
            gaps.append(
                _Gap(
                    kind=enums.GapKind.ACCESS,
                    summary=f"{label} is not a connector this build knows about.",
                    remedy="Reconnect the system, or upgrade Meridian.",
                    subject=conn.id,
                    risk="Nothing can be verified about what this system permits.",
                )
            )
            continue

        connector = registry.build(conn.connector_id, {})
        for_kinds = [
            op
            for op in connector.operations
            if not op.node_kinds or node_kinds & set(op.node_kinds)
        ]

        # An unclear intent cannot be checked against a verb. What *is* knowable
        # is whether the system permits any change to these kinds at all, so that
        # much is reported and the rest waits for the intent.
        #
        # The alternative — checking against a guessed verb — produces a gap that
        # says "cannot modify" about a request that turns out to be a removal,
        # and sends someone to grant the wrong permission.
        if intent == enums.ChangeIntent.UNCLEAR:
            if not for_kinds:
                gaps.append(
                    _Gap(
                        kind=enums.GapKind.ACCESS,
                        summary=(
                            f"{label} declares no ability to change "
                            f"{', '.join(sorted(node_kinds))} at all. Meridian reads "
                            "this system; it cannot change it."
                        ),
                        remedy=(
                            "Apply the change in the source system and let Meridian "
                            "re-extract to confirm it, or enable write support for "
                            "this connector."
                        ),
                        subject=conn.id,
                        risk=(
                            "Meridian would have to claim a change it has no way to "
                            "make, and the approval record would say it did."
                        ),
                    )
                )
            continue

        usable = [op for op in for_kinds if intent in op.intents]

        if not usable:
            gaps.append(
                _Gap(
                    kind=enums.GapKind.ACCESS,
                    summary=(
                        f"{label} declares no ability to {intent} "
                        f"{', '.join(sorted(node_kinds))}. Meridian reads this system; "
                        "it cannot change it."
                    ),
                    remedy=(
                        "Apply the change in the source system and let Meridian "
                        "re-extract to confirm it, or enable write support for this "
                        "connector."
                    ),
                    subject=conn.id,
                    risk=(
                        "Meridian would have to claim a change it has no way to make, "
                        "and the approval record would say it did."
                    ),
                )
            )
            continue

        granted = set(conn.granted_scopes or [])
        for op in usable:
            missing = [s for s in op.requires_scopes if s not in granted]
            if missing:
                gaps.append(
                    _Gap(
                        kind=enums.GapKind.ACCESS,
                        summary=(
                            f"{label} is missing {', '.join(missing)}, which "
                            f"{op.label} requires."
                        ),
                        remedy=(
                            f"Grant {', '.join(missing)} on this connection, then "
                            "re-run the feasibility check."
                        ),
                        subject=conn.id,
                        risk=(
                            "The change would fail partway, leaving the source system "
                            "in a state nobody planned for."
                        ),
                    )
                )

    return gaps


def data_gaps(nodes: list[GraphNode]) -> list[_Gap]:
    """Whether there is anything to reason about at all."""
    if nodes:
        return []
    return [
        _Gap(
            kind=enums.GapKind.DATA,
            summary=(
                "Nothing in the knowledge graph matches this request, so there is "
                "no configuration to assess."
            ),
            remedy=(
                "Extract the system this change concerns, or rephrase the request "
                "using the names the configuration actually uses."
            ),
            risk=(
                "An impact analysis over an empty graph would find nothing affected "
                "and would look like a clean result."
            ),
        )
    ]


def freshness_gaps(db: Session, nodes: list[GraphNode]) -> list[_Gap]:
    """Whether the configuration is recent enough to change something against.

    Blocking, and that is a considered choice. Stale configuration does not fail
    loudly — it answers confidently from a tenant that has since moved on, and a
    change planned against it can overwrite something extracted before it
    existed. The remedy is a re-extraction, which is cheap; the failure is
    silent, which is not.
    """
    source_ids = {n.source_id for n in nodes if n.source_id}
    if not source_ids:
        return []

    now = utcnow()
    gaps: list[_Gap] = []
    for src in db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id.in_(source_ids))
    ).scalars():
        if src.last_synced_at is None:
            gaps.append(
                _Gap(
                    kind=enums.GapKind.FRESHNESS,
                    summary=f"{src.name} has never completed an extraction.",
                    remedy="Run an extraction for this source.",
                    subject=src.id,
                    risk=(
                        "Everything the graph holds for this source is unverified "
                        "against the live system."
                    ),
                )
            )
            continue

        age_days = (now - src.last_synced_at).days
        threshold = src.staleness_threshold_days or 7
        if age_days > threshold:
            gaps.append(
                _Gap(
                    kind=enums.GapKind.FRESHNESS,
                    summary=(
                        f"{src.name} was last extracted {age_days} days ago, past its "
                        f"{threshold}-day threshold."
                    ),
                    remedy="Re-extract this source, then re-run the feasibility check.",
                    subject=src.id,
                    risk=(
                        "The change would be planned against configuration that may "
                        "already have moved, and the plan would look sound."
                    ),
                )
            )
    return gaps


def understanding_gaps(intent: str, open_questions: int) -> list[_Gap]:
    """Whether anything material is still being guessed at."""
    gaps: list[_Gap] = []
    if intent == enums.ChangeIntent.UNCLEAR:
        gaps.append(
            _Gap(
                kind=enums.GapKind.UNDERSTANDING,
                summary="What kind of change this is has not been established yet.",
                remedy="Say whether this adds, changes, removes, or reduces something.",
                risk=(
                    "A removal planned as a modification leaves the old behaviour in "
                    "place and reports success."
                ),
            )
        )
    if open_questions:
        gaps.append(
            _Gap(
                kind=enums.GapKind.UNDERSTANDING,
                summary=(
                    f"{open_questions} question(s) about this change are unanswered."
                ),
                remedy="Answer them, or accept each as an explicit unknown.",
                risk=(
                    "Meridian would pick a reading of the request, and the approval "
                    "would cover the reading rather than the request."
                ),
            )
        )
    return gaps


def verdict_for(gaps: list[_Gap]) -> str:
    """The verdict, computed.

    BLOCKED outranks INCOMPLETE deliberately. When access or data is missing the
    change cannot proceed however thoroughly it is described, so asking the
    requester for more detail first wastes their time and reads as though the
    detail were the obstacle.
    """
    blocking = [g for g in gaps if g.blocking]
    if any(
        g.kind in {enums.GapKind.ACCESS, enums.GapKind.DATA, enums.GapKind.FRESHNESS}
        for g in blocking
    ):
        return enums.FeasibilityVerdict.BLOCKED
    if blocking:
        return enums.FeasibilityVerdict.INCOMPLETE
    return enums.FeasibilityVerdict.FEASIBLE


# ------------------------------------------------------------------- model


def _prompt(requirement: Requirement, text: str, ctx: Context, budget: int) -> str:
    nodes = [
        {
            "id": n.id,
            "label": n.label,
            "kind": n.kind,
            "description": n.description,
            "attributes": n.attributes or {},
        }
        for n in ctx.nodes[:MAX_TARGETS]
    ]
    return json.dumps(
        {
            "requirement": {"ref": requirement.ref, "title": requirement.title},
            "request": text,
            "retrievedConfiguration": nodes,
            "alreadySettled": [
                {"question": q, "answer": a} for q, a in ctx.settled
            ],
            "questionBudget": budget,
        },
        indent=2,
        default=str,
    )


def _stub_payload(ctx: Context) -> str:
    """Structurally valid output for when no model is configured.

    Intent is "unclear" and no questions are proposed, because nothing read the
    request. Targets are the strongest retrieved nodes, which is a claim
    retrieval genuinely made and not an inference. The result is an assessment
    that refuses to say the change is understood — the honest position when
    nothing has understood it.
    """
    return json.dumps(
        {
            "intent": enums.ChangeIntent.UNCLEAR.value,
            "understoodAs": (
                "No language model is configured, so the request has not been "
                "interpreted. The nodes listed are what retrieval matched."
            ),
            "targetNodeIds": [n.id for n in ctx.nodes[:3]],
            "questions": [],
            "budgetRequest": {"count": 0, "why": ""},
        }
    )


def _attribute_keys(nodes: list[GraphNode]) -> set[str]:
    keys: set[str] = set()
    for n in nodes:
        keys.update(str(k) for k in (n.attributes or {}))
    return keys


# ------------------------------------------------------------------ assess


def assess(
    db: Session,
    requirement: Requirement,
    *,
    text: str | None = None,
    question_budget: int = DEFAULT_QUESTION_BUDGET,
) -> FeasibilityAssessment:
    """Assess a requirement and record the result.

    Always produces an assessment, including when the answer is no. A refusal
    that leaves no row behind cannot be reviewed, and "why did it say no" is the
    question people will ask.
    """
    text = text if text is not None else request_text(db, requirement)
    ctx = gather(db, requirement, text=text)

    result = llm.complete(
        system=SYSTEM,
        prompt=_prompt(requirement, text, ctx, question_budget),
        max_tokens=2048,
        grounded_node_ids=[n.id for n in ctx.nodes],
        stub=_stub_payload(ctx),
    )
    record_cost(
        db,
        result,
        kind="feasibility",
        requirement_id=requirement.id,
        workspace_id=requirement.workspace_id,
        detail=f"Feasibility assessment for {requirement.ref}.",
    )

    parsed = extract_json(result.text) or {}
    discarded: list[dict] = []

    intent = parsed.get("intent")
    if intent not in {i.value for i in enums.ChangeIntent}:
        if intent is not None:
            discarded.append({"reason": "unknown intent", "value": str(intent)})
        intent = enums.ChangeIntent.UNCLEAR.value

    # Targets are filtered to what retrieval actually returned. A nominated id
    # that was never in the input is a fabrication, and a fabricated *target* is
    # worse than a fabricated citation: it is the thing the change would be
    # applied to.
    retrieved = {n.id: n for n in ctx.nodes}
    targets: list[GraphNode] = []
    for nid in parsed.get("targetNodeIds") or []:
        node = retrieved.get(nid)
        if node is None:
            discarded.append({"reason": "target not retrieved", "value": str(nid)})
        elif node not in targets:
            targets.append(node)

    # Budget adjustment. Permitted, bounded, and recorded — an adjustment nobody
    # can see afterwards is indistinguishable from having no ceiling at all.
    budget = question_budget
    raised_to: int | None = None
    reason = ""
    ask = parsed.get("budgetRequest") or {}
    wanted = ask.get("count")
    why = str(ask.get("why") or "").strip()
    if isinstance(wanted, int) and wanted > budget and why:
        raised_to = min(wanted, HARD_QUESTION_CEILING)
        budget = raised_to
        reason = why
        if wanted > HARD_QUESTION_CEILING:
            discarded.append(
                {
                    "reason": "budget request above ceiling",
                    "value": f"asked {wanted}, capped at {HARD_QUESTION_CEILING}",
                }
            )

    allowed_about = set(retrieved) | _attribute_keys(ctx.nodes)
    settled_texts = {q.strip().lower() for q, _ in ctx.settled}
    questions: list[ClarificationQuestion] = []
    for raw in parsed.get("questions") or []:
        if not isinstance(raw, dict):
            continue
        q_text = str(raw.get("text") or "").strip()
        about = str(raw.get("about") or "").strip()
        if not q_text:
            continue
        if about and about not in allowed_about:
            discarded.append({"reason": "question about unknown subject", "value": q_text})
            continue
        if q_text.strip().lower() in settled_texts:
            discarded.append({"reason": "already settled", "value": q_text})
            continue
        if len(questions) >= budget:
            discarded.append({"reason": "over question budget", "value": q_text})
            continue
        options = [str(o) for o in (raw.get("options") or []) if str(o).strip()]
        questions.append(
            ClarificationQuestion(
                id=new_id("cq"),
                text=q_text,
                rationale=str(raw.get("rationale") or ""),
                options=options,
                about=about,
                position=len(questions),
            )
        )

    owners, orphans = owning_connections(db, targets)
    gaps: list[_Gap] = [
        *data_gaps(ctx.nodes),
        *understanding_gaps(intent, len(questions)),
        *freshness_gaps(db, targets),
        *access_gaps(intent, targets, owners, orphans),
    ]

    assessment = FeasibilityAssessment(
        id=new_id("feas"),
        requirement_id=requirement.id,
        workspace_id=requirement.workspace_id,
        assessed_at=utcnow(),
        intent=intent,
        verdict=verdict_for(gaps),
        understood_as=str(parsed.get("understoodAs") or ""),
        target_node_ids=[n.id for n in targets],
        owning_connection_ids=sorted({c.id for c in owners.values()}),
        question_budget=question_budget,
        budget_raised_to=raised_to,
        budget_reason=reason,
        model=result.model,
        model_version=result.model_version,
        cost_usd=result.cost_usd,
        source=result.source,
        discarded=discarded,
    )
    db.add(assessment)
    db.flush()

    for position, gap in enumerate(gaps):
        db.add(
            FeasibilityGap(
                id=new_id("fgap"),
                assessment_id=assessment.id,
                kind=gap.kind,
                summary=gap.summary,
                remedy=gap.remedy,
                subject=gap.subject,
                blocking=gap.blocking,
                risk=gap.risk,
                position=position,
            )
        )
    for question in questions:
        question.assessment_id = assessment.id
        db.add(question)

    db.flush()
    db.refresh(assessment)
    return assessment


def latest(db: Session, requirement_id: str) -> FeasibilityAssessment | None:
    """The most recent assessment for a requirement, or None."""
    return db.execute(
        select(FeasibilityAssessment)
        .where(FeasibilityAssessment.requirement_id == requirement_id)
        .order_by(FeasibilityAssessment.assessed_at.desc())
        .limit(1)
    ).scalar_one_or_none()

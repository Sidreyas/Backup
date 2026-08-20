"""
Requirements, discussion threads and impact analysis.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.agents import ask as ask_agent
from api.agents import feasibility as feasibility_agent
from api.agents import impact as impact_agent
from api.agents.llm import llm, record_cost
from api.core.db import get_db
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.feasibility import ClarificationQuestion
from api.domain.models import ChatMessage, ImpactAnalysis, Requirement
from api.graph import queries
from api.ledger import chain
from api.routers.deps import Actor, current_actor, current_workspace
from api.services import gate
from api.schemas import wire

router = APIRouter(tags=["requirements"])


class CreateRequirement(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str = ""
    platform: str = ""
    systemKind: str = enums.SystemKind.VENDOR_PLATFORM
    priority: str = enums.Criticality.MEDIUM


class StageChange(BaseModel):
    stage: str
    reason: str | None = None


#: Openers, courtesies and meta-questions. Matched whole, not as substrings —
#: "thanks" is small talk, "what does the thanks-giving holiday plan accrue"
#: is not.
_SMALL_TALK = frozenset(
    {
        "hi", "hey", "hello", "yo", "hiya", "howdy",
        "thanks", "thank", "ty", "cheers", "thx",
        "ok", "okay", "cool", "nice", "great", "good", "sure", "yes", "no",
        "morning", "afternoon", "evening", "there", "you", "how", "are",
        "what", "can", "do", "help", "who", "your", "name", "hows", "it",
        "going", "please", "sorry", "bye", "test", "testing",
    }
)

#: Words that mean the message is about the customer's systems, however short
#: it is. "test coverage?" is two words and is not small talk.
_DOMAIN_HINT = re.compile(
    r"\b(config|configuration|approval|workflow|process|rule|field|leave|"
    r"absence|accrual|entitlement|plan|policy|integration|report|security|"
    r"coverage|impact|change|test|risk|tenant|workday|graph)\w*\b",
    re.IGNORECASE,
)


def _is_small_talk(text: str) -> bool:
    """Whether a message asks nothing about the customer's configuration.

    Retrieval is the expensive, slow part of a turn and grounding rules make
    the assistant answer like a database. Both are right for a question about
    a tenant and wrong for "hi" — which used to be answered with "I don't have
    any relevant configuration data for MER-1003 in the knowledge graph".

    Deliberately conservative: a message is small talk only when it is short
    *and* every word is a courtesy *and* it contains no domain vocabulary.
    Misclassifying a real question as chit-chat would drop its grounding, so
    the failure this guards against is the more damaging direction.
    """
    stripped = text.strip().lower()
    if not stripped:
        return True
    if _DOMAIN_HINT.search(stripped):
        return False

    words = re.findall(r"[a-z']+", stripped)
    if not words or len(words) > 6:
        return False
    return all(word in _SMALL_TALK for word in words)


class SendMessage(BaseModel):
    text: str = Field(min_length=1)


@router.get("/requirements")
def list_requirements(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Requirement).order_by(Requirement.updated_at.desc())
    ).scalars()
    return [wire.requirement(r) for r in rows]


@router.get("/requirements/{requirement_id}")
def get_requirement(requirement_id: str, db: Session = Depends(get_db)) -> dict | None:
    r = db.get(Requirement, requirement_id)
    return wire.requirement(r) if r else None


@router.post("/requirements", status_code=201)
def create_requirement(
    body: CreateRequirement,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Create a requirement and open its discussion.

    The thread starts empty. Nothing is said on the requirement's behalf before
    anyone has asked anything — and in particular no impact analysis is
    implied, because the analysis endpoint exists precisely so that step is
    explicit and grounded.
    """
    highest = db.execute(select(func.count()).select_from(Requirement)).scalar_one()
    now = utcnow()

    requirement = Requirement(
        id=new_id("req"),
        workspace_id=workspace_id,
        ref=f"MER-{1000 + highest + 1}",
        title=body.title,
        summary=body.summary or body.title,
        # In discussion — nothing has been analysed yet.
        stage=enums.RequirementStage.DISCUSSING,
        requested_by=actor.name,
        requested_by_role=actor.role,
        platform=body.platform,
        system_kind=body.systemKind,
        priority=body.priority,
        # Nothing is claimed impacted until the graph has been consulted.
        impacted_node_ids=[],
        estimated_cost_usd=0.0,
        actual_cost_usd=0.0,
        risk_level=enums.Criticality.MEDIUM,
    )
    db.add(requirement)
    db.flush()

    # A new requirement starts with an empty thread.
    #
    # This used to seed two turns: the title echoed back as though the user had
    # typed it, and a fixed assistant reply asking which population is
    # affected. Both were removed. The echo restates what is already in the
    # header above the thread, and the reply was hardcoded prose wearing the
    # assistant's name — it cited nothing, cost nothing, and consulted no
    # graph, while looking exactly like a grounded turn. On a product whose
    # claim is that every answer is grounded, a canned opener is the wrong
    # first impression.
    #
    # The empty state on the chat page already explains what to ask.

    chain.append(
        db,
        chain.RecordInput(
            action="requirement.created",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=requirement.ref,
            summary=(
                f"Requirement raised against {body.platform or 'an unnamed system'} "
                f"at {body.priority} priority."
            ),
            duration_seconds=45,
            workspace_id=workspace_id,
        ),
    )

    db.commit()
    return wire.requirement(requirement)


@router.patch("/requirements/{requirement_id}/stage")
def set_stage(
    requirement_id: str,
    body: StageChange,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")
    if body.stage not in {s.value for s in enums.RequirementStage}:
        raise HTTPException(status_code=422, detail=f"Unknown stage: {body.stage}")

    # Acting stages are gated on a recorded feasibility verdict. 409 rather than
    # 403: nothing is forbidden about the request, the requirement is in the wrong
    # state for it, and the response body says exactly what would have to change.
    #
    # There is no force parameter, deliberately. See api/services/gate.py.
    try:
        gate.require_feasible(db, requirement, body.stage)
    except gate.NotFeasible as refusal:
        raise HTTPException(status_code=409, detail=refusal.detail()) from refusal

    before = requirement.stage
    requirement.stage = body.stage
    requirement.updated_at = utcnow()

    chain.append(
        db,
        chain.RecordInput(
            action="requirement.stage_changed",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=requirement.ref,
            summary=f"Stage moved from {before} to {body.stage}.",
            changes=[
                {"field": "stage", "label": "Stage", "before": before, "after": body.stage}
            ],
            reason=body.reason,
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    return wire.requirement(requirement)


@router.get("/requirements/{requirement_id}/thread")
def get_thread(requirement_id: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.requirement_id == requirement_id)
        .order_by(ChatMessage.at)
    ).scalars()
    return [wire.chat_message(m) for m in rows]


@router.post("/requirements/{requirement_id}/messages")
def send_message(
    requirement_id: str,
    body: SendMessage,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """One grounded assistant turn.

    Grounding is real: the graph is searched for nodes relevant to the message
    and those nodes — and only those — are given to the model as context and
    returned as citations. A citation to a node the model was never shown would
    be a fabrication, so the citation list is built from the retrieval, not
    from the reply.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")

    now = utcnow()
    db.add(
        ChatMessage(
            id=new_id("m"),
            requirement_id=requirement_id,
            role="user",
            content=body.text,
            at=now,
        )
    )

    conversational = _is_small_talk(body.text)

    # `ask_agent.retrieve`, not `queries.search` directly.
    #
    # `search` matches its argument as one literal substring, so passing a
    # whole question asked the graph for a node whose label contains
    # "What is the Hong Kong annual leave entitlement?" — which is nothing,
    # always. Chat therefore grounded on zero nodes and answered "the
    # configuration context does not contain any information about..." for
    # data that was sitting in the graph.
    #
    # `retrieve` splits the question into terms, searches each, and ranks by
    # how many matched. It is the same retrieval `/api/ask` uses, so the two
    # surfaces now answer the same question the same way.
    grounding = (
        []
        if conversational
        # Same budget as `/api/ask`. The hardcoded 8 here silently truncated:
        # a question about HKG annual leave retrieved ten relevant nodes and
        # dropped the two that ranked lowest — one of which was the eligibility
        # rule that says *who the plan applies to*, the exact thing being
        # asked. Two surfaces answering the same question from different
        # amounts of evidence is its own defect.
        else ask_agent.retrieve(
            db,
            body.text,
            workspace_id=workspace_id,
            limit=ask_agent.MAX_CONTEXT_NODES,
        )
    )
    if not conversational and not grounding and requirement.impacted_node_ids:
        from api.domain.models import GraphNode

        grounding = list(
            db.execute(
                select(GraphNode).where(GraphNode.id.in_(requirement.impacted_node_ids))
            ).scalars()
        )

    # Attributes are the substance. Connectors store what a node *means*
    # there — a plan's summary, a lookup table's bands, a calculation's
    # branches — while `description` is usually empty.
    #
    # Sending label/kind/provenance alone produced answers that named every
    # right object and then said "the configuration does not contain any
    # descriptive details, such as the number of days" — for a plan whose
    # stored summary reads "7 Days rising to 14 Days, by worker years of
    # service". Correct given what it was shown, and useless.
    #
    # Serialised as JSON, matching `/api/ask`: attribute values are nested
    # (bands are a list of objects), and flattening them into prose loses the
    # structure the model needs to read a table.
    context = json.dumps(
        [
            {
                "id": n.id,
                "label": n.label,
                "kind": n.kind,
                "provenance": n.provenance or "",
                "description": n.description or "",
                "attributes": n.attributes or {},
            }
            for n in grounding
        ],
        indent=2,
        default=str,
    ) if grounding else "(the graph returned nothing relevant to this question)"

    # Two modes, because "hi" and "which approvals does this touch" are not
    # the same request.
    #
    # Every message used to be treated as a configuration question and answered
    # under the grounding rules, so "Hi" was met with "I don't have any relevant
    # configuration data for MER-1003 in the knowledge graph" — technically
    # true, conversationally absurd, and it teaches people the assistant does
    # not understand them.
    #
    # The grounding discipline is not relaxed here: the conversational mode is
    # only ever entered for messages that ask nothing about configuration, and
    # it is explicitly forbidden from making claims about the tenant. Anything
    # substantive still goes through retrieval and still answers only from what
    # was found.
    if conversational:
        system = (
            "You are Meridian's requirements assistant for enterprise change "
            "governance. The user has said something conversational rather than "
            "asked about their configuration. Reply briefly and warmly in one or "
            "two sentences, and offer what you can help with: what a proposed "
            "change would touch, which approval chains depend on an object, "
            "what has no test coverage, and how a rule is configured. "
            "Do NOT state any fact about their systems, data, or configuration "
            "— you have not looked anything up. Do not mention the knowledge "
            "graph, indexing, or missing data."
        )
    else:
        system = (
            "You are the requirements assistant of an enterprise change governance "
            "platform. Answer using only the configuration context provided. "
            "If the context does not answer the question, say so plainly and name what "
            "would need to be connected or indexed. Never invent a configuration "
            "object, a field, or an approval rule. Disagree explicitly when the "
            "proposed change conflicts with what the context shows.\n\n"
            # Shape follows the question. Without this the model defaults to a
            # heading-and-bullets report for everything, so "who does this
            # apply to" — a one-sentence answer — arrived as a formatted
            # document with a single line inside it.
            "Match the shape of your answer to the question. A narrow question "
            "gets one or two sentences with no headings. A question asking for "
            "an explanation or a walkthrough gets short sections. Use a table "
            "only for genuinely tabular data such as service bands or step "
            "sequences, and never for two or three values. Do not restate the "
            "question, and do not open with 'Based on the configuration "
            "context' — the sources are already shown beside your answer.\n\n"
            "Write for a business reader: name configuration objects the way "
            "the tenant names them, and explain what a rule does rather than "
            "quoting its internal identifier unless asked."
        )

    prompt = (
        f"MESSAGE FROM THE USER\n{body.text}"
        if conversational
        else (
            f"REQUIREMENT {requirement.ref}: {requirement.title}\n"
            f"{requirement.summary}\n\n"
            f"CONFIGURATION CONTEXT FROM THE KNOWLEDGE GRAPH\n{context}\n\n"
            f"QUESTION FROM THE USER\n{body.text}"
        )
    )

    result = llm.complete(
        system=system,
        prompt=prompt,
        max_tokens=2000,
        grounded_node_ids=[n.id for n in grounding],
        stub=(
            "No language model is configured, so this turn was not generated. "
            f"The graph returned {len(grounding)} node(s) relevant to your question; "
            "they are cited below so the retrieval is still inspectable."
        ),
    )
    record_cost(
        db,
        result,
        kind="chat_turn",
        requirement_id=requirement_id,
        workspace_id=workspace_id,
        detail=f"Assistant turn on {requirement.ref}.",
    )

    message = ChatMessage(
        id=new_id("m"),
        requirement_id=requirement_id,
        role="assistant",
        content=result.text,
        at=utcnow(),
        # Citations come from what was retrieved, never from what the model
        # claimed to have used.
        citations=[
            {
                "nodeId": n.id,
                "label": n.label,
                "provenance": n.provenance,
                "confidence": enums.LinkConfidence.CONFIRMED
                if n.last_verified_at
                else enums.LinkConfidence.MEDIUM,
            }
            for n in grounding
        ],
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        model=result.model,
    )
    db.add(message)

    requirement.actual_cost_usd = round(
        requirement.actual_cost_usd + result.cost_usd, 6
    )

    chain.append(
        db,
        chain.RecordInput(
            action="requirement.discussed",
            actor=f"{result.model} · advisory",
            actor_type=enums.ActorType.AGENT,
            requirement_ref=requirement.ref,
            summary=(
                f"Assistant turn grounded against {len(grounding)} graph node(s)."
                + ("" if result.source == "llm" else " No model configured; stub reply.")
            ),
            cost_usd=result.cost_usd,
            ai=result.provenance(),
            workspace_id=workspace_id,
        ),
    )

    db.commit()
    return wire.chat_message(message)


class AssessRequest(BaseModel):
    """Optional overrides for a feasibility run."""

    text: str | None = None
    #: Questions this round. Raising it here is the operator's lever; the agent
    #: has its own, bounded lever and has to justify using it.
    questionBudget: int = Field(
        default=feasibility_agent.DEFAULT_QUESTION_BUDGET, ge=1, le=feasibility_agent.HARD_QUESTION_CEILING
    )


class AnswerRequest(BaseModel):
    """An answer to one clarification question, or an accepted unknown."""

    answer: str | None = None
    acceptUnknown: bool = False


@router.get("/requirements/{requirement_id}/feasibility")
def get_feasibility(requirement_id: str, db: Session = Depends(get_db)) -> dict | None:
    assessment = feasibility_agent.latest(db, requirement_id)
    return wire.feasibility_assessment(assessment) if assessment else None


@router.post("/requirements/{requirement_id}/feasibility", status_code=201)
def assess_feasibility(
    requirement_id: str,
    body: AssessRequest | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Assess whether a requirement can be acted on.

    Always writes an assessment, including when the answer is no. A refusal with
    no row behind it cannot be reviewed, and "why did it say no" is the first
    thing anyone asks.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")

    body = body or AssessRequest()
    assessment = feasibility_agent.assess(
        db,
        requirement,
        text=body.text,
        question_budget=body.questionBudget,
    )

    chain.append(
        db,
        chain.RecordInput(
            action="requirement.feasibility_assessed",
            actor=actor.name,
            actor_type=enums.ActorType.AGENT,
            requirement_ref=requirement.ref,
            summary=(
                f"Feasibility: {assessment.verdict} "
                f"({len(assessment.blocking_gaps)} blocking gap(s), "
                f"{len(assessment.questions)} question(s))."
            ),
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    db.refresh(assessment)
    return wire.feasibility_assessment(assessment)


@router.post("/requirements/{requirement_id}/questions/{question_id}")
def answer_question(
    requirement_id: str,
    question_id: str,
    body: AnswerRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Answer a clarification question, or accept it as an unknown.

    Answering does not re-assess. The verdict is a recorded claim, and the next
    assessment is an explicit act — otherwise a requester clicking through four
    options would trigger four model calls and four rows, three of which nobody
    asked for.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")

    question = db.get(ClarificationQuestion, question_id)
    if question is None or question.assessment.requirement_id != requirement_id:
        raise HTTPException(status_code=404, detail="Question not found")

    answer = (body.answer or "").strip()
    if not answer and not body.acceptUnknown:
        raise HTTPException(
            status_code=422,
            detail="Provide an answer, or set acceptUnknown to proceed without one.",
        )

    question.answered_as = answer or None
    question.accepted_unknown = body.acceptUnknown and not answer
    question.answered_at = utcnow()

    chain.append(
        db,
        chain.RecordInput(
            action="requirement.question_answered",
            actor=actor.name,
            actor_type=enums.ActorType.HUMAN,
            requirement_ref=requirement.ref,
            summary=(
                f"Accepted as unknown: {question.text}"
                if question.accepted_unknown
                else f"Answered: {question.text}"
            ),
            changes=[
                {
                    "field": "answer",
                    "label": question.text,
                    "before": None,
                    "after": answer or "(accepted as unknown)",
                }
            ],
            workspace_id=workspace_id,
        ),
    )
    db.commit()
    db.refresh(question)
    return wire.feasibility_assessment(question.assessment)


@router.get("/impact")
def list_impact(db: Session = Depends(get_db)) -> list[dict]:
    """Every analysis that exists. A requirement still in discussion has none."""
    rows = db.execute(
        select(ImpactAnalysis).order_by(ImpactAnalysis.generated_at.desc())
    ).scalars()
    return [wire.impact_analysis(a) for a in rows]


@router.get("/requirements/{requirement_id}/impact")
def get_impact(requirement_id: str, db: Session = Depends(get_db)) -> dict | None:
    analysis = db.execute(
        select(ImpactAnalysis)
        .where(ImpactAnalysis.requirement_id == requirement_id)
        .order_by(ImpactAnalysis.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return wire.impact_analysis(analysis) if analysis else None


class GenerateImpact(BaseModel):
    seedNodeIds: list[str] | None = None
    maxDepth: int = Field(default=3, ge=1, le=6)


@router.post("/requirements/{requirement_id}/impact")
def generate_impact(
    requirement_id: str,
    body: GenerateImpact,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> dict:
    """Run impact analysis: graph traversal first, model assessment second."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found")

    if body.seedNodeIds is not None:
        requirement.impacted_node_ids = body.seedNodeIds

    analysis = impact_agent.generate(
        db,
        requirement,
        seed_node_ids=body.seedNodeIds,
        max_depth=body.maxDepth,
    )

    breaking = sum(
        1 for i in analysis.items if i.severity == enums.ImpactSeverity.BREAKING
    )
    gaps = sum(1 for i in analysis.items if i.coverage_gap)

    chain.append(
        db,
        chain.RecordInput(
            action="impact.generated",
            actor=f"{analysis.model} · impact engine",
            actor_type=enums.ActorType.AGENT,
            requirement_ref=requirement.ref,
            summary=(
                f"Impact analysis over {len(analysis.items)} node(s) — "
                f"{breaking} breaking, {gaps} without test coverage."
                + ("" if analysis.source == "llm" else " No model configured; nodes unassessed.")
            ),
            cost_usd=analysis.cost_usd,
            duration_seconds=analysis.duration_seconds,
            ai={
                "model": analysis.model,
                "modelVersion": analysis.model_version,
                "promptHash": "",
                "tokensIn": 0,
                "tokensOut": 0,
                "temperature": 0.2,
                "groundedNodeIds": [i.node_id for i in analysis.items],
            },
            workspace_id=workspace_id,
        ),
    )

    db.commit()
    return wire.impact_analysis(analysis)

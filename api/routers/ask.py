"""
The question endpoint.

The chat surface over the knowledge graph. Everything else in Meridian
extracts; this is where that work becomes usable to someone who does not know
what a business process definition is.

Answers are grounded in extracted nodes and cite them, so a reader can check
the claim against its source. `answers.grounded` being false is meaningful and
surfaced rather than hidden: it means retrieval found nothing, and the honest
response is to say the graph does not cover the question rather than to
improvise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.agents import ask as ask_agent
from api.core.db import get_db
from api.routers.deps import Actor, current_actor, current_workspace

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CitedNode(BaseModel):
    id: str
    label: str
    kind: str
    key: str | None = None
    provenance: str = ""


class AskResponse(BaseModel):
    question: str
    answer: str
    grounded: bool
    cited: list[CitedNode]
    #: How many nodes retrieval considered, as against how many the answer
    #: cites. A large gap is a signal the question was vague.
    consideredCount: int
    gaps: list[str]
    #: Node ids the model claimed but which were not in its input. Non-empty
    #: means a fabricated citation was caught and dropped; it is reported
    #: rather than swallowed because it is exactly the kind of event the AI
    #: incident register exists for.
    fabricatedCitations: list[str]
    provenance: dict


@router.post("/ask", response_model=AskResponse)
def post_ask(
    body: AskRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    workspace_id: str = Depends(current_workspace),
) -> AskResponse:
    answer = ask_agent.ask(
        db, body.question, workspace_id=workspace_id, actor=actor.email
    )

    # `ask` records what the question cost. Nothing else here writes, so
    # without this commit the row is discarded when the request ends and the
    # spend never appears — every question answered, every dashboard reading
    # zero. Other routes that call `record_cost` happen to commit for their own
    # reasons; this one has no other reason, which is why it was missing.
    db.commit()

    return AskResponse(
        question=answer.question,
        answer=answer.text,
        grounded=answer.grounded,
        cited=[
            CitedNode(
                id=node.id,
                label=node.label,
                kind=node.kind,
                key=node.natural_key,
                provenance=node.provenance or "",
            )
            for node in answer.cited
        ],
        consideredCount=len(answer.considered),
        gaps=answer.gaps,
        fabricatedCitations=answer.fabricated,
        provenance=answer.provenance,
    )

"""
Answering questions from the graph.

The chat surface, and the thing that makes the extraction worth doing. A user
asks "how much annual leave do Hong Kong staff get" or "what breaks if I change
the UK FTE calculation", and the answer comes from what Meridian extracted —
not from what a model remembers about Workday.

The division is the same one `impact.py` makes, for the same reason:

    retrieval is deterministic  ·  the model only explains what retrieval found

A model asked a question about a customer's tenant will answer it. Fluently,
plausibly, and from its training data — which describes *Workday in general*,
not *this tenant*. The resulting sentence is indistinguishable from a real
answer and wrong in a way nobody can check. So the model here never sees the
question without evidence attached, and every claim it makes is expected to
cite a node id that was in its input. Citations that were not are dropped and
the drop is reported.

Retrieval is three passes, cheapest first:

  1. **Direct match** on label and natural key.
  2. **Neighbourhood expansion** — the matched nodes plus what they reach.
     A question about a plan is usually a question about its accruals, and
     an answer that stopped at the plan node would be technically grounded and
     practically useless.
  3. **Kind filtering** when the question names a category ("which lookup
     tables", "what plans").

Deliberately not embeddings. `search()` is ILIKE today, and swapping in pgvector
changes one function; building the whole answer path on a retrieval method that
does not exist yet would mean neither works.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from api.agents.llm import extract_json, llm, record_cost
from api.domain.models import GraphNode
from api.graph import queries

#: How many nodes reach the model. A large context is not a better answer:
#: past a point the model starts summarising the context rather than answering
#: the question, and every extra node is tokens spent on something the user did
#: not ask about.
MAX_CONTEXT_NODES = 40

#: Neighbourhood depth. Two hops reaches plan → accrual → calculation, which is
#: the chain the client's own question needs. Three pulls in most of a tenant.
NEIGHBOUR_DEPTH = 2

#: Slack for neighbours beyond what the question matched directly.
#:
#: Small on purpose. A question that matched two nodes wants the handful of
#: things they connect to — the calculation behind an accrual, the org a plan
#: is scoped to — not forty. Without a cap of this shape the expansion simply
#: refills every slot the relevance filter emptied, and the filter stops
#: meaning anything.
NEIGHBOUR_ALLOWANCE = 4

#: Words that carry no retrieval signal. Kept short deliberately — an
#: aggressive stoplist strips the domain nouns that make a query work.
_NOISE = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "do", "does", "did",
        "what", "which", "who", "when", "where", "why", "how", "much", "many",
        "of", "for", "to", "in", "on", "at", "by", "with", "and", "or", "not",
        "i", "we", "you", "it", "they", "me", "my", "our", "if", "can", "will",
        "would", "should", "there", "that", "this", "these", "those", "get",
        "gets", "have", "has", "had", "be", "been", "about", "from", "into",
    }
)


@dataclass(slots=True)
class Answer:
    """A grounded answer, with everything needed to check it."""

    question: str
    text: str
    #: Nodes the answer is based on, in the order retrieval ranked them.
    cited: list[GraphNode] = field(default_factory=list)
    considered: list[GraphNode] = field(default_factory=list)
    #: Node ids the model cited that were not in its input. Always empty in a
    #: correct run; non-empty means the model invented a citation, which is
    #: recorded rather than quietly dropped.
    fabricated: list[str] = field(default_factory=list)
    #: What the graph does not know that bears on this question. Computed, not
    #: asked of the model.
    gaps: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    @property
    def grounded(self) -> bool:
        return bool(self.cited)


def terms(question: str) -> list[str]:
    """Retrieval terms from a natural-language question.

    Quoted phrases are kept whole — `"GBR Statutory Holiday"` should match as
    one thing rather than three common words.
    """
    phrases = re.findall(r'"([^"]+)"', question)
    rest = re.sub(r'"[^"]+"', " ", question)
    words = [
        word
        for word in re.findall(r"[A-Za-z0-9_%()-]+", rest)
        if len(word) > 2 and word.lower() not in _NOISE
    ]
    # Longest first: a distinctive term is a better first query than a common
    # one, and retrieval stops early once it has enough.
    return phrases + sorted(set(words), key=len, reverse=True)


def retrieve(
    db: Session,
    question: str,
    *,
    workspace_id: str | None = None,
    limit: int = MAX_CONTEXT_NODES,
) -> list[GraphNode]:
    """Nodes that bear on the question, most relevant first.

    Ranking is by how the node was found — a direct label match outranks a
    node reached by traversal — because a two-hop neighbour is context, not
    an answer.
    """
    query_terms = terms(question)
    seen: dict[str, GraphNode] = {}
    hits: dict[str, int] = {}

    for term in query_terms:
        for node in queries.search(db, term, workspace_id=workspace_id, limit=limit):
            seen.setdefault(node.id, node)
            hits[node.id] = hits.get(node.id, 0) + 1

    if not seen:
        return []

    # Rank by how many of the question's terms a node matched, not by which
    # term happened to be searched first.
    #
    # Without this, "what breaks if I change the HKG Annual Leave Days
    # Entitlement calculation" retrieved every node containing "leave" — the
    # whole GBR plan and a seeded payroll integration — with the same standing
    # as the one node the question names. The model then cited them, correctly
    # by its own rules, and produced an answer about integrations nobody asked
    # about. Precision here is what stops a grounded answer being a misleading
    # one.
    ordered = sorted(
        seen.values(),
        key=lambda n: (-hits[n.id], len(n.label or "")),
    )

    # How many nodes are *relevant* is a property of the question, not a
    # constant. "Hong Kong" has three answers; "what leave plans do we have"
    # has four; "what breaks if I change this" can have twenty. Returning a
    # fixed number pads a narrow question with noise and truncates a broad one
    # — and the padding is the more damaging half, because a model given a
    # weakly-related node will dutifully write about it.
    #
    # Relevance is judged relative to the best match rather than absolutely.
    # Asking about "the HKG annual leave entitlement" matches four terms on
    # the node that answers it and one term — "leave" — on five GBR nodes that
    # do not. That is a cliff, not a gradient, and cutting at it is what stops
    # an answer about Hong Kong citing British statutory holiday.
    #
    # A node still has to clear half the best score, so a single shared common
    # word never survives beside a four-term match.
    best = hits[ordered[0].id]
    floor = max(1, (best + 1) // 2)
    ordered = [n for n in ordered if hits[n.id] >= floor]

    # Expand from the strongest matches only. Expanding from everything turns
    # a vague question into most of the graph.
    #
    # The expansion is bounded *relative to what matched*, not to `limit`:
    # filling every remaining slot with neighbours undoes the relevance cut
    # above, because a question that legitimately matched three nodes would be
    # padded back to forty with whatever happens to sit near them. Neighbours
    # are context for an answer, so a handful per direct match is the right
    # order of magnitude.
    seeds = [n.id for n in ordered[:5]]
    ceiling = min(limit, len(ordered) * 2 + NEIGHBOUR_ALLOWANCE)
    for reached in queries.neighbours(
        db,
        seeds,
        max_depth=NEIGHBOUR_DEPTH,
        min_confidence="low",
        workspace_id=workspace_id,
    ):
        if len(ordered) >= ceiling:
            break
        if reached.node.id not in seen:
            seen[reached.node.id] = reached.node
            ordered.append(reached.node)

    return ordered[:limit]


def _node_context(node: GraphNode) -> dict:
    """One node as the model sees it.

    Attributes are included because they hold the answer: the lookup table's
    bands, the calculation's branches, the plan's carryover. A context of
    labels alone would let the model name the right node and still invent its
    contents.
    """
    return {
        "id": node.id,
        "label": node.label,
        "kind": node.kind,
        "key": node.natural_key,
        "description": node.description or "",
        "provenance": node.provenance or "",
        "attributes": node.attributes or {},
    }


def _gaps(nodes: list[GraphNode]) -> list[str]:
    """What the graph admits it does not know, among these nodes.

    Read off the `resolved` flag connectors set on an unvisited reference.
    Stated in the answer so a user is never left believing a partial extraction
    was a complete one.
    """
    return [
        f"'{node.label}' is referenced but has not been extracted yet"
        for node in nodes
        if (node.attributes or {}).get("resolved") is False
    ]


SYSTEM = """You answer questions about a customer's enterprise configuration.

You are given nodes extracted from that customer's actual systems. Answer ONLY
from them. You have general knowledge about platforms like Workday; do not use
it here, because the question is about how THIS customer is configured and your
general knowledge describes something else.

Rules:
- Every factual claim must come from the supplied nodes.
- Cite the node ids you used.
- If the nodes do not answer the question, say so plainly and say what is
  missing. A short honest answer is worth more than a long plausible one.
- Quantities must carry their unit. "28" is not an answer; "28 days" is.
- Write for a business reader: no ids, no internal keys, no jargon in the prose.

Return JSON only:
{"answer": "<plain language>", "cited": ["<node id>", ...],
 "confident": true|false}"""


def ask(
    db: Session,
    question: str,
    *,
    workspace_id: str | None = None,
    actor: str = "user",
) -> Answer:
    """Answer a question from the graph."""
    question = (question or "").strip()
    if not question:
        return Answer(
            question="",
            text="Ask a question and I will answer it from what Meridian has extracted.",
        )

    considered = retrieve(db, question, workspace_id=workspace_id)
    if not considered:
        # No retrieval, no answer. The model is never given a chance to answer
        # from memory — that is the single most likely way this feature would
        # produce a confident description of a tenant nobody extracted.
        return Answer(
            question=question,
            text=(
                "Nothing in the extracted configuration matches that question. "
                "Either the source has not been connected yet, or the extraction "
                "has not reached it."
            ),
            gaps=["no matching nodes in the graph"],
        )

    context = [_node_context(node) for node in considered]
    prompt = (
        f"Question: {question}\n\n"
        f"Nodes extracted from the customer's systems:\n"
        f"{json.dumps(context, indent=2, default=str)}"
    )

    by_id = {node.id: node for node in considered}
    result = llm.complete(
        system=SYSTEM,
        prompt=prompt,
        grounded_node_ids=list(by_id),
        stub=json.dumps(
            {
                "answer": _stub_answer(question, considered),
                "cited": [n.id for n in considered[:5]],
                "confident": False,
            }
        ),
    )
    record_cost(
        db, result, kind="ask", workspace_id=workspace_id, detail=actor
    )

    payload = extract_json(result.text) or {}
    text = str(payload.get("answer") or "").strip()
    claimed = [str(i) for i in (payload.get("cited") or [])]

    # A citation the model invented is dropped and recorded. The alternative —
    # showing it — puts a node id in front of a user that resolves to nothing.
    cited = [by_id[i] for i in claimed if i in by_id]
    fabricated = [i for i in claimed if i not in by_id]

    return Answer(
        question=question,
        text=text or _stub_answer(question, considered),
        cited=cited or considered[:3],
        considered=considered,
        fabricated=fabricated,
        gaps=_gaps(considered),
        provenance=result.provenance(),
    )


def _stub_answer(question: str, nodes: list[GraphNode]) -> str:
    """What to say when no model is configured.

    Deliberately factual rather than conversational: it lists what was found
    and leaves the interpretation to the reader. A stub that guessed at prose
    would be the same failure mode this module exists to prevent, with no model
    involved.
    """
    lines = [
        f"Found {len(nodes)} item(s) related to that question in the extracted "
        "configuration:"
    ]
    for node in nodes[:8]:
        attributes = node.attributes or {}
        summary = attributes.get("summary")
        if summary:
            lines.append(f"- {summary}")
            continue
        bands = attributes.get("bands")
        if bands:
            first, last = bands[0], bands[-1]
            lines.append(
                f"- {node.label}: {first.get('result')} rising to "
                f"{last.get('result')}, by {attributes.get('keyedOn', 'lookup')}"
            )
            continue
        lines.append(f"- {node.label} ({node.kind})")
    return "\n".join(lines)

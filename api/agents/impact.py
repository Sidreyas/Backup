"""
Impact analysis.

The graph decides *what* is impacted; the model explains *why* and how badly.
That division is the whole design. A model asked "what does this change affect"
will produce a confident, plausible, unverifiable list. A model asked "here are
the nine nodes the graph says are reachable — assess each one" produces
something a reviewer can check against the graph it came from.

So traversal runs first and is deterministic. The model never adds a node to
the result; it can only grade and explain the ones traversal found. If the
model returns a node id that was not in its input, that id is dropped and the
drop is recorded — a fabricated citation is exactly the kind of AI incident
this platform has a register for.

Blind spots are stated rather than hidden. An analysis that lists nothing it
could not reason about is claiming omniscience, and the two honest sources of
blindness — nodes with no confirmed path, and sources that are stale — are
computed rather than asked of the model.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.agents.llm import extract_json, llm, record_cost
from api.core.ids import new_id, utcnow
from api.domain import enums
from api.domain.models import (
    GraphNode,
    ImpactAnalysis,
    ImpactItem,
    KnowledgeSource,
    Requirement,
)
from api.domain.stlc import TestCase
from api.graph import queries

SYSTEM = """You are the impact analysis engine of an enterprise change governance platform.

You will be given a proposed change and a list of configuration nodes that a \
knowledge graph has determined are reachable from it. Your job is to assess each \
node that was given to you.

Rules you must follow:
- Assess ONLY the nodes provided. Never introduce a node that is not in the list.
- If you cannot tell whether a node is affected, say so with severity "none" and \
explain what you would need to know. Guessing is worse than abstaining.
- Severity means: "breaking" = existing behaviour stops working or data is lost; \
"major" = behaviour changes in a way users will notice; "minor" = internal or \
cosmetic; "none" = not actually affected.
- Your reason must refer to the specific configuration in the node's description \
or provenance. A reason that would apply to any node is not a reason.

Reply with JSON only, in this exact shape:
{"items": [{"nodeId": "...", "severity": "breaking|major|minor|none", "reason": "..."}]}"""


def _stub_payload(reached: list[queries.Reached]) -> str:
    """Structurally valid output for when no model is configured.

    Every node is graded "none" with an explicit statement that no analysis
    ran. That is the honest default: the graph found these nodes, and nothing
    has assessed them. Grading them anything else would manufacture a finding.
    """
    return json.dumps(
        {
            "items": [
                {
                    "nodeId": r.node.id,
                    "severity": "none",
                    "reason": (
                        "Reachable from the change in the graph, but no language model "
                        "is configured, so nothing has assessed it. Severity is "
                        "unassessed rather than low."
                    ),
                }
                for r in reached
            ]
        }
    )


def generate(
    db: Session,
    requirement: Requirement,
    *,
    seed_node_ids: list[str] | None = None,
    max_depth: int = 3,
) -> ImpactAnalysis:
    """Produce an impact analysis for a requirement.

    Seeds default to the requirement's recorded impacted nodes. When it has
    none — a requirement still in discussion — the analysis is empty and says
    why, rather than traversing from an arbitrary starting point.
    """
    seeds = seed_node_ids if seed_node_ids is not None else list(requirement.impacted_node_ids or [])
    started = utcnow()

    reached = (
        queries.neighbours(
            db,
            seeds,
            max_depth=max_depth,
            min_confidence=enums.LinkConfidence.MEDIUM,
            workspace_id=requirement.workspace_id,
        )
        if seeds
        else []
    )

    # Seeds themselves are impacted by definition — they are what the change
    # touches. Traversal deliberately excludes them, so they are added back at
    # depth 0 rather than being lost.
    seed_nodes = (
        list(db.execute(select(GraphNode).where(GraphNode.id.in_(seeds))).scalars())
        if seeds
        else []
    )
    for node in seed_nodes:
        reached.insert(
            0,
            queries.Reached(
                node=node,
                depth=0,
                path_confidence=enums.LinkConfidence.CONFIRMED,
                via=[],
            ),
        )

    prompt = _build_prompt(requirement, reached)
    result = llm.complete(
        system=SYSTEM,
        prompt=prompt,
        max_tokens=4096,
        grounded_node_ids=[r.node.id for r in reached],
        stub=_stub_payload(reached),
    )

    record_cost(
        db,
        result,
        kind="impact_analysis",
        requirement_id=requirement.id,
        workspace_id=requirement.workspace_id,
        detail=f"Impact analysis for {requirement.ref} over {len(reached)} nodes.",
    )

    parsed = extract_json(result.text) or {}
    graded = {
        item.get("nodeId"): item
        for item in parsed.get("items", [])
        if isinstance(item, dict)
    }

    # Anything the model invented. Dropped from the result and reported: a node
    # id that was never in the input is a fabricated citation.
    allowed = {r.node.id for r in reached}
    fabricated = [nid for nid in graded if nid not in allowed]

    analysis = ImpactAnalysis(
        id=new_id("ia"),
        requirement_id=requirement.id,
        generated_at=started,
        model=result.model,
        model_version=result.model_version,
        cost_usd=result.cost_usd,
        duration_seconds=max(1, int((utcnow() - started).total_seconds())),
        environment_fingerprint=_fingerprint(db, requirement),
        source=result.source,
        blind_spots=_blind_spots(db, requirement, reached, seeds, fabricated),
    )
    db.add(analysis)
    db.flush()

    coverage = _coverage_index(db, requirement.id)

    for r in reached:
        item = graded.get(r.node.id, {})
        severity = item.get("severity")
        if severity not in {s.value for s in enums.ImpactSeverity}:
            severity = enums.ImpactSeverity.NONE

        covered = coverage.get(r.node.id, [])
        db.add(
            ImpactItem(
                id=new_id("ii"),
                analysis_id=analysis.id,
                node_id=r.node.id,
                node_label=r.node.label,
                node_kind=r.node.kind,
                severity=severity,
                # The graph's confidence in the path, not the model's
                # confidence in its own opinion. The model does not get to
                # grade how sure the graph is.
                confidence=r.path_confidence,
                reason=item.get("reason") or "No assessment was produced for this node.",
                provenance=r.node.provenance,
                owner=r.node.owner,
                covered_by_test_ids=covered,
                # A gap only counts where something is actually at stake.
                coverage_gap=not covered and severity != enums.ImpactSeverity.NONE,
            )
        )

    db.flush()
    return analysis


def _build_prompt(requirement: Requirement, reached: list[queries.Reached]) -> str:
    lines = [
        f"PROPOSED CHANGE ({requirement.ref})",
        f"Title: {requirement.title}",
        f"Summary: {requirement.summary}",
        f"Target system: {requirement.platform}",
        "",
        "NODES THE GRAPH FOUND REACHABLE FROM THIS CHANGE:",
    ]
    if not reached:
        lines.append("(none — the graph has no confirmed configuration for this change)")
    for r in reached:
        lines.append(
            f"- id={r.node.id} | kind={r.node.kind} | {r.node.label}\n"
            f"    hops={r.depth} path_confidence={r.path_confidence}\n"
            f"    provenance: {r.node.provenance}\n"
            f"    description: {r.node.description or '(none recorded)'}"
        )
    lines.append("")
    lines.append("Assess each node above. Reply with JSON only.")
    return "\n".join(lines)


def _coverage_index(db: Session, requirement_id: str) -> dict[str, list[str]]:
    """Which approved test cases cover which nodes.

    Only approved cases count. A draft case covering a node is not coverage —
    it is an intention, and treating it as coverage would close a gap on paper
    that is still open in fact.
    """
    cases = db.execute(
        select(TestCase).where(
            TestCase.requirement_id == requirement_id,
            TestCase.state == enums.ReviewState.APPROVED,
        )
    ).scalars()

    index: dict[str, list[str]] = {}
    for case in cases:
        for node_id in case.covers_node_ids or []:
            index.setdefault(node_id, []).append(case.id)
    return index


def _blind_spots(
    db: Session,
    requirement: Requirement,
    reached: list[queries.Reached],
    seeds: list[str],
    fabricated: list[str],
) -> list[dict]:
    """What this analysis could not see. Computed, not asked of the model."""
    spots: list[dict] = []

    if not seeds:
        spots.append(
            {
                "area": "No starting point",
                "reason": (
                    "This requirement has no impacted nodes recorded, so nothing was "
                    "traversed. Ground it against the graph before relying on an "
                    "impact analysis."
                ),
            }
        )

    weak = [r for r in reached if r.path_confidence in {enums.LinkConfidence.MEDIUM}]
    if weak:
        spots.append(
            {
                "area": f"{len(weak)} node(s) reached only through unconfirmed links",
                "reason": (
                    "These were found via assertions no human has confirmed. They may "
                    "be wrong in either direction — a real dependency may be missing "
                    "and a listed one may not exist."
                ),
            }
        )

    stale = list(
        db.execute(
            select(KnowledgeSource).where(
                KnowledgeSource.status.in_(
                    [enums.IngestStatus.STALE, enums.IngestStatus.ERROR]
                )
            )
        ).scalars()
    )
    if stale:
        spots.append(
            {
                "area": f"{len(stale)} source(s) stale or failing",
                "reason": (
                    "Configuration from "
                    + ", ".join(s.name for s in stale[:3])
                    + " may be out of date, so changes made there since the last "
                    "successful sync are invisible to this analysis."
                ),
            }
        )

    if fabricated:
        spots.append(
            {
                "area": "Model referenced nodes that were not provided",
                "reason": (
                    f"{len(fabricated)} node id(s) in the model's reply did not appear in "
                    "its input and were discarded. This is a hallucinated citation and "
                    "should be raised as an AI incident if it recurs."
                ),
            }
        )

    if not llm.enabled:
        spots.append(
            {
                "area": "No language model configured",
                "reason": (
                    "Node discovery ran, but nothing assessed severity. Every item is "
                    "reported as unassessed rather than low-impact."
                ),
            }
        )

    return spots


def _fingerprint(db: Session, requirement: Requirement) -> dict:
    """The environment this analysis reasoned about.

    Recorded so an analysis stays interpretable after the environment moves on.
    Falls back to a stated-unknown rather than inventing a release string.
    """
    from api.domain.stlc import TestEnvironment

    env = db.execute(
        select(TestEnvironment)
        .where(TestEnvironment.platform == requirement.platform)
        .limit(1)
    ).scalar_one_or_none()

    if env is not None and env.fingerprint:
        return env.fingerprint

    return {
        "environment": "Unknown",
        "tenant": "unknown",
        "release": "unknown",
        "refreshedAt": None,
        "dataCoverage": 0,
    }

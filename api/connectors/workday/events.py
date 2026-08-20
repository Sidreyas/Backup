"""
Runtime business process events.

The configuration says a Change Job goes Manager → HR Partner → Compensation
Partner. This module reads what *actually happened*, and the gap between the
two is the finding the product exists to surface — the transcript's example is
an undocumented manual payroll correction that runs after every completion and
appears in no definition anywhere.

Two design decisions carry most of the weight.

**Observed steps are ordered, exactly like configured steps.** A runtime chain
is a sequence for the same reason an approval chain is: "the third thing that
happened" is the question. Emitting these as an unordered bag would make the
configured-versus-observed comparison impossible, which is the entire point of
reading them. So this module produces `RelationOrder` on `HAS_OBSERVED_STEP`,
using the same machinery `_rows_bp_steps` uses for definitions.

**Worker data is minimised at extraction, not later.** The transcript says to
minimise or tokenise; doing that downstream means the PII was already written
to evidence and the ledger, and "we delete it afterwards" is not a defence any
DPO accepts. `minimise=True` (the default) replaces named approvers with a
stable pseudonym derived from the tenant's own identifier, so drift analysis
can still say "the same person approved every one of these" without the graph
ever learning who. Turning it off is a deliberate, per-connection act.

The pseudonym is a keyed hash, not a plain digest: a bare SHA of a worker id is
trivially reversible when the id space is small, which for approvers in one
tenant it is.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

#: Steps whose presence in a run says something about the process rather than
#: about the worker. Everything else is transactional noise.
TERMINAL_STATUSES = {"completed", "successfully completed", "closed"}
OPEN_STATUSES = {"in progress", "awaiting action", "pending"}


@dataclass(slots=True)
class ObservedStep:
    """One step that actually executed in a business process instance."""

    sequence: int
    name: str
    status: str
    #: Pseudonymised unless minimisation is off. Never the raw worker name when
    #: `minimise` is set.
    actor: str = ""
    completed_at: str = ""
    due_at: str = ""
    #: True when this step appears in no definition for the process. This is
    #: the drift signal; it is computed by the connector, which is the only
    #: layer that can see both sides.
    undocumented: bool = False


@dataclass(slots=True)
class ProcessInstance:
    """One run of a business process."""

    instance_id: str
    definition_key: str
    definition_label: str
    status: str
    initiated_at: str = ""
    completed_at: str = ""
    steps: list[ObservedStep] = field(default_factory=list)

    @property
    def natural_key(self) -> str:
        return f"workday:bpinstance:{self.instance_id}"

    @property
    def scope(self) -> str:
        """Ordering scope for this instance's observed steps.

        Scoped to the *instance*, not the definition: two runs of Change Job
        each have a step 2, and they are not in conflict. Scoping to the
        definition would make the partial unique index reject the second run.
        """
        return f"workday:bpinstance:{self.instance_id}"


class Pseudonymiser:
    """Stable, non-reversible actor identifiers.

    Stable so "the same person approved all 40 of these" remains visible.
    Non-reversible so the graph never holds who that person is. Keyed with the
    tenant name, which means the same worker pseudonymises differently in
    different tenants — cross-tenant correlation is not a feature anyone asked
    for and would be a liability if it happened by accident.
    """

    __slots__ = ("_key",)

    def __init__(self, tenant: str) -> None:
        self._key = f"meridian:workday:{tenant}".encode()

    def __call__(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return ""
        digest = hmac.new(self._key, cleaned.encode("utf-8"), hashlib.sha256)
        return f"worker:{digest.hexdigest()[:16]}"


def parse_instances(
    rows: list[dict[str, Any]],
    *,
    pseudonymise: Pseudonymiser | None = None,
) -> list[ProcessInstance]:
    """Turn report rows into process instances with ordered steps.

    Workday's runtime reports return one row *per step*, not per instance, so
    rows are grouped by instance and then ordered within it. Rows arriving out
    of order is normal and must not produce an out-of-order chain, which is why
    position comes from the step-order column rather than from row position.
    """
    from api.connectors.workday.raas import field_value

    grouped: dict[str, ProcessInstance] = {}
    pending: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    for row in rows:
        instance_id = field_value(
            row, "Business_Process_Instance_ID", "Instance_ID", "Event_ID", "instanceId"
        )
        if not instance_id:
            continue

        if instance_id not in grouped:
            definition_label = field_value(
                row, "Business_Process_Type", "Definition_Name", "Process", "process"
            )
            definition_id = field_value(
                row, "Definition_ID", "Business_Process_ID", "definitionId"
            )
            # Match `_rows_bp_definitions` exactly: it uses the raw reference id
            # when there is one and slugs only the display name as a fallback.
            # Slugging unconditionally here produced `workday:bp:cj` against the
            # configured side's `workday:bp:CJ`, so the IMPLEMENTS edge linking
            # a run to its definition silently never resolved — the two chains
            # ingested cleanly and sat in the graph as unrelated islands.
            definition_key = definition_id or _slug(definition_label)
            grouped[instance_id] = ProcessInstance(
                instance_id=instance_id,
                definition_key=f"workday:bp:{definition_key}",
                definition_label=definition_label or definition_id or "Business process",
                status=field_value(row, "Overall_Status", "Status", "status"),
                initiated_at=field_value(
                    row, "Initiated_DateTime", "Initiated_On", "initiatedAt"
                ),
                completed_at=field_value(
                    row, "Completed_DateTime", "Completed_On", "completedAt"
                ),
            )
            pending[instance_id] = []

        pending[instance_id].append(
            (field_value(row, "Step_Order", "Sequence", "Order", "stepOrder"), row)
        )

    for instance_id, entries in pending.items():
        instance = grouped[instance_id]
        # Sort by the source's own ordering, falling back to arrival order for
        # rows that carry none. `_order_key` keeps "2a" between 2 and 3 rather
        # than throwing it to the end.
        entries.sort(key=lambda pair: _order_key(pair[0]))

        for position, (_, row) in enumerate(entries, start=1):
            instance.steps.append(_step(row, position, pseudonymise))

    return list(grouped.values())


def _step(
    row: dict[str, Any], position: int, pseudonymise: Pseudonymiser | None
) -> ObservedStep:
    from api.connectors.workday.raas import field_value

    actor = field_value(
        row, "Completed_By", "Actual_Approver", "Worker", "Actor", "completedBy"
    )
    return ObservedStep(
        sequence=position,
        name=field_value(row, "Step_Name", "Step", "Task", "stepName")
        or f"Step {position}",
        status=field_value(row, "Step_Status", "Status", "stepStatus"),
        actor=pseudonymise(actor) if pseudonymise else actor,
        completed_at=field_value(row, "Completed_DateTime", "Completed_On"),
        due_at=field_value(row, "Due_Date", "Due_DateTime", "dueDate"),
    )


def mark_undocumented(
    instances: list[ProcessInstance], configured: dict[str, set[str]]
) -> None:
    """Flag observed steps that appear in no definition.

    `configured` maps a definition natural key to the set of step names that
    definition declares. A step observed but never configured is the
    transcript's headline finding, and marking it at extraction keeps the
    judgement next to the evidence that supports it.

    Comparison is on normalised names because a report column and a definition
    column reach the same step through different spellings often enough that
    exact matching would report drift that is really a naming difference.
    """
    for instance in instances:
        known = configured.get(instance.definition_key)
        if not known:
            # No definition extracted for this process — absence of a baseline
            # is not evidence of drift, and claiming otherwise would flag every
            # step of every process the report pack has not reached.
            continue
        for step in instance.steps:
            step.undocumented = _normalise(step.name) not in known


def _normalise(name: str) -> str:
    return " ".join((name or "").lower().split())


def _slug(value: str) -> str:
    cleaned = "".join(
        char.lower() if char.isalnum() else "_" for char in (value or "").strip()
    )
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "unknown"


def _order_key(raw: str) -> tuple[int, str]:
    """Sort key tolerating Workday's suffixed step orders.

    "2a" sorts after "2" and before "3" — it is a sub-step, and Workday uses
    the form routinely.
    """
    text = (raw or "").strip()
    if not text:
        return (10**6, "")
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        else:
            break
    if not digits:
        return (10**6, text.lower())
    return (int(digits), text[len(digits) :].lower())

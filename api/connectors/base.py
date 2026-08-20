"""
The connector contract.

Every source system implements this interface, which is the transcript's
`EnterpriseConnector` narrowed to what a connector can actually be held to. Two
methods from that sketch are deliberately absent:

  - `resolve_identifiers` and `calculate_diff` are *platform* concerns, not
    connector concerns. Entity resolution has to compare across connectors, so
    letting each one resolve its own identifiers would produce as many
    resolution policies as there are connectors. They live in
    `api/graph/resolve.py`.

The contract's real job is the distinction the transcript keeps returning to:

    platform capability  ≠  tenant configuration  ≠  observed runtime behaviour

`discover_capabilities` reports what the *product* supports. `snapshot` reports
what this *customer* has configured. `observe` reports what actually ran. A
connector that conflates them produces a graph that cannot answer "is this
configured, or did someone just do it once".

Connectors never write to the graph. They emit `RawRecord`s; normalisation into
nodes and assertions happens in `api/graph/normalize.py` against a schema. This
is the engineering principle from the transcript — the extractor navigates and
captures, a deterministic parser produces the values, and nothing reaches the
graph without passing validation.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from api.core.ids import utcnow


@dataclass(slots=True)
class ConnectorScope:
    """A permission the connector asks for.

    `required` scopes cannot be declined without the connector losing its
    purpose; optional ones trade capability for caution, which is a decision
    the customer's security team should get to make rather than one the
    product makes for them.
    """

    id: str
    label: str
    description: str
    required: bool = False
    writes: bool = False


@dataclass(slots=True)
class ConnectorCapability:
    """One thing a connector can extract.

    `layer` records which of the three truths this capability speaks to, so the
    graph can keep them apart:
      - "capability": what the platform supports (a WSDL, an OpenAPI spec)
      - "configuration": what this tenant has set up
      - "runtime": what was observed happening
    """

    id: str
    label: str
    layer: str
    node_kinds: list[str] = field(default_factory=list)
    requires_scopes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConnectorOperation:
    """One change a connector is able to make in the source system.

    Every connector declares an empty list today, and that is the truth rather
    than an oversight: Meridian reads. The Workday browser layer refuses a step
    labelled save, submit or approve, and the API connectors hold read scopes
    only.

    The list exists so feasibility can ask a connector "could you make this
    change?" and get the answer from the connector itself. The alternative — a
    table of assumptions about what each system permits, kept somewhere else —
    goes stale the first time a connector changes and nobody remembers to update
    it, and it goes stale in the dangerous direction: claiming an ability that
    is not there.

    `node_kinds` is what makes the match specific. A connector able to modify a
    time off plan cannot necessarily modify an approval chain, and a feasibility
    answer of "yes, Workday supports writes" would paper over exactly that.
    """

    id: str
    label: str
    #: Which of ChangeIntent this operation serves — "new", "modify", "remove".
    #: A connector that can create but not delete says so here, so a removal is
    #: refused rather than attempted and half-completed.
    intents: list[str] = field(default_factory=list)
    node_kinds: list[str] = field(default_factory=list)
    requires_scopes: list[str] = field(default_factory=list)
    #: How the change would actually be made — "api", "screen", "package".
    #: Recorded because the three carry different risk, and an approver reading
    #: a plan deserves to know which one they are signing off.
    via: str = "api"


@dataclass(slots=True)
class RelationOrder:
    """Where an ordered relation sits, and what gates it.

    Separate from the relation tuple because ordering is the exception: an
    approval chain has a third step, `GOVERNED_BY` does not. Attaching this to
    every relation would mean every connector declaring "unordered" for almost
    all of them.
    """

    #: Position within `scope`. 1-based, matching how source systems number.
    sequence: int
    #: What the position is relative to — the process definition, the pipeline.
    #: Position 3 means nothing on its own, and two processes each having a
    #: step 3 is not a conflict.
    scope: str
    #: The branch rule as the source states it, or None for an unconditional
    #: step. Stored verbatim rather than parsed: making conditions evaluable is
    #: a separate, much larger piece of work.
    condition: dict[str, Any] | None = None


@dataclass(slots=True)
class RawRecord:
    """One immutable observation, before any interpretation.

    Stored as evidence exactly as received. The `natural_key` is the record's
    stable identifier *in its source system* and is what entity resolution
    matches on — never the display label, because two unrelated things called
    "Approval" must not merge.
    """

    kind: str
    natural_key: str
    label: str
    payload: dict[str, Any]
    source_ref: str = ""
    provenance: str = ""
    layer: str = "configuration"
    observed_at: str = field(default_factory=lambda: utcnow().isoformat())
    # Relationships this record asserts, as (predicate, target natural_key).
    # Emitted as candidates only — they become graph assertions with a
    # confidence, not facts.
    relations: list[tuple[str, str]] = field(default_factory=list)
    # Ordering and branch conditions for the relations above, keyed by
    # (predicate, target natural_key).
    #
    # Kept alongside `relations` rather than widening its tuple: most relations
    # are unordered, and every connector that emits a plain (predicate, target)
    # pair would otherwise need changing to say "no order" explicitly.
    ordering: dict[tuple[str, str], RelationOrder] = field(default_factory=dict)


@dataclass(slots=True)
class AccessCheck:
    ok: bool
    message: str
    # Scopes the credential actually has, which can be narrower than what was
    # requested. Reporting the difference is the point: a connector silently
    # running with less access than it needs produces a thin graph and no
    # explanation for why.
    effective_scopes: list[str] = field(default_factory=list)
    missing_scopes: list[str] = field(default_factory=list)


class ConnectorError(RuntimeError):
    """Raised for a fault the operator can act on.

    Distinct from an unexpected exception: this carries a message intended to
    be shown to a human in the connections UI.
    """


class NotConfigured(ConnectorError):
    """The connector has no credentials.

    Not an error state in the UI sense — a connector nobody has configured is
    simply unconfigured, and reporting that plainly is more useful than a stack
    trace or a false 'error' badge.
    """


class EnterpriseConnector(abc.ABC):
    """Base class every connector implements."""

    #: Stable identifier, matching the frontend's connector definition ids.
    id: str = ""
    name: str = ""
    vendor: str = ""
    category: str = "custom"
    kind: str = "platform"
    description: str = ""
    auth_methods: list[str] = []
    scopes: list[ConnectorScope] = []
    provides: list[str] = []

    #: Changes this connector can make. Empty everywhere today — see
    #: `ConnectorOperation`. Feasibility reads this to decide whether a requested
    #: change is possible at all, so a connector that gains write support
    #: declares it here and the gate starts permitting it without further
    #: plumbing.
    operations: list[ConnectorOperation] = []

    #: Bumped when extraction logic changes in a way that alters output. Stored
    #: on every ExtractionRun so a re-extraction that produces different nodes
    #: can be attributed to a code change rather than a source change.
    extractor_version: str = "1"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    # --- capability discovery ---------------------------------------------

    @abc.abstractmethod
    def discover_capabilities(self) -> list[ConnectorCapability]:
        """What this connector can extract, given how it is configured."""

    @abc.abstractmethod
    def validate_access(self) -> AccessCheck:
        """Check credentials without changing anything.

        Must never repair. "Does this still work" is the question people
        actually have, and answering it should not risk credentials that are
        already working.
        """

    # --- extraction --------------------------------------------------------

    @abc.abstractmethod
    def snapshot(self) -> Iterator[RawRecord]:
        """Emit the current tenant configuration.

        An iterator rather than a list: a large tenant produces more records
        than should be held in memory at once, and the ingestion pipeline
        writes evidence as records arrive so a run that fails halfway still
        leaves what it collected.
        """

    def observe(self) -> Iterator[RawRecord]:
        """Emit runtime behaviour — what actually ran, versus what is configured.

        Optional. A connector with no runtime surface returns nothing, which is
        honest; the alternative would be inventing a distinction the source
        system does not expose.
        """
        return iter(())

    def subscribe_to_changes(self) -> str | None:
        """Return a webhook path for incremental change, if supported.

        `None` means this connector is poll-only, which the scheduler needs to
        know rather than guess.
        """
        return None

    def is_configured(self) -> bool:
        return True

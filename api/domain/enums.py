"""
Enumerations, mirroring `src/lib/types.ts` exactly.

These are stored as plain strings rather than native Postgres ENUM types. A
Postgres enum requires a migration to add a value, and this vocabulary is still
moving — `AuditAction` in particular is expected to grow as the product records
more kinds of event. String columns with a Python-side enum give the same
type-safety where it is checked (in the application) without turning every new
audit verb into a schema migration.

Every literal here must match the TypeScript union of the same name. A mismatch
is not a type error in either language — it is a runtime bug that shows up as a
blank badge in the UI, so the two lists are kept adjacent in review.
"""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PLANNING = "planning"
    PAUSED = "paused"
    ARCHIVED = "archived"


class SourceKind(StrEnum):
    REPOSITORY = "repository"
    DOCUMENT = "document"
    DESIGN = "design"
    PLATFORM = "platform"
    TICKETING = "ticketing"
    WIKI = "wiki"


class IngestStatus(StrEnum):
    CONNECTED = "connected"
    SYNCING = "syncing"
    INDEXING = "indexing"
    ERROR = "error"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class UploadStage(StrEnum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    LINKING = "linking"
    READY = "ready"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class DocKind(StrEnum):
    SRS = "srs"
    BRD = "brd"
    FRD = "frd"
    PRD = "prd"
    ARCHITECTURE = "architecture"
    CONTRACT = "contract"
    OTHER = "other"


class NodeKind(StrEnum):
    REQUIREMENT = "requirement"
    BUSINESS_PROCESS = "business_process"
    CONFIG_OBJECT = "config_object"
    CODE_MODULE = "code_module"
    INTEGRATION = "integration"
    REPORT = "report"
    DATA_ENTITY = "data_entity"
    SCREEN = "screen"
    POLICY = "policy"


class LinkConfidence(StrEnum):
    """Every edge is a hypothesis until a human confirms it."""

    CONFIRMED = "confirmed"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RequirementStage(StrEnum):
    DRAFT = "draft"
    DISCUSSING = "discussing"
    IMPACT_REVIEW = "impact_review"
    TEST_PLANNING = "test_planning"
    TEST_DESIGN = "test_design"
    TEST_EXECUTION = "test_execution"
    AWAITING_APPROVAL = "awaiting_approval"
    BUILDING = "building"
    EVIDENCE = "evidence"
    SIGNED_OFF = "signed_off"
    REJECTED = "rejected"


class SystemKind(StrEnum):
    VENDOR_PLATFORM = "vendor_platform"
    INTERNAL_PROJECT = "internal_project"
    MIXED = "mixed"


class Criticality(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ImpactSeverity(StrEnum):
    BREAKING = "breaking"
    MAJOR = "major"
    MINOR = "minor"
    NONE = "none"


class ArtifactOrigin(StrEnum):
    AI_GENERATED = "ai_generated"
    HUMAN_AUTHORED = "human_authored"
    AI_EDITED_BY_HUMAN = "ai_edited_by_human"


class ReviewState(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class TestLevel(StrEnum):
    UNIT = "unit"
    INTEGRATION = "integration"
    SYSTEM = "system"
    UAT = "uat"
    REGRESSION = "regression"


class TestType(StrEnum):
    FUNCTIONAL = "functional"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"
    DATA_INTEGRITY = "data_integrity"
    COMPLIANCE = "compliance"


class RubricDimension(StrEnum):
    SPECIFICITY = "specificity"
    TRACEABILITY = "traceability"
    TESTABILITY = "testability"
    RISK_COVERAGE = "risk_coverage"
    EVIDENCE_GROUNDING = "evidence_grounding"


class RubricVerdict(StrEnum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"


class EnvironmentStatus(StrEnum):
    READY = "ready"
    PROVISIONING = "provisioning"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    REFRESHING = "refreshing"


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ABORTED = "aborted"
    BLOCKED = "blocked"


class RunStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    FLAKY = "flaky"
    RUNNING = "running"
    QUEUED = "queued"
    SKIPPED = "skipped"


class EvidenceGrade(StrEnum):
    """The product's central distinction.

    `VERIFIED` means a deterministic, replayable test produced an artifact.
    `ASSERTED` means an agent claims it works. Only verified evidence may
    satisfy a gate that demands it — enforced in `api/services/approvals.py`,
    not merely displayed.
    """

    VERIFIED = "verified"
    ASSERTED = "asserted"


class DefectStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    CLOSED = "closed"
    WONT_FIX = "wont_fix"
    REJECTED = "rejected"


class ClosureState(StrEnum):
    OPEN = "open"
    READY_TO_CLOSE = "ready_to_close"
    CLOSED = "closed"
    CLOSED_WITH_DEVIATIONS = "closed_with_deviations"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    DELEGATED = "delegated"


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class RetentionClass(StrEnum):
    STANDARD = "standard"
    SOX = "sox"
    GXP = "gxp"
    AI_ACT = "ai_act"
    PERMANENT = "permanent"


class IncidentKind(StrEnum):
    HALLUCINATED_CITATION = "hallucinated_citation"
    MISSED_IMPACT = "missed_impact"
    FALSE_IMPACT = "false_impact"
    UNAUTHORISED_ACTION = "unauthorised_action"
    EVIDENCE_MISMATCH = "evidence_mismatch"
    MODEL_DRIFT = "model_drift"
    POLICY_BYPASS = "policy_bypass"
    DATA_LEAKAGE = "data_leakage"


class IncidentSeverity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    CONTAINED = "contained"
    RESOLVED = "resolved"
    DISCLOSED = "disclosed"


class AuthMethod(StrEnum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BASIC = "basic"
    SERVICE_ACCOUNT = "service_account"
    WEBHOOK = "webhook"


class SyncCadence(StrEnum):
    REALTIME = "realtime"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class AssertionStatus(StrEnum):
    """Lifecycle of a reified graph assertion.

    `PROPOSED` is machine output nobody has looked at. `CONFIRMED` and
    `REFUTED` are human judgements. `SUPERSEDED` is set when a later assertion
    about the same subject/predicate/object replaces this one — the old row is
    never deleted, so the history of what the graph believed stays readable.
    """

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    SUPERSEDED = "superseded"


class ChangeIntent(StrEnum):
    """What a requirement is asking to happen.

    The shape of the feasibility check follows from this. A REMOVE has to know
    what depends on the thing; a NEW has to know where it lands; a DOWNGRADE is
    a MODIFY whose acceptance criteria are about what must *stop* working, which
    is the case people forget to test.

    UNCLEAR is a real answer, not a fallback. "Change the timing in Hong Kong
    leave" does not say whether timing means the accrual schedule or the
    approval SLA, and guessing between them silently is how the wrong thing
    gets built.
    """

    NEW = "new"
    MODIFY = "modify"
    REMOVE = "remove"
    DOWNGRADE = "downgrade"
    UNCLEAR = "unclear"


class FeasibilityVerdict(StrEnum):
    """Whether a requirement can be acted on.

    INCOMPLETE and BLOCKED are kept apart because the remedy differs and the
    audience differs. INCOMPLETE is answerable by the person asking: more
    detail, a decision between candidates. BLOCKED cannot be talked away by
    anyone in the conversation — a permission is missing, or configuration was
    never extracted — and needs someone to change the world outside Meridian.

    Collapsing the two into "not ready" would send every requester off to chase
    their own security administrator, and would let a genuinely blocked change
    look like a conversation that had not finished yet.
    """

    FEASIBLE = "feasible"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"


class GapKind(StrEnum):
    """Why a requirement is not yet feasible.

    FRESHNESS is separate from DATA on purpose. Absent configuration and
    six-week-old configuration fail differently: the first is visibly empty,
    and the second answers confidently from a tenant that has since moved on.
    """

    UNDERSTANDING = "understanding"
    DATA = "data"
    ACCESS = "access"
    FRESHNESS = "freshness"

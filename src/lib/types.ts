/**
 * Meridian domain model.
 *
 * These types encode the governance semantics of the product, not just the
 * shape of the mock data. Two distinctions matter most and are enforced here:
 *
 *  1. EvidenceGrade — 'verified' (a deterministic, replayable test produced an
 *     artifact) vs 'asserted' (an agent claims it works). Only 'verified'
 *     evidence may satisfy a sign-off gate.
 *  2. LinkConfidence — cross-artifact graph edges are hypotheses until a human
 *     confirms them. The graph never silently presents a guess as a fact.
 */

export type Id = string

/* --------------------------------------------------------------- workspaces */

/**
 * A workspace is a governance boundary — typically a business unit or a
 * regulated entity. Policies, approval gates and the audit chain are scoped to
 * it, so a change in one workspace can never satisfy a gate in another.
 *
 * A project sits inside a workspace and scopes the working set: which sources
 * are connected, which requirements are in flight, which evidence counts.
 */
export interface Workspace {
  id: Id
  name: string
  /** Short label used in the switcher and breadcrumbs */
  slug: string
  /** Regulatory regime that governs everything inside it */
  compliance: string[]
  region: string
  memberCount: number
  projectIds: Id[]
}

export type ProjectStatus = 'active' | 'planning' | 'paused' | 'archived'

export interface Project {
  id: Id
  workspaceId: Id
  name: string
  key: string
  description: string
  status: ProjectStatus
  /** The platform this project governs changes for */
  platform: string
  lead: string
  createdAt: string
  /** Ids of the knowledge sources connected to this project */
  sourceIds: Id[]
  openRequirements: Id[]
  monthlySpendUsd: number
}

/* ------------------------------------------------------------------ sources */

export type SourceKind = 'repository' | 'document' | 'design' | 'platform' | 'ticketing' | 'wiki'

export type IngestStatus = 'connected' | 'syncing' | 'indexing' | 'error' | 'stale' | 'disconnected'

export interface KnowledgeSource {
  id: Id
  name: string
  kind: SourceKind
  /** e.g. 'GitHub', 'Workday', 'SAP S/4HANA', 'Confluence', 'Figma' */
  provider: string
  status: IngestStatus
  /** ISO timestamp of last successful sync */
  lastSyncedAt: string | null
  /** How many days of drift before this source is considered stale */
  stalenessThresholdDays: number
  entities: number
  documents: number
  /** 0–100; how much of the source Meridian could actually parse */
  coverage: number
  sizeLabel: string
  owner: string
  error?: string
}

/* ---------------------------------------------------------------- ingestion */

export type UploadStage =
  | 'queued'
  | 'uploading'
  | 'parsing'
  | 'extracting'
  | 'linking'
  | 'ready'
  | 'failed'
  | 'needs_review'

export type DocKind = 'srs' | 'brd' | 'frd' | 'prd' | 'architecture' | 'contract' | 'other'

/**
 * A single artefact the user has pushed into Meridian — an uploaded document,
 * a cloned repository, or a pulled platform tenant.
 *
 * Ingestion is deliberately staged rather than a single "done" flag, because
 * each stage can partially fail: a PDF may parse but yield no requirements, a
 * repo may index but resolve no links to the business layer. Surfacing the
 * stage is what lets the user see why the graph looks thin.
 */
export interface IngestJob {
  id: Id
  projectId: Id
  name: string
  /** Which pipeline handled it */
  kind: SourceKind
  docKind?: DocKind
  provider: string
  stage: UploadStage
  /** 0–100 within the current stage */
  progress: number
  sizeLabel: string
  uploadedAt: string
  uploadedBy: string
  /** Entities lifted out of this artefact */
  entitiesExtracted: number
  /** Edges proposed from it into the rest of the graph */
  linksProposed: number
  /** Share of the artefact the parser could actually read (0–100) */
  parseCoverage: number
  /** Populated when the pipeline needs a human decision or has failed */
  message?: string
  warnings: string[]
}

/** A step in the graph build, shown as a live pipeline on the ingestion page. */
export interface BuildStep {
  id: Id
  label: string
  description: string
  status: 'pending' | 'running' | 'done' | 'blocked'
  /** Human-readable output, e.g. "1,284 entities" */
  detail: string
  durationSeconds: number
  costUsd: number
}

export interface GraphBuild {
  id: Id
  projectId: Id
  startedAt: string
  finishedAt: string | null
  status: 'idle' | 'running' | 'complete' | 'failed'
  steps: BuildStep[]
  nodesCreated: number
  edgesProposed: number
  edgesConfirmed: number
  costUsd: number
  /** Areas the build knows it could not resolve */
  unresolved: { area: string; reason: string; count: number }[]
}

/* -------------------------------------------------------------------- graph */

export type NodeKind =
  | 'requirement'
  | 'business_process'
  | 'config_object'
  | 'code_module'
  | 'integration'
  | 'report'
  | 'data_entity'
  | 'screen'
  | 'policy'

/** Every edge is a hypothesis until a human confirms it. */
export type LinkConfidence = 'confirmed' | 'high' | 'medium' | 'low'

export interface GraphNode {
  id: Id
  label: string
  kind: NodeKind
  /** Which source this node was derived from */
  sourceId: Id
  /** Human-readable provenance, e.g. 'BRD-2024-Q3.pdf § 4.2' */
  provenance: string
  /** Deep link back into the source system */
  sourceRef: string
  criticality: 'critical' | 'high' | 'medium' | 'low'
  owner: string
  lastVerifiedAt: string | null
  /** Layout position, normalised 0–1 (mock — a real graph would use a layout engine) */
  x: number
  y: number
  description: string
}

export interface GraphEdge {
  id: Id
  from: Id
  to: Id
  label: string
  confidence: LinkConfidence
  /** Who confirmed it, when — null while still a hypothesis */
  confirmedBy: string | null
  confirmedAt: string | null
  /** What made Meridian propose this link */
  rationale: string
}

/* ------------------------------------------------------------- requirements */

/**
 * Requirement lifecycle, aligned to the STLC phases that sit between an agreed
 * impact analysis and sign-off:
 *
 *   impact_review → test_planning → test_design → test_execution
 *                 → evidence → awaiting_approval → signed_off
 *
 * The testing stages are explicit rather than collapsed into "building",
 * because each has its own entry and exit criteria and each can be blocked.
 */
export type RequirementStage =
  | 'draft'
  | 'discussing'
  | 'impact_review'
  | 'test_planning'
  | 'test_design'
  | 'test_execution'
  | 'awaiting_approval'
  | 'building'
  | 'evidence'
  | 'signed_off'
  | 'rejected'

/**
 * What kind of system a requirement targets.
 *
 * Not every change lands in a vendor platform. Teams run their own internal
 * applications and services, and a requirement against one of those is
 * governed identically — same graph, same evidence, same gates. Modelling only
 * external platforms would have forced that work to masquerade as something
 * it is not.
 */
export type SystemKind = 'vendor_platform' | 'internal_project' | 'mixed'

export interface Requirement {
  id: Id
  ref: string
  title: string
  summary: string
  stage: RequirementStage
  requestedBy: string
  requestedByRole: string
  createdAt: string
  updatedAt: string
  /** Display name of the target system, vendor or internal alike. */
  platform: string
  /** Whether `platform` names a vendor product or something built in-house. */
  systemKind: SystemKind
  /**
   * How urgently the business wants this.
   *
   * Distinct from `riskLevel`, which is how dangerous the change is. A low-risk
   * change can be urgent and a high-risk one can be nice-to-have; collapsing
   * the two would let urgency argue its way past a risk gate.
   */
  priority: TestPriority
  /** Nodes this requirement is believed to touch */
  impactedNodeIds: Id[]
  estimatedCostUsd: number
  actualCostUsd: number
  riskLevel: 'critical' | 'high' | 'medium' | 'low'
}

export type ChatRole = 'user' | 'assistant' | 'system'

export interface Citation {
  nodeId: Id
  label: string
  provenance: string
  confidence: LinkConfidence
}

/** The assistant can formally disagree; dissent is part of the record. */
export interface Dissent {
  severity: 'blocking' | 'advisory'
  statement: string
  conflictsWith?: string
}

/** One page the crawler reached. */
export interface CrawledPage {
  url: string
  title: string
  /** What the crawler found here that is worth testing. */
  note: string
}

/**
 * A site crawl run to discover what an application actually does.
 *
 * Recorded as a first-class artefact rather than prose in the transcript: the
 * cases generated from it cite it, so an auditor asking "how did you know the
 * checkout flow existed" has an answer with a timestamp and a page list.
 */
export interface CrawlResult {
  id: Id
  startUrl: string
  status: 'running' | 'complete' | 'failed'
  startedAt: string
  /** How deep the crawler was allowed to follow links. */
  maxDepth: number
  pages: CrawledPage[]
  /** Present when status is 'failed'. */
  error?: string
}

/** A case proposed in-thread, before it is written to the plan. */
export interface ProposedCase {
  id: Id
  ref: string
  title: string
  /** The journey or area it belongs to — "Discovery", "Ordering". */
  group: string
  summary: string
  /** Steps, shown when the reader expands the card. */
  steps: string[]
}

export interface ChatMessage {
  id: Id
  role: ChatRole
  content: string
  at: string
  citations?: Citation[]
  dissent?: Dissent
  /** Token + cost accounting per assistant turn */
  tokensIn?: number
  tokensOut?: number
  costUsd?: number
  model?: string
  /**
   * A crawl the assistant ran to answer this turn. Rendered as a card in the
   * transcript so the evidence sits with the claim it supports.
   */
  crawl?: CrawlResult
  /**
   * Cases the assistant generated on this turn. Shown in the transcript and
   * mirrored into the side panel — the same set, in the place you are reading
   * and the place you will act on them.
   */
  generatedCases?: ProposedCase[]
  /**
   * Outcome of a test run made on this turn. Renders as a completion pill above
   * the reply, so the run is legible as an event that happened rather than as a
   * claim inside prose.
   */
  runSummary?: { passed: number; total: number }
  /**
   * Tool calls made on this turn, summarised. Named rather than hidden: an
   * answer that quietly went and read a live system is different from one
   * that reasoned over what it already had.
   */
  toolCalls?: { label: string; detail?: string }[]
}

/* ----------------------------------------------------------------- impact */

export type ImpactSeverity = 'breaking' | 'major' | 'minor' | 'none'

export interface ImpactItem {
  id: Id
  nodeId: Id
  nodeLabel: string
  nodeKind: NodeKind
  severity: ImpactSeverity
  confidence: LinkConfidence
  reason: string
  provenance: string
  owner: string
  /** Regression tests that cover this node, if any */
  coveredByTestIds: Id[]
  /** True when Meridian has no test coverage for a node it flagged */
  coverageGap: boolean
}

export interface ImpactAnalysis {
  requirementId: Id
  generatedAt: string
  model: string
  costUsd: number
  durationSeconds: number
  items: ImpactItem[]
  /** Nodes Meridian knows it could not reason about, stated explicitly */
  blindSpots: { area: string; reason: string }[]
  environmentFingerprint: EnvironmentFingerprint
}

/* ------------------------------------------------------------------- STLC */

/**
 * The Software Testing Life Cycle as Meridian models it. Each artefact below
 * is authored by an agent and then reviewed by a human — nothing an agent
 * produces is treated as approved until someone signs it, which is the same
 * rule the graph applies to links and the evidence store applies to claims.
 */
export type ArtifactOrigin = 'ai_generated' | 'human_authored' | 'ai_edited_by_human'

/** Review state shared by test plans and test cases. */
export type ReviewState = 'draft' | 'in_review' | 'approved' | 'rejected'

/**
 * Entry and exit criteria are what make this a life cycle rather than a task
 * list: a phase cannot be entered until its entry criteria hold, and closure
 * is *evaluated* against exit criteria rather than simply declared.
 */
export interface Criterion {
  id: Id
  text: string
  /** Whether the condition currently holds. null = not yet evaluated. */
  met: boolean | null
  /** How it was checked — an automated probe or a person asserting it */
  evaluatedBy: 'system' | 'human' | null
  detail?: string
}

export type TestLevel = 'unit' | 'integration' | 'system' | 'uat' | 'regression'
export type TestType =
  'functional' | 'security' | 'performance' | 'accessibility' | 'data_integrity' | 'compliance'

/** STLC phase 2 — planning. Scope, strategy, risks, criteria, estimates. */
export interface TestPlan {
  id: Id
  ref: string
  requirementId: Id
  requirementRef: string
  title: string
  origin: ArtifactOrigin
  state: ReviewState
  version: number
  createdAt: string
  updatedAt: string
  author: string
  approvedBy: string | null
  approvedAt: string | null
  /** Narrative sections, editable as prose */
  objective: string
  scopeIn: string[]
  scopeOut: string[]
  levels: TestLevel[]
  types: TestType[]
  entryCriteria: Criterion[]
  exitCriteria: Criterion[]
  /** Risks the plan explicitly accepts, with mitigation */
  risks: { id: Id; risk: string; likelihood: 'high' | 'medium' | 'low'; mitigation: string }[]
  /** Impacted graph nodes this plan claims to cover */
  coveredNodeIds: Id[]
  /** Nodes flagged by impact analysis that the plan does NOT cover */
  uncoveredNodeIds: Id[]
  environmentIds: Id[]
  estimatedCases: number
  estimatedDurationHours: number
  generationCostUsd: number
  model: string
}

export type TestPriority = 'critical' | 'high' | 'medium' | 'low'

export interface TestStep {
  id: Id
  index: number
  action: string
  expected: string
}

/**
 * The five things a generated test case is judged on.
 *
 * Fixed rather than free-form so scores are comparable across cases and over
 * time: a rubric whose dimensions change per case measures nothing.
 */
export type RubricDimensionId =
  | 'specificity'
  | 'traceability'
  | 'testability'
  | 'risk_coverage'
  | 'evidence_grounding'

/**
 * One scored dimension.
 *
 * `rationale` is not optional. A bare 4.0 is an opinion; a 4.0 with the reason
 * it was not a 5.0 is something a reviewer can disagree with, which is the
 * only form of machine judgement worth showing.
 */
export interface RubricScore {
  dimension: RubricDimensionId
  /** 1–5, to one decimal. */
  score: number
  rationale: string
  /**
   * What in the source material the judge pointed at — a requirement ref, a
   * graph node, a policy clause. Empty when the judge could cite nothing,
   * which is itself worth seeing.
   */
  citations: string[]
}

export type RubricVerdict = 'accept' | 'revise' | 'reject'

/**
 * An LLM's assessment of a generated test case.
 *
 * Deliberately advisory. The verdict is recorded and shown, but approval stays
 * a human action — a model scoring another model's output is evidence for a
 * reviewer, not a substitute for one. Auto-approving on a high score would put
 * an unaccountable actor inside the control this whole system exists to prove.
 */
export interface JudgeRubric {
  /** Which model produced the assessment, so a bad run can be traced. */
  judgeModel: string
  judgedAt: string
  scores: RubricScore[]
  /** Mean of the dimension scores, precomputed for display. */
  overall: number
  verdict: RubricVerdict
  /** One line a reviewer can read instead of five. */
  summary: string
  /**
   * The inputs the judge saw. Without this the score is unreproducible, and an
   * unreproducible score has no place in an audit trail.
   */
  inputs: string[]
  /**
   * Set when the case was edited after being judged, so the score describes a
   * version that no longer exists.
   *
   * Shown rather than hidden: silently dropping a stale score would conceal
   * that a human overrode a judged case, which is precisely the event a
   * reviewer most needs to see.
   */
  supersededByEdit?: boolean
}

/** STLC phase 3 — test case development. */
export interface TestCase {
  id: Id
  ref: string
  planId: Id
  requirementId: Id
  title: string
  origin: ArtifactOrigin
  state: ReviewState
  level: TestLevel
  type: TestType
  priority: TestPriority
  /** Whether this case can run deterministically or needs a human/agent */
  automatable: boolean
  preconditions: string[]
  steps: TestStep[]
  /** The single assertion this case ultimately proves */
  expectedResult: string
  testData: string
  /** Graph nodes this case exercises — drives the coverage view */
  coversNodeIds: Id[]
  createdAt: string
  updatedAt: string
  author: string
  /** Why the agent proposed this case; shown so a reviewer can judge it */
  rationale: string
  /**
   * Scored assessment of this case. Absent on human-authored cases — there is
   * nothing to audit about a person's judgement that the person did not
   * already sign, and scoring their work with a model would invert the
   * accountability this system is built on.
   */
  rubric?: JudgeRubric
  estimatedDurationSeconds: number
  tags: string[]
}

/** A named, ordered selection of cases run together. */
export interface TestSuite {
  id: Id
  ref: string
  name: string
  description: string
  caseIds: Id[]
  /** Suites can be ad-hoc (built at execution time) or saved */
  saved: boolean
  createdAt: string
  createdBy: string
}

export type EnvironmentStatus = 'ready' | 'provisioning' | 'degraded' | 'offline' | 'refreshing'

/**
 * STLC phase 4 — environment setup. Environments are long-lived and shared, so
 * they are modelled as a precondition checked at execution time rather than a
 * wizard step repeated per requirement.
 */
export interface TestEnvironment {
  id: Id
  name: string
  kind: 'sandbox' | 'staging' | 'preprod' | 'ephemeral'
  platform: string
  status: EnvironmentStatus
  fingerprint: EnvironmentFingerprint
  /** Checks that must pass before a run may start here */
  readiness: Criterion[]
  lastRefreshedAt: string
  ownedBy: string
  /** Cost per hour while the environment is held */
  hourlyCostUsd: number
  notes?: string
}

export type ExecutionStatus = 'queued' | 'running' | 'passed' | 'failed' | 'aborted' | 'blocked'

/** Per-case outcome inside an execution — the expected vs actual record. */
export interface CaseResult {
  id: Id
  caseId: Id
  caseRef: string
  caseTitle: string
  status: RunStatus
  grade: EvidenceGrade
  /** What the case said should happen */
  expected: string
  /** What actually happened */
  actual: string
  /** Set when expected and actual diverge */
  deviation: string | null
  durationSeconds: number
  attempts: number
  startedAt: string
  artifacts: EvidenceArtifact[]
  coversNodeIds: Id[]
  /** Populated when a defect was raised from this result */
  defectRef?: string
}

/** STLC phase 5 — execution. One run of a suite in one environment. */
export interface TestExecution {
  id: Id
  ref: string
  requirementId: Id
  planId: Id
  /** Either a saved suite or an ad-hoc selection */
  suiteId: Id | null
  suiteName: string
  environmentId: Id
  environment: EnvironmentFingerprint
  status: ExecutionStatus
  triggeredBy: string
  triggeredByType: 'human' | 'agent' | 'schedule'
  startedAt: string
  finishedAt: string | null
  results: CaseResult[]
  costUsd: number
  /** Readiness checks evaluated at launch; a failure blocks the run */
  preflight: Criterion[]
  /** Why the execution was blocked, if it was */
  blockedReason?: string
}

/* --------------------------------------------------------------- defects */

/**
 * Defect severity, using the same scale as impact so a defect's weight can be
 * compared with the risk it was raised against.
 */
export type DefectSeverity = ImpactSeverity

/**
 * Where a defect sits in its own small lifecycle.
 *
 * `fixed` and `closed` are deliberately distinct: a developer marking
 * something fixed is a claim, and only a passing re-test turns that claim into
 * a closed defect. Collapsing the two would let an unverified assertion
 * satisfy a closure gate.
 */
export type DefectStatus = 'open' | 'in_progress' | 'fixed' | 'closed' | 'wont_fix' | 'rejected'

/**
 * STLC phase 5b — a defect raised from a failed or deviating result.
 *
 * Defects are what connect execution to re-test: a failed case produces a
 * defect, a fix produces a re-test, and the re-test is what closes it. Without
 * this record the cycle jumps from "a test failed" to "sign it off" with
 * nothing accounting for what happened in between.
 */
export interface Defect {
  id: Id
  ref: string
  requirementId: Id
  /** The execution and case result this was raised from */
  executionId: Id | null
  caseId: Id | null
  caseRef: string | null
  title: string
  /** What the case expected versus what it did — copied at raise time so the
   *  defect stays readable even if the case is later edited. */
  expected: string
  actual: string
  severity: DefectSeverity
  status: DefectStatus
  owner: string
  raisedBy: string
  raisedByType: ArtifactOrigin
  raisedAt: string
  updatedAt: string
  /** Free-text notes appended as the defect moves — the working record. */
  notes: { at: string; by: string; text: string }[]
  /** Executions that re-tested this defect, newest last */
  retestExecutionIds: Id[]
  /** Set once a re-test has passed against it */
  verifiedByExecutionId: Id | null
  /** Nodes the defect touches, so closure can tell whether a gap is covered */
  affectedNodeIds: Id[]
}

/** STLC phase 6 — closure. Evaluated, not declared. */
export interface TestClosure {
  id: Id
  requirementId: Id
  requirementRef: string
  planId: Id
  executionIds: Id[]
  /** Closure cannot be signed while any exit criterion is unmet */
  exitCriteria: Criterion[]
  state: 'open' | 'ready_to_close' | 'closed' | 'closed_with_deviations'
  closedBy: string | null
  closedAt: string | null
  summary: {
    casesTotal: number
    passed: number
    failed: number
    blocked: number
    notRun: number
    verified: number
    asserted: number
  }
  /** Defects still open at closure, stated rather than hidden */
  openDefects: { ref: string; title: string; severity: ImpactSeverity; owner: string }[]
  /** What the cycle could not prove — carried into the approval package */
  residualRisks: { area: string; reason: string; acceptedBy: string | null }[]
  lessons: string[]
  totalCostUsd: number
  totalDurationHours: number
}

/* --------------------------------------------------------------- evidence */

export type EvidenceGrade = 'verified' | 'asserted'
export type RunStatus = 'passed' | 'failed' | 'flaky' | 'running' | 'queued' | 'skipped'

export interface EnvironmentFingerprint {
  environment: string
  tenant: string
  release: string
  refreshedAt: string
  /** 0–100: share of production scenario classes represented in this env */
  dataCoverage: number
}

export interface EvidenceArtifact {
  id: Id
  kind: 'video' | 'trace' | 'dom' | 'network' | 'screenshot' | 'log'
  label: string
  sizeLabel: string
  /** Content hash — the artifact is part of a tamper-evident chain */
  sha256: string
}

export interface TestRun {
  id: Id
  ref: string
  requirementId: Id
  title: string
  /** The core distinction: deterministic replayable test vs agent claim */
  grade: EvidenceGrade
  status: RunStatus
  /** Only meaningful for deterministic runs */
  suite: string | null
  startedAt: string
  durationSeconds: number
  attempts: number
  flakeRate: number
  runner: string
  environment: EnvironmentFingerprint
  artifacts: EvidenceArtifact[]
  coveredNodeIds: Id[]
  failureReason?: string
  costUsd: number
}

/* -------------------------------------------------------------- approvals */

export type ApprovalDecision = 'approved' | 'rejected' | 'pending' | 'delegated'

export interface ApprovalGate {
  id: Id
  name: string
  role: string
  /** A gate can require verified evidence — asserted will not satisfy it */
  requiresEvidenceGrade: EvidenceGrade | null
  decision: ApprovalDecision
  approver: string | null
  approverEmail: string | null
  decidedAt: string | null
  comment: string | null
  /** Blocking policy violations that prevent this gate from being satisfied */
  blockedBy: string[]
  /**
   * When a decision is due on this gate.
   *
   * A breached deadline does not block the gate — it is reported, not enforced.
   * Auto-rejecting on a missed SLA would replace a human decision with a
   * timer, which is the opposite of what a sign-off is for.
   */
  dueAt: string | null
  /**
   * Evidence that the decision was meaningful. Null while pending — there is
   * no oversight to record until someone has actually decided.
   */
  oversight?: HumanOversightRecord | null
}

export interface ApprovalPackage {
  id: Id
  requirementId: Id
  requirementRef: string
  title: string
  submittedAt: string
  submittedBy: string
  gates: ApprovalGate[]
  evidenceSummary: {
    verified: number
    asserted: number
    failed: number
    coverageGaps: number
  }
  estimatedCostUsd: number
  riskLevel: 'critical' | 'high' | 'medium' | 'low'
}

/* ------------------------------------------------------------ audit chain */

/**
 * Every action the platform can record.
 *
 * The taxonomy is deliberately exhaustive over what the product actually does.
 * An action a user can take that has no term here is an action that leaves no
 * trace, and a record that is silently incomplete is worse than one that is
 * obviously partial — an auditor can work with the second and is misled by the
 * first.
 */
export type AuditAction =
  /* sources & graph */
  | 'source.connected'
  | 'source.synced'
  | 'artifact.uploaded'
  | 'graph.link_confirmed'
  | 'graph.built'
  /* requirements */
  | 'requirement.created'
  | 'requirement.discussed'
  | 'requirement.stage_changed'
  | 'impact.generated'
  /* policy & configuration */
  | 'policy.evaluated'
  | 'policy.violated'
  | 'policy.toggled'
  | 'settings.changed'
  | 'access.granted'
  /* STLC authoring */
  | 'plan.generated'
  | 'plan.state_changed'
  | 'test.generated'
  | 'testcase.edited'
  | 'testcase.state_changed'
  /* execution */
  | 'test.run'
  | 'execution.started'
  | 'execution.finished'
  /* defects */
  | 'defect.raised'
  | 'defect.status_changed'
  | 'retest.recorded'
  /* closure & approval */
  | 'closure.signed'
  | 'approval.requested'
  | 'approval.granted'
  | 'approval.rejected'
  | 'change.deployed'
  /* the record about the record */
  | 'evidence.exported'
  | 'chain.verified'
  | 'incident.raised'
  | 'incident.updated'

/**
 * A single field-level change — the ALCOA+ / 21 CFR Part 11 §11.10(e) unit of
 * record.
 *
 * A summary sentence says an artefact changed; it does not say what it was
 * before. Regulators ask for the prior value specifically, because "the test
 * expectation was edited" and "the test expectation was weakened from X to Y"
 * are different findings and only the second is actionable.
 */
export interface FieldChange {
  field: string
  /** Display label; `field` stays machine-readable for filtering */
  label: string
  before: string | null
  after: string | null
}

/**
 * Model provenance for an entry an AI produced.
 *
 * Required to answer two questions the EU AI Act asks: which system version
 * produced this output (Art. 12 substantial-modification detection), and can
 * the output be reproduced (NIST AI RMF traceability). Without the model
 * version on the record, a silent model upgrade is invisible in the history.
 */
export interface AiProvenance {
  model: string
  /** Pinned version — the field that makes drift detectable at all */
  modelVersion: string
  /** Hash of the prompt, so the input is attestable without storing it */
  promptHash: string
  tokensIn: number
  tokensOut: number
  temperature: number
  /** Which knowledge-graph nodes grounded the output */
  groundedNodeIds: Id[]
}

/**
 * How long an entry must be kept, and why.
 *
 * Retention is a property of the record rather than a global setting because
 * one workspace's regimes can differ: an EU AI Act log has a six-month floor,
 * a SOX ITGC record is held seven years, and a GxP record is held for the life
 * of the product. Storing the class on the entry lets one chain satisfy all
 * three without the shortest window governing the longest obligation.
 */
export type RetentionClass = 'standard' | 'sox' | 'gxp' | 'ai_act' | 'permanent'

export interface AuditEntry {
  id: Id
  seq: number
  at: string
  action: AuditAction
  actor: string
  actorType: 'human' | 'agent' | 'system'
  requirementRef: string | null
  summary: string
  /** Hash chain — each entry commits to the previous one */
  hash: string
  prevHash: string
  costUsd: number
  /** Wall-clock attributable to this step */
  durationSeconds: number

  /* ---------------------------------------------- ALCOA+ / Part 11 (Phase B) */

  /** Field-level before/after. Empty for entries that create rather than edit. */
  changes?: FieldChange[]
  /**
   * Why the change was made.
   *
   * Part 11 asks for this explicitly. It is optional in the type because
   * system-generated entries have no author to ask, not because a human edit
   * may omit it.
   */
  reason?: string

  /* ------------------------------------------------- AI provenance (Phase C) */

  /** Present when an agent or model produced this entry */
  ai?: AiProvenance

  /* --------------------------------------------------- retention (Phase D) */

  retention: RetentionClass
  /** Suspends deletion regardless of retention class, e.g. for litigation */
  legalHold: boolean
  /** Target workspace so retention and segregation can be scoped */
  workspaceId?: Id
}

/**
 * The outcome of recomputing the chain.
 *
 * A product that claims tamper-evidence has to be able to show the claim
 * failing. Returning the first broken sequence number rather than a bare
 * boolean is what makes the failure investigable.
 */
export interface ChainVerification {
  valid: boolean
  entriesChecked: number
  verifiedAt: string
  /** Seq of the first entry whose hash does not match its content */
  firstBrokenSeq: number | null
  /** Human-readable account of what broke */
  detail: string
}

/* ------------------------------------------------- human oversight (Art. 14) */

/**
 * Evidence that a human decision was meaningful rather than nominal.
 *
 * EU AI Act Art. 14 requires effective human oversight of high-risk systems.
 * A signature proves someone clicked; it does not prove they looked. Recording
 * how long the reviewer spent, what they opened, and whether they went along
 * with the AI is what separates oversight from rubber-stamping — and the
 * override rate is the metric supervisory authorities ask for first.
 */
export interface HumanOversightRecord {
  /** Seconds between opening the package and deciding */
  reviewDurationSeconds: number
  /** Evidence artifacts the reviewer actually opened */
  artifactsOpened: Id[]
  artifactsAvailable: number
  /** What the system recommended, if it recommended anything */
  aiRecommendation: 'approve' | 'reject' | 'none'
  humanDecision: 'approve' | 'reject'
  /** True when the human went against the recommendation */
  overridden: boolean
  /** Required when overriding — the reviewer's stated reasoning */
  overrideRationale: string | null
}

/* --------------------------------------------------------- AI incidents */

/**
 * An incident in *Meridian's own AI*, not in the system under test.
 *
 * Defects record what the tested software got wrong. Nothing recorded what the
 * platform got wrong — a fabricated citation, an impact analysis that missed a
 * breaking change, an agent that acted outside advisory mode. NIST AI RMF asks
 * for incident disclosure and EU AI Act Art. 73 obliges providers to report
 * serious incidents within fixed deadlines, so this needs to be a first-class
 * register rather than a support ticket.
 */
export type IncidentKind =
  | 'hallucinated_citation'
  | 'missed_impact'
  | 'false_impact'
  | 'unauthorised_action'
  | 'evidence_mismatch'
  | 'model_drift'
  | 'policy_bypass'
  | 'data_leakage'

export type IncidentSeverity = 'critical' | 'major' | 'minor'

export type IncidentStatus =
  | 'open'
  | 'investigating'
  | 'contained'
  | 'resolved'
  | 'disclosed'

export interface AiIncident {
  id: Id
  ref: string
  kind: IncidentKind
  severity: IncidentSeverity
  status: IncidentStatus
  title: string
  /** What happened, in the reporter's words */
  description: string
  detectedAt: string
  detectedBy: string
  /** How it surfaced — a person noticing is a weaker control than a probe */
  detectionMethod: 'human_review' | 'automated_probe' | 'policy_engine' | 'external_report'
  /** Artefacts the incident touched, so blast radius is stated not guessed */
  affectedRequirementRefs: string[]
  affectedArtifactIds: Id[]
  /** The model implicated, when the incident is model-attributable */
  model: string | null
  modelVersion: string | null
  /**
   * Whether this meets the EU AI Act Art. 73 serious-incident bar. Recorded as
   * a judgement with a rationale rather than derived from severity, because
   * reportability is a legal test, not a severity threshold.
   */
  reportable: boolean
  reportableRationale: string
  /** Set once a regulator or affected party has been told */
  disclosedAt: string | null
  disclosedTo: string | null
  /** What stopped it recurring */
  correctiveAction: string | null
  resolvedAt: string | null
  notes: { at: string; by: string; text: string }[]
}

/* ------------------------------------------------------------- policy */

export interface Policy {
  id: Id
  ref: string
  name: string
  description: string
  severity: 'blocking' | 'warning'
  scope: string
  enabled: boolean
  triggeredCount: number
}

/* ------------------------------------------------------------ analytics */

export interface CostPoint {
  date: string
  llmUsd: number
  computeUsd: number
  changes: number
}

export interface CycleTimePoint {
  week: string
  /** This org's own historical baseline, in hours */
  baselineHours: number
  meridianHours: number
  changes: number
}

export interface DoraMetric {
  label: string
  value: string
  deltaPct: number
  direction: 'up_good' | 'down_good'
  detail: string
}

export interface ModelSpend {
  model: string
  costUsd: number
  calls: number
  share: number
}

/** One day of extraction activity. */
export interface RunPoint {
  date: string
  runs: number
  failed: number
  nodes: number
  /** Mean seconds per run that day — a total would hide a single slow run. */
  avgSeconds: number
}

export interface RunTotals {
  runs: number
  succeeded: number
  failed: number
  nodes: number
  totalSeconds: number
  /**
   * Runs that have finished. Kept separate from `runs` because a run still in
   * flight has no duration, and averaging over all of them understates it.
   */
  timedRuns: number
  avgSeconds: number
  llmUsd: number
  computeUsd: number
  tokensIn: number
  tokensOut: number
  operations: number
  days: number
}

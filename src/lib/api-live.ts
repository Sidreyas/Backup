/**
 * The real backend client.
 *
 * Implements the same surface as the mock in `api.ts` against the FastAPI
 * server. `api.ts` chooses between the two at import time, so components never
 * learn which one they are talking to.
 *
 * Three functions here deliberately do **not** call the backend, because the
 * backend does not implement them yet: `crawlSite`, `generateCasesFromCrawl`
 * and `runProposedCases`. Meridian cannot drive a browser, and pretending
 * otherwise by returning invented pages or a fabricated pass would put
 * unfounded claims into a product whose entire value is that its claims are
 * founded. They throw a clear `NotImplementedYet` instead, and the UI shows
 * that rather than a lie.
 */
import { ApiError, http, setActor } from './http'
import type {
  AiIncident,
  ApprovalPackage,
  AuditEntry,
  ChainVerification,
  ChatMessage,
  CostPoint,
  CrawlResult,
  CycleTimePoint,
  Defect,
  DefectSeverity,
  DefectStatus,
  DoraMetric,
  GraphBuild,
  GraphEdge,
  GraphNode,
  HumanOversightRecord,
  ImpactAnalysis,
  IncidentKind,
  IncidentSeverity,
  IncidentStatus,
  IngestJob,
  KnowledgeSource,
  ModelSpend,
  RunPoint,
  RunTotals,
  Policy,
  Project,
  Requirement,
  SystemKind,
  TestCase,
  TestClosure,
  TestEnvironment,
  TestExecution,
  TestPlan,
  TestPriority,
  TestRun,
  TestSuite,
  Workspace,
} from './types'
import type { Connection, ConnectorDefinition, SyncCadence } from './mock-connectors'

export { ApiError, setActor }

/**
 * One value a connector needs before it can run.
 *
 * `authMethods` scopes a field to particular authentication choices — Workday
 * asks for a refresh token or a private key or a password depending on which
 * method the customer's security team approved, and showing all three at once
 * would present two different fields both labelled "Integration System User".
 */
export interface CredentialField {
  id: string
  label: string
  help: string
  kind: 'text' | 'password' | 'textarea' | 'select'
  required: boolean
  placeholder: string
  authMethods: string[]
  options: { id: string; label: string; description: string }[]
}

/** A step the customer performs in their own system before connecting. */
export interface SetupStep {
  id: string
  /**
   * The task name exactly as it appears in the source system's search.
   *
   * Null when the step is a setting on a screen you are already on rather than
   * something you navigate to — Azure DevOps scope selection, for instance.
   */
  task: string | null
  title: string
  /** One or two words, for the stepper label. Falls back to `title`. */
  short?: string
  detail: string
  why: string
  /** Commonly missed, and its absence produces a misleading error. */
  critical?: boolean
  optional?: boolean
}

/** An artefact the customer must build — Workday's discovery reports. */
export interface RequiredArtifact {
  id: string
  reportName: string
  title: string
  unlocks: string
  dataSource: string
  businessObject: string
  whyReport: string
  produces: string
  priority: number
  notes: string[]
  fields: { name: string; description: string; required: boolean }[]
}

/**
 * How to build an artefact in the source system.
 *
 * Shared by every artefact rather than repeated per one, because for Workday's
 * report pack the procedure is identical and only the name, data source and
 * columns differ.
 */
export interface ArtifactBuildStep {
  id: string
  /** The task to search for, when the step starts with one. */
  task: string | null
  title: string
  detail: string
  /** What goes wrong if this is skipped. */
  symptom: string | null
  critical?: boolean
}

export interface ConnectorSetup {
  id: string
  name: string
  vendor: string
  implemented: boolean
  authMethods: string[]
  credentialFields: CredentialField[]
  scopes: {
    id: string
    label: string
    description: string
    required: boolean
    writes: boolean
  }[]
  setupSteps: SetupStep[]
  requiredArtifacts: RequiredArtifact[]
  artifactBuildSteps: ArtifactBuildStep[]
  /** Stated before a customer invests a day in setup, not after. */
  limitations: string[]
  /** False when the server has no encryption key and cannot store credentials. */
  secretsConfigured: boolean
}

/**
 * An administrator-captured browser session.
 *
 * Deliberately does not carry the session. Some enterprise configuration —
 * field validation, conditional visibility, the lookup tables behind a leave
 * calculation — exists only on screens, and reading it needs a browser that is
 * already signed in. A human signs in with the capture tool; Meridian keeps
 * the resulting cookies, never the password, and they expire.
 *
 * `expiringSoon` exists so an admin re-captures *before* a long extraction
 * rather than halfway through one.
 */
export interface BrowserSessionStatus {
  present: boolean
  capturedBy: string
  capturedAt: string
  expiresAt: string
  lastUsedAt: string
  remainingSeconds: number
  expired: boolean
  expiringSoon: boolean
  message: string
}

/** Raised for a capability the backend has not built. */
export class NotImplementedYet extends Error {
  constructor(what: string) {
    super(
      `${what} is not implemented in the backend yet. Nothing was fabricated in its place.`,
    )
    this.name = 'NotImplementedYet'
  }
}

export const liveApi = {
  /* ------------------------------------------------------------ org scope */

  getWorkspaces: () => http.get<Workspace[]>('/workspaces'),
  getProjects: () => http.get<Project[]>('/projects'),

  /* -------------------------------------------------------------- sources */

  getSources: () => http.get<KnowledgeSource[]>('/sources'),
  getConnectors: () => http.get<ConnectorDefinition[]>('/connectors'),
  getConnections: () => http.get<Connection[]>('/connections'),

  getConnection: (connectionId: string) =>
    http.get<Connection & { settings: Record<string, unknown> }>(
      `/connections/${connectionId}`,
    ),

  /**
   * Everything needed to walk someone through connecting a system.
   *
   * Served by the backend rather than hardcoded here: the help text explaining
   * where to find a Workday token endpoint belongs next to the code that knows
   * why the field exists, and a new connector should not need a frontend
   * change to become connectable.
   */
  getConnectorSetup: (connectorId: string) =>
    http.get<ConnectorSetup>(`/connectors/${connectorId}/setup`),

  /** Register a connection, supplying whatever credentials it declared. */
  createConnection: (input: {
    connectorId: string
    label: string
    authMethod: string
    grantedScopes: string[]
    cadence: SyncCadence
    owner: string
    values: Record<string, string>
  }) => http.post<Connection>('/connections', input),

  updateConnectionCredentials: (connectionId: string, values: Record<string, string>) =>
    http.patch<Connection & { settings: Record<string, unknown> }>(
      `/connections/${connectionId}/credentials`,
      values,
    ),

  /**
   * Whether an administrator-captured browser session exists.
   *
   * Never returns the session itself — it is a bearer credential, and putting
   * one on a screen would be strictly worse than not showing it. Presence,
   * who captured it and when it lapses are all the UI needs.
   */
  getBrowserSession: (connectionId: string) =>
    http.get<BrowserSessionStatus>(`/connections/${connectionId}/browser-session`),

  /** End the current session. History is kept; the session stops working. */
  revokeBrowserSession: (connectionId: string) =>
    http.delete<BrowserSessionStatus>(`/connections/${connectionId}/browser-session`),

  /**
   * What this connection can extract *right now*.
   *
   * Distinct from the connector's declared capabilities: this reflects the
   * scopes actually granted and, for Workday, which discovery reports exist in
   * the tenant. It is how the UI can say "business process logic is not
   * reachable yet" instead of silently producing a thin graph.
   */
  getConnectionCapabilities: (connectionId: string) =>
    http.get<{
      configured: boolean
      capabilities: {
        id: string
        label: string
        layer: string
        nodeKinds: string[]
        requiresScopes: string[]
      }[]
    }>(`/connections/${connectionId}/capabilities`),

  /**
   * Test without changing anything.
   *
   * Returns which scopes actually worked, not just a pass/fail: a Workday
   * token that can read organisations but not integration systems produces a
   * partial graph, and the operator should learn that here rather than from a
   * thin graph three screens later.
   */
  testConnection: (connectionId: string) =>
    http.post<{
      ok: boolean
      message: string
      effectiveScopes?: string[]
      missingScopes?: string[]
    }>(`/connections/${connectionId}/test`),

  syncConnection: async (connectionId: string): Promise<Connection> => {
    const result = await http.post<{ connection: Connection }>(
      `/connections/${connectionId}/sync`,
    )
    return result.connection
  },

  disconnectConnection: (connectionId: string) =>
    http.post<Connection>(`/connections/${connectionId}/disconnect`),

  setConnectionCadence: (connectionId: string, cadence: SyncCadence) =>
    http.patch<Connection>(`/connections/${connectionId}/cadence`, { cadence }),

  /* ---------------------------------------------------------------- graph */

  getGraph: () => http.get<{ nodes: GraphNode[]; edges: GraphEdge[] }>('/graph'),

  /** Confirm a proposed link — the human judgement the graph waits for. */
  confirmEdge: (edgeId: string) => http.post<GraphEdge>(`/graph/edges/${edgeId}/confirm`),

  searchGraph: (query: string) =>
    http.get<GraphNode[]>(`/graph/search?q=${encodeURIComponent(query)}`),

  getIngestJobs: () => http.get<IngestJob[]>('/ingest-jobs'),
  getGraphBuild: () => http.get<GraphBuild | null>('/graph-build'),

  /* --------------------------------------------------------- requirements */

  getRequirements: () => http.get<Requirement[]>('/requirements'),
  getRequirement: (id: string) => http.get<Requirement | null>(`/requirements/${id}`),

  createRequirement: (input: {
    title: string
    summary: string
    platform: string
    systemKind: SystemKind
    priority: TestPriority
  }) => http.post<Requirement>('/requirements', input),

  setRequirementStage: (id: string, stage: Requirement['stage'], reason?: string) =>
    http.patch<Requirement>(`/requirements/${id}/stage`, { stage, reason }),

  getThread: (requirementId: string) =>
    http.get<ChatMessage[]>(`/requirements/${requirementId}/thread`),

  sendMessage: (requirementId: string, text: string) =>
    http.post<ChatMessage>(`/requirements/${requirementId}/messages`, { text }),

  /* --------------------------------------------------------------- impact */

  getImpactAnalyses: () => http.get<ImpactAnalysis[]>('/impact'),
  getImpact: (requirementId: string) =>
    http.get<ImpactAnalysis | null>(`/requirements/${requirementId}/impact`),

  generateImpact: (requirementId: string, seedNodeIds?: string[], maxDepth = 3) =>
    http.post<ImpactAnalysis>(`/requirements/${requirementId}/impact`, {
      seedNodeIds,
      maxDepth,
    }),

  /* ----------------------------------------------------------------- STLC */

  getTestPlans: () => http.get<TestPlan[]>('/test-plans'),
  getTestPlan: (id: string) => http.get<TestPlan | null>(`/test-plans/${id}`),

  generateTestPlan: (requirementId: string, generateCases = true) =>
    http.post<{ plan: TestPlan; cases: TestCase[] }>('/test-plans/generate', {
      requirementId,
      generateCases,
    }),

  setTestPlanState: (id: string, state: TestPlan['state'], reason?: string) =>
    http.patch<TestPlan>(`/test-plans/${id}/state`, { state, reason }),

  getTestCases: () => http.get<TestCase[]>('/test-cases'),

  saveTestCase: (updated: TestCase, reason?: string) =>
    http.patch<TestCase>(`/test-cases/${updated.id}`, {
      title: updated.title,
      expectedResult: updated.expectedResult,
      priority: updated.priority,
      level: updated.level,
      type: updated.type,
      automatable: updated.automatable,
      testData: updated.testData,
      preconditions: updated.preconditions,
      steps: updated.steps,
      reason,
    }),

  setTestCaseState: (id: string, state: TestCase['state'], reason?: string) =>
    http.patch<TestCase>(`/test-cases/${id}/state`, { state, reason }),

  getTestSuites: () => http.get<TestSuite[]>('/test-suites'),

  createTestSuite: (input: { name: string; description: string; caseIds: string[] }) =>
    http.post<TestSuite>('/test-suites', input),

  updateTestSuite: (
    id: string,
    patch: { name?: string; description?: string; caseIds?: string[] },
  ) =>
    http.patch<TestSuite>(`/test-suites/${id}`, {
      name: patch.name ?? '',
      description: patch.description ?? '',
      caseIds: patch.caseIds ?? [],
    }),

  deleteTestSuite: (id: string) => http.delete<void>(`/test-suites/${id}`),

  getTestEnvironments: () => http.get<TestEnvironment[]>('/test-environments'),
  getTestExecutions: () => http.get<TestExecution[]>('/test-executions'),
  getTestExecution: (id: string) => http.get<TestExecution | null>(`/test-executions/${id}`),

  /**
   * Record an execution.
   *
   * `results` carries outcomes from whatever actually ran the cases. Passing
   * none is legitimate and produces `skipped` results — the honest state for
   * "nothing ran this" — rather than a pass nobody observed.
   */
  runTestExecution: (input: {
    caseIds: string[]
    environmentId: string
    suiteName: string
    requirementId?: string | null
    planId?: string | null
    suiteId?: string | null
    results?: {
      caseId: string
      status: string
      actual: string
      durationSeconds?: number
      deviation?: string | null
      attempts?: number
      artifacts?: { kind: string; label: string; sizeLabel: string; sha256: string }[]
    }[]
    retestDefectIds?: string[]
  }) => http.post<TestExecution>('/test-executions', input),

  getTestRuns: () => http.get<TestRun[]>('/test-runs'),
  getTestClosures: () => http.get<TestClosure[]>('/test-closures'),
  getTestClosure: (requirementId: string) =>
    http.get<TestClosure | null>(`/requirements/${requirementId}/closure`),

  /* -------------------------------------------------------------- defects */

  getDefects: (requirementId?: string) =>
    http.get<Defect[]>(
      requirementId ? `/defects?requirementId=${encodeURIComponent(requirementId)}` : '/defects',
    ),

  raiseDefect: (input: {
    requirementId: string
    executionId: string | null
    caseId: string | null
    caseRef: string | null
    title: string
    expected: string
    actual: string
    severity: DefectSeverity
    owner: string
    affectedNodeIds?: string[]
  }) => http.post<Defect>('/defects', input),

  setDefectStatus: (id: string, status: DefectStatus, note?: string) =>
    http.patch<Defect>(`/defects/${id}/status`, { status, note }),

  /* ------------------------------------------------------------ approvals */

  getApprovals: () => http.get<ApprovalPackage[]>('/approvals'),

  /** What stands between a gate and an approval, before anyone tries. */
  getGateBlockers: (packageId: string, gateId: string) =>
    http.get<{ blocked: boolean; reasons: string[] }>(
      `/approvals/${packageId}/gates/${gateId}/blockers`,
    ),

  /**
   * Decide a gate.
   *
   * Throws `ApiError` with `reasons` when the backend refuses an approval that
   * policy forbids — the refusal is the feature, so it must reach the user
   * intact rather than being reported as a generic failure.
   */
  decideGate: (input: {
    packageId: string
    gateId: string
    decision: 'approved' | 'rejected'
    comment: string
    oversight: HumanOversightRecord
  }) =>
    http.post<ApprovalPackage>(
      `/approvals/${input.packageId}/gates/${input.gateId}/decide`,
      {
        decision: input.decision,
        comment: input.comment,
        reviewDurationSeconds: input.oversight.reviewDurationSeconds,
        artifactsOpened: input.oversight.artifactsOpened,
        artifactsAvailable: input.oversight.artifactsAvailable,
        aiRecommendation: input.oversight.aiRecommendation,
        overrideRationale: input.oversight.overrideRationale,
      },
    ),

  /* ---------------------------------------------------------------- audit */

  getAudit: () => http.get<AuditEntry[]>('/audit'),
  verifyAuditChain: () => http.post<ChainVerification>('/audit/verify'),
  simulateTamper: async (seq: number) => {
    const result = await http.post<{ ok: boolean }>(`/audit/simulate-tamper?seq=${seq}`)
    return result.ok
  },

  /**
   * Restoring a tampered chain is not something a real ledger supports.
   *
   * The mock could reset because its chain lived in memory. Server-side,
   * re-hashing tampered content would launder the tamper into a valid-looking
   * chain — precisely the attack the chain exists to prevent. Re-seed the
   * database instead.
   */
  resetChain: async (): Promise<void> => {
    throw new NotImplementedYet(
      'Resetting the audit chain (re-hashing tampered entries would defeat the chain)',
    )
  },

  /* ------------------------------------------------------------ incidents */

  getIncidents: () => http.get<AiIncident[]>('/incidents'),

  raiseIncident: (input: {
    kind: IncidentKind
    severity: IncidentSeverity
    title: string
    description: string
    affectedRequirementRefs: string[]
    reportable: boolean
    reportableRationale: string
  }) => http.post<AiIncident>('/incidents', input),

  setIncidentStatus: (id: string, status: IncidentStatus, note?: string) =>
    http.patch<AiIncident>(`/incidents/${id}/status`, { status, note }),

  /* ------------------------------------------------------------- policies */

  getPolicies: () => http.get<Policy[]>('/policies'),

  /* ------------------------------------------------------------ analytics */

  getAnalytics: (days = 30) =>
    http.get<{
      windowDays: number
      runs: RunPoint[]
      runTotals: RunTotals
      cost: CostPoint[]
      cycleTime: CycleTimePoint[]
      dora: DoraMetric[]
      modelSpend: ModelSpend[]
    }>(`/analytics?days=${days}`),

  /* -------------------------------------------------------------- evidence */

  exportEvidencePack: (input: { requirementRef?: string | null; scope: string }) =>
    http.post<{ filename: string; content: string; manifestHash: string }>(
      '/evidence/export',
      input,
    ),

  /* ------------------------------------------------- not built server-side */

  /**
   * These three would require Meridian to drive a real browser against a real
   * application. It cannot yet. Returning invented pages, invented cases or a
   * fabricated pass would be the single most damaging thing this product could
   * do, so they fail loudly instead.
   */
  crawlSite: async (_startUrl: string): Promise<CrawlResult> => {
    throw new NotImplementedYet('Site crawling')
  },

  generateCasesFromCrawl: async (_crawl: CrawlResult) => {
    throw new NotImplementedYet('Generating cases from a crawl')
  },

  runProposedCases: async () => {
    throw new NotImplementedYet('Running proposed cases against a live site')
  },
}

/**
 * The data layer. Components talk to this module and nothing else.
 *
 * Meridian now has a real backend, so `api` below is a **hybrid**: every
 * endpoint the server implements is served live, and the handful it does not
 * yet implement falls back to the fixtures in this file.
 *
 * The split is deliberate and visible at the bottom of the file rather than
 * hidden behind a flag. Two categories remain mocked:
 *
 *   - **Genuinely unbuilt capabilities** — site crawling, generating cases
 *     from a crawl, running proposed cases. These need Meridian to drive a
 *     browser against a live application, which it cannot do yet. The live
 *     client throws `NotImplementedYet` for these; the mock is kept so the
 *     chat page still demonstrates the intended flow.
 *   - **Screens not yet migrated** — pages whose backend endpoints exist but
 *     whose UI still reads fixture shapes.
 *
 * `VITE_USE_MOCK_API=1` forces everything back to fixtures, which is useful
 * for UI work without a running backend.
 */
import { liveApi, NotImplementedYet } from './api-live'
import {
  APPROVAL_PACKAGES,
  GRAPH_BUILD,
  INGEST_JOBS,
  AUDIT_ENTRIES,
  CHAT_THREAD,
  CURRENT_USER,
  COST_SERIES,
  CYCLE_TIME_SERIES,
  DORA_METRICS,
  GRAPH_EDGES,
  GRAPH_NODES,
  IMPACT_ANALYSES,
  MODEL_SPEND,
  RUN_SERIES,
  RUN_TOTALS,
  POLICIES,
  REQUIREMENTS,
  SOURCES,
  TEST_RUNS,
} from './mock-data'
import {
  CONNECTIONS,
  CONNECTORS,
  type Connection,
  type ConnectorDefinition,
  type SyncCadence,
} from './mock-connectors'
import {
  DEFECTS,
  TEST_CASES,
  TEST_CLOSURES,
  TEST_ENVIRONMENTS,
  TEST_EXECUTIONS,
  TEST_PLANS,
  TEST_SUITES,
} from './mock-stlc'
import type {
  AiIncident,
  CrawlResult,
  ProposedCase,
  ApprovalPackage,
  CaseResult,
  ChainVerification,
  Defect,
  DefectSeverity,
  DefectStatus,
  GraphBuild,
  HumanOversightRecord,
  IncidentKind,
  IncidentSeverity,
  IncidentStatus,
  IngestJob,
  AuditEntry,
  ChatMessage,
  CostPoint,
  CycleTimePoint,
  DoraMetric,
  GraphEdge,
  GraphNode,
  ImpactAnalysis,
  KnowledgeSource,
  ModelSpend,
  RunPoint,
  RunTotals,
  Policy,
  Requirement,
  RunStatus,
  SystemKind,
  TestCase,
  TestClosure,
  TestEnvironment,
  TestExecution,
  TestPlan,
  TestPriority,
  TestRun,
  TestSuite,
} from './types'
import {
  getEntries,
  record,
  rehashFixture,
  seedLedger,
  sha256,
  simulateTamper,
  verifyChain,
} from './audit'
import { ACTIVE_MODEL, diffFields } from './provenance'
import { AI_INCIDENTS } from './mock-incidents'

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * Turn the hand-authored fixture into a genuinely valid chain.
 *
 * The fixture's hashes were written by hand and do not verify. Recomputing
 * them once at boot means the integrity banner on the audit page is reporting
 * a real result from the first render, rather than a claim that would fail the
 * moment anyone checked it.
 */
let ledgerReady: Promise<void> | null = null
function ensureLedger(): Promise<void> {
  if (!ledgerReady) {
    ledgerReady = rehashFixture(AUDIT_ENTRIES).then(seedLedger)
  }
  return ledgerReady
}

/** Host only, for prose. Falls back to the raw string on an unparseable URL. */
function safeHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

const trimSlash = (u: string) => u.replace(/\/+$/, '')

/**
 * Does this message look like a request to generate test cases?
 *
 * Deliberately narrow. A loose match would hijack ordinary questions about
 * testing ("what does this test cover?") and answer them by generating cases,
 * which is worse than not matching at all.
 */
export function looksLikeGenerateRequest(text: string): boolean {
  const t = text.toLowerCase()
  const verb = /\b(create|generate|write|draft|set ?up|build|suggest)\b/.test(t)
  const noun = /\b(test cases?|tests|test suite|scenarios?|coverage)\b/.test(t)
  return verb && noun
}

/**
 * Does this message look like a request to run the cases that exist?
 *
 * Kept separate from `looksLikeGenerateRequest` and checked first, because
 * "run the tests" contains no generate verb and "create and run tests" should
 * generate rather than run — there is nothing to run yet at that point.
 */
export function looksLikeRunRequest(text: string): boolean {
  const t = text.toLowerCase()
  const verb = /\b(run|execute|kick ?off|start)\b/.test(t)
  const noun = /\b(tests?|test cases?|test run|suite|them|all of them)\b/.test(t)
  return verb && noun
}

/** The first http(s) URL in a message, if any. */
export function extractUrl(text: string): string | null {
  const m = text.match(/https?:\/\/[^\s<>"')]+/i)
  return m ? m[0] : null
}

/** Deep clone so callers can never mutate the module-level fixtures. */
const clone = <T>(value: T): T => structuredClone(value)

async function resolve<T>(value: T, ms = 320): Promise<T> {
  await delay(ms)
  return clone(value)
}

const mockApi = {
  getSources: () => resolve<KnowledgeSource[]>(SOURCES, 380),

  /* ------------------------------------------------------------ connectors */

  getConnectors: () => resolve<ConnectorDefinition[]>(CONNECTORS, 260),
  getConnections: () => resolve<Connection[]>(CONNECTIONS, 300),

  /**
   * Test a connection without changing it.
   *
   * Separate from connecting because "does this still work" is the question
   * people actually have, and answering it should never risk the credentials
   * that are already working. A connector in error stays in error — the test
   * reports, it does not repair.
   */
  testConnection: async (connectionId: string): Promise<{ ok: boolean; message: string }> => {
    await delay(900)
    const cn = CONNECTIONS.find((c) => c.id === connectionId)
    if (!cn) return { ok: false, message: 'Connection not found.' }
    cn.lastTestedAt = new Date().toISOString()
    return cn.status === 'error'
      ? { ok: false, message: cn.error ?? 'The external system rejected the credentials.' }
      : { ok: true, message: `Reached ${cn.label}. Credentials and scopes are valid.` }
  },

  /**
   * Connect a new instance of a connector.
   *
   * Required scopes are granted implicitly — a connector without them cannot
   * do its job, so offering them as a choice would be theatre. Optional ones
   * are whatever the caller passed.
   */
  connectConnector: async (input: {
    connectorId: string
    label: string
    authMethod: Connection['authMethod']
    grantedScopes: string[]
    cadence: SyncCadence
    owner: string
  }): Promise<Connection> => {
    await delay(1100)
    const def = CONNECTORS.find((c) => c.id === input.connectorId)
    if (!def) throw new Error('Unknown connector')

    const required = def.scopes.filter((s) => s.required).map((s) => s.id)
    const created: Connection = {
      id: `cn-${Date.now().toString(36)}`,
      connectorId: input.connectorId,
      label: input.label.trim() || def.name,
      // A new connection starts indexing, not connected: claiming it is ready
      // before the first sync would be a lie the very next screen exposes.
      status: 'indexing',
      authMethod: input.authMethod,
      grantedScopes: Array.from(new Set([...required, ...input.grantedScopes])),
      cadence: input.cadence,
      lastSyncedAt: null,
      nextSyncAt: null,
      owner: input.owner,
      connectedBy: CURRENT_USER.name,
      connectedAt: new Date().toISOString(),
      recordCount: 0,
      lastTestedAt: new Date().toISOString(),
    }
    CONNECTIONS.unshift(created)
    return clone(created)
  },

  /** Register a connector the customer built themselves. */
  createCustomConnector: async (input: {
    name: string
    vendor: string
    description: string
    authMethod: Connection['authMethod']
    provides: string[]
  }): Promise<ConnectorDefinition> => {
    await delay(800)
    const created: ConnectorDefinition = {
      id: `cx-custom-${Date.now().toString(36)}`,
      name: input.name.trim(),
      vendor: input.vendor.trim() || 'Internal',
      category: 'custom',
      kind: 'platform',
      description: input.description.trim(),
      authMethods: [input.authMethod],
      provides: input.provides.filter(Boolean),
      custom: true,
      scopes: [
        {
          id: 'read.metadata',
          label: 'Read configuration metadata',
          description: 'Whatever your endpoint exposes as configuration.',
          required: true,
          writes: false,
        },
      ],
    }
    CONNECTORS.push(created)
    return clone(created)
  },

  setConnectionCadence: async (connectionId: string, cadence: SyncCadence): Promise<Connection> => {
    await delay(320)
    const cn = CONNECTIONS.find((c) => c.id === connectionId)
    if (!cn) throw new Error('Connection not found')
    cn.cadence = cadence
    return clone(cn)
  },

  /**
   * Disconnect, keeping indexed data.
   *
   * Deliberately not a delete: evidence already gathered under this connection
   * is cited by approvals that have been signed. Removing it would rewrite
   * history to make a past decision unverifiable.
   */
  disconnectConnection: async (connectionId: string): Promise<Connection> => {
    await delay(600)
    const cn = CONNECTIONS.find((c) => c.id === connectionId)
    if (!cn) throw new Error('Connection not found')
    cn.status = 'disconnected'
    cn.nextSyncAt = null
    return clone(cn)
  },

  syncConnection: async (connectionId: string): Promise<Connection> => {
    await delay(1200)
    const cn = CONNECTIONS.find((c) => c.id === connectionId)
    if (!cn) throw new Error('Connection not found')
    if (cn.status === 'error') return clone(cn)
    cn.status = 'connected'
    cn.lastSyncedAt = new Date().toISOString()
    return clone(cn)
  },
  getGraph: () =>
    resolve<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
      { nodes: GRAPH_NODES, edges: GRAPH_EDGES },
      420,
    ),
  getRequirements: () => resolve<Requirement[]>(REQUIREMENTS, 300),
  getRequirement: async (id: string): Promise<Requirement | null> =>
    resolve(REQUIREMENTS.find((r) => r.id === id) ?? null, 240),
  getThread: async (requirementId: string): Promise<ChatMessage[]> =>
    resolve(CHAT_THREAD[requirementId] ?? [], 340),

  /**
   * Create a requirement and open its discussion.
   *
   * Previously "Start discussion" navigated to req-1 regardless of what was
   * typed, so every new requirement silently became someone else's. This
   * writes a real record, mints a ref, and seeds a thread from the user's own
   * words so the discussion starts from what they actually wrote.
   */
  createRequirement: async (input: {
    title: string
    summary: string
    platform: string
    systemKind: SystemKind
    priority: TestPriority
  }): Promise<Requirement> => {
    await delay(520)

    /* Refs continue the existing series rather than restarting from 1. */
    const highest = REQUIREMENTS.reduce((max, r) => {
      const n = Number(r.ref.replace(/^\D+/, ''))
      return Number.isFinite(n) && n > max ? n : max
    }, 1000)
    const now = new Date().toISOString()
    const id = `req-${Math.random().toString(36).slice(2, 8)}`

    const requirement: Requirement = {
      id,
      ref: `MER-${highest + 1}`,
      title: input.title,
      summary: input.summary || input.title,
      /* A new requirement is in discussion — nothing has been analysed yet. */
      stage: 'discussing',
      requestedBy: CURRENT_USER.name,
      requestedByRole: CURRENT_USER.role,
      createdAt: now,
      updatedAt: now,
      platform: input.platform,
      systemKind: input.systemKind,
      priority: input.priority,
      /* Nothing is claimed impacted until the graph has been consulted. */
      impactedNodeIds: [],
      estimatedCostUsd: 0,
      actualCostUsd: 0,
      riskLevel: 'medium',
    }

    REQUIREMENTS.unshift(requirement)

    await ensureLedger()
    await record({
      action: 'requirement.created',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: requirement.ref,
      summary: `Requirement raised against ${input.platform} at ${input.priority} priority.`,
      durationSeconds: 45,
      workspaceId: 'ws-acme',
    })

    /*
     * Seed the thread with the user's description and an opening reply that
     * asks rather than asserts. Fabricating an impact analysis here would put
     * claims in the record that nothing has actually grounded.
     */
    CHAT_THREAD[id] = [
      {
        id: `${id}-m1`,
        role: 'user',
        at: now,
        content: input.summary ? `${input.title}\n\n${input.summary}` : input.title,
      },
      {
        id: `${id}-m2`,
        role: 'assistant',
        at: now,
        content: `Before I ground this against ${input.platform}, two things I need from you: which population is affected, and whether any existing approval or audit control is expected to change. I will not propose an impact analysis until I can cite the configuration behind it.`,
        citations: [],
        costUsd: 0,
      },
    ]

    return clone(requirement)
  },

  /** Persist a stage change from the requirements table. */
  setRequirementStage: async (
    id: string,
    stage: Requirement['stage'],
    reason?: string,
  ): Promise<Requirement | null> => {
    await delay(280)
    const i = REQUIREMENTS.findIndex((r) => r.id === id)
    if (i < 0) return null
    const before = REQUIREMENTS[i]
    const after = { ...before, stage, updatedAt: new Date().toISOString() }
    REQUIREMENTS[i] = after

    await ensureLedger()
    await record({
      action: 'requirement.stage_changed',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: after.ref,
      summary: `Stage moved from ${before.stage} to ${stage}.`,
      changes: diffFields(before, after, [{ field: 'stage', label: 'Stage' }]),
      reason,
      workspaceId: 'ws-acme',
    })

    return clone(REQUIREMENTS[i])
  },
  getImpact: async (requirementId: string): Promise<ImpactAnalysis | null> =>
    resolve(IMPACT_ANALYSES[requirementId] ?? null, 400),
  /** Every analysis that exists. A requirement still in discussion has none. */
  getImpactAnalyses: () => resolve<ImpactAnalysis[]>(Object.values(IMPACT_ANALYSES), 380),
  getTestRuns: () => resolve<TestRun[]>(TEST_RUNS, 360),
  getApprovals: () => resolve<ApprovalPackage[]>(APPROVAL_PACKAGES, 340),
  /** The live ledger, not the raw fixture — everything written this session is here. */
  getAudit: async (): Promise<AuditEntry[]> => {
    await ensureLedger()
    await delay(380)
    return clone(getEntries())
  },

  /**
   * Recompute the chain and report the result.
   *
   * Exposed as its own call because verification is an action with a cost and
   * an outcome, not a property to be read off the page. It is also itself
   * audited when it fails — a failed integrity check is exactly the kind of
   * event the record should contain.
   */
  verifyAuditChain: async (): Promise<ChainVerification> => {
    await ensureLedger()
    await delay(520)
    const result = await verifyChain()
    if (!result.valid) {
      await record({
        action: 'chain.verified',
        actor: 'Meridian Integrity Monitor',
        actorType: 'system',
        summary: `Chain verification FAILED at entry #${result.firstBrokenSeq}.`,
        workspaceId: 'ws-acme',
        retention: 'permanent',
      })
    }
    return result
  },

  /**
   * Demonstration only — corrupt an entry so detection can be shown working.
   * See `simulateTamper` in audit.ts for why this exists.
   */
  simulateTamper: async (seq: number): Promise<boolean> => {
    await ensureLedger()
    await delay(200)
    return simulateTamper(seq)
  },

  /** Restore the chain after a tamper demonstration. */
  resetChain: async (): Promise<void> => {
    await delay(200)
    seedLedger(await rehashFixture(AUDIT_ENTRIES))
  },
  getPolicies: () => resolve<Policy[]>(POLICIES, 260),
  getIngestJobs: () => resolve<IngestJob[]>(INGEST_JOBS, 340),
  getGraphBuild: () => resolve<GraphBuild>(GRAPH_BUILD, 380),

  /* ------------------------------------------------------------------ STLC */

  getTestPlans: () => resolve<TestPlan[]>(TEST_PLANS, 340),
  getTestPlan: async (id: string): Promise<TestPlan | null> =>
    resolve(TEST_PLANS.find((p) => p.id === id || p.requirementId === id) ?? null, 300),
  getTestCases: () => resolve<TestCase[]>(TEST_CASES, 360),
  getTestSuites: () => resolve<TestSuite[]>(TEST_SUITES, 280),

  /**
   * Save a named selection of cases as a reusable suite.
   *
   * Stores case ids rather than a snapshot of the cases themselves: a suite is
   * "these tests", and if a case is later edited the suite should run the
   * corrected version. Freezing copies would quietly re-run superseded tests
   * and produce evidence for a case that no longer exists.
   */
  createTestSuite: async (input: {
    name: string
    description: string
    caseIds: string[]
  }): Promise<TestSuite> => {
    await delay(600)
    const seq = TEST_SUITES.length + 1
    const created: TestSuite = {
      id: `ts-${Date.now().toString(36)}`,
      ref: `TS-${String(seq).padStart(3, '0')}`,
      name: input.name.trim(),
      description: input.description.trim(),
      // De-duplicated: the picker allows a case to be toggled repeatedly, and
      // a suite listing the same case twice would run it twice.
      caseIds: Array.from(new Set(input.caseIds)),
      saved: true,
      createdAt: new Date().toISOString(),
      createdBy: CURRENT_USER.name,
    }
    TEST_SUITES.unshift(created)
    return clone(created)
  },

  updateTestSuite: async (
    id: string,
    patch: { name?: string; description?: string; caseIds?: string[] },
  ): Promise<TestSuite> => {
    await delay(420)
    const suite = TEST_SUITES.find((s) => s.id === id)
    if (!suite) throw new Error('Suite not found')
    if (patch.name !== undefined) suite.name = patch.name.trim()
    if (patch.description !== undefined) suite.description = patch.description.trim()
    if (patch.caseIds !== undefined) suite.caseIds = Array.from(new Set(patch.caseIds))
    return clone(suite)
  },

  deleteTestSuite: async (id: string): Promise<void> => {
    await delay(360)
    const i = TEST_SUITES.findIndex((s) => s.id === id)
    if (i >= 0) TEST_SUITES.splice(i, 1)
  },
  getTestEnvironments: () => resolve<TestEnvironment[]>(TEST_ENVIRONMENTS, 320),
  getTestExecutions: () => resolve<TestExecution[]>(TEST_EXECUTIONS, 380),
  getTestExecution: async (id: string): Promise<TestExecution | null> =>
    resolve(TEST_EXECUTIONS.find((e) => e.id === id) ?? null, 300),
  getTestClosures: () => resolve<TestClosure[]>(TEST_CLOSURES, 340),
  getTestClosure: async (requirementId: string): Promise<TestClosure | null> =>
    resolve(TEST_CLOSURES.find((c) => c.requirementId === requirementId) ?? null, 320),

  /**
   * Persist an edited test case. The real backend would version this; here we
   * mutate the fixture so an edit survives navigation within the session.
   */
  saveTestCase: async (updated: TestCase, reason?: string): Promise<TestCase> => {
    await delay(420)
    const i = TEST_CASES.findIndex((c) => c.id === updated.id)
    const before = i >= 0 ? clone(TEST_CASES[i]) : null
    const next: TestCase = {
      ...updated,
      updatedAt: new Date().toISOString(),
      // An AI-generated case that a human edits is no longer purely generated.
      origin: updated.origin === 'ai_generated' ? 'ai_edited_by_human' : updated.origin,
    }
    if (i >= 0) TEST_CASES[i] = next

    /*
     * Field-level diff, not a summary. Weakening an expected result is the
     * single most consequential edit anyone can make to a test asset, and a
     * record that says only "case edited" cannot distinguish it from a typo
     * fix. Part 11 §11.10(e) asks for the prior value for exactly this reason.
     */
    if (before) {
      const changes = diffFields(before, next, [
        { field: 'title', label: 'Title' },
        { field: 'expectedResult', label: 'Expected result' },
        { field: 'priority', label: 'Priority' },
        { field: 'level', label: 'Level' },
        { field: 'type', label: 'Type' },
        { field: 'automatable', label: 'Automatable' },
        { field: 'testData', label: 'Test data' },
        { field: 'state', label: 'Review state' },
        { field: 'origin', label: 'Origin' },
      ])
      if (changes.length) {
        await ensureLedger()
        await record({
          action: 'testcase.edited',
          actor: CURRENT_USER.name,
          actorType: 'human',
          requirementRef: next.ref,
          summary: `${next.ref} edited — ${changes.map((c) => c.label).join(', ')}.`,
          changes,
          reason,
          workspaceId: 'ws-acme',
        })
      }
    }

    return clone(next)
  },

  /** Approve or reject a plan or case in one call — both share ReviewState. */
  setTestCaseState: async (
    id: string,
    state: TestCase['state'],
    reason?: string,
  ): Promise<TestCase | null> => {
    await delay(300)
    const i = TEST_CASES.findIndex((c) => c.id === id)
    if (i < 0) return null
    const before = clone(TEST_CASES[i])
    TEST_CASES[i] = { ...TEST_CASES[i], state, updatedAt: new Date().toISOString() }

    await ensureLedger()
    await record({
      action: 'testcase.state_changed',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: TEST_CASES[i].ref,
      summary: `${TEST_CASES[i].ref} ${state === 'approved' ? 'approved' : `moved to ${state}`}.`,
      changes: diffFields(before, TEST_CASES[i], [{ field: 'state', label: 'Review state' }]),
      reason,
      workspaceId: 'ws-acme',
    })

    return clone(TEST_CASES[i])
  },

  setTestPlanState: async (
    id: string,
    state: TestPlan['state'],
    reason?: string,
  ): Promise<TestPlan | null> => {
    await delay(320)
    const i = TEST_PLANS.findIndex((p) => p.id === id)
    if (i < 0) return null
    const before = clone(TEST_PLANS[i])
    TEST_PLANS[i] = {
      ...TEST_PLANS[i],
      state,
      updatedAt: new Date().toISOString(),
      approvedBy: state === 'approved' ? CURRENT_USER.name : null,
      approvedAt: state === 'approved' ? new Date().toISOString() : null,
    }

    await ensureLedger()
    await record({
      action: 'plan.state_changed',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: TEST_PLANS[i].requirementRef,
      summary: `${TEST_PLANS[i].ref} ${state === 'approved' ? 'approved' : `moved to ${state}`}.`,
      changes: diffFields(before, TEST_PLANS[i], [
        { field: 'state', label: 'Review state' },
        { field: 'approvedBy', label: 'Approved by' },
      ]),
      reason,
      /* A plan approval is a SOX control point, not routine authoring. */
      retention: state === 'approved' ? 'sox' : 'standard',
      workspaceId: 'ws-acme',
    })

    return clone(TEST_PLANS[i])
  },

  /**
   * Simulated execution. Streams one case result at a time so the UI shows a
   * run in progress rather than a spinner followed by a finished table —
   * watching results land is the whole point of an execution screen.
   */
  runTestExecution: async (
    input: {
      caseIds: string[]
      environmentId: string
      suiteName: string
      /**
       * Defects this run is re-testing. A re-test exists to prove a fix, so
       * the cases behind those defects are expected to pass this time —
       * without this, replaying the authored outcome would fail the case
       * forever and no defect could ever be verified.
       */
      retestDefectIds?: string[]
    },
    onProgress: (partial: { index: number; total: number; result: CaseResult }) => void,
  ): Promise<TestExecution> => {
    const env = TEST_ENVIRONMENTS.find((e) => e.id === input.environmentId) ?? TEST_ENVIRONMENTS[0]
    const cases = input.caseIds
      .map((id) => TEST_CASES.find((c) => c.id === id))
      .filter((c): c is TestCase => Boolean(c))

    const retestDefects = (input.retestDefectIds ?? [])
      .map((id) => DEFECTS.find((d) => d.id === id))
      .filter((d): d is Defect => Boolean(d))
    const retestCaseIds = new Set(retestDefects.map((d) => d.caseId).filter(Boolean) as string[])

    const results: CaseResult[] = []
    for (let i = 0; i < cases.length; i++) {
      const c = cases[i]
      await delay(700)
      // Reuse the authored outcome for this case when one exists, so the
      // simulated run stays consistent with the rest of the fixture.
      const prior = TEST_EXECUTIONS[0].results.find((r) => r.caseId === c.id)

      // A case being re-tested passes: the fix under test is what changed.
      if (prior && retestCaseIds.has(c.id)) {
        const fixed: CaseResult = {
          ...clone(prior),
          id: `cr-live-${i}`,
          status: 'passed',
          deviation: null,
          actual: `Re-tested after the fix. ${prior.expected}`,
          attempts: 1,
          startedAt: new Date().toISOString(),
          defectRef: undefined,
        }
        results.push(fixed)
        onProgress({ index: i + 1, total: cases.length, result: fixed })
        continue
      }

      const result: CaseResult = prior
        ? { ...clone(prior), id: `cr-live-${i}`, startedAt: new Date().toISOString() }
        : {
            id: `cr-live-${i}`,
            caseId: c.id,
            caseRef: c.ref,
            caseTitle: c.title,
            status: 'passed',
            grade: c.automatable ? 'verified' : 'asserted',
            expected: c.expectedResult,
            actual: `Observed the expected outcome across ${c.steps.length} steps.`,
            deviation: null,
            durationSeconds: c.estimatedDurationSeconds,
            attempts: 1,
            startedAt: new Date().toISOString(),
            artifacts: [],
            coversNodeIds: c.coversNodeIds,
          }
      results.push(result)
      onProgress({ index: i + 1, total: cases.length, result })
    }

    const failed = results.some((r) => r.status === 'failed')
    const execution: TestExecution = {
      id: `te-live-${Math.random().toString(36).slice(2, 8)}`,
      ref: `EX-1042-${String(TEST_EXECUTIONS.length + 1).padStart(2, '0')}`,
      requirementId: 'req-1',
      planId: 'tp-1042',
      suiteId: null,
      suiteName: input.suiteName,
      environmentId: env.id,
      environment: env.fingerprint,
      status: failed ? 'failed' : 'passed',
      triggeredBy: CURRENT_USER.name,
      triggeredByType: 'human',
      startedAt: new Date().toISOString(),
      finishedAt: new Date().toISOString(),
      results,
      costUsd: Number((results.length * 0.42).toFixed(2)),
      preflight: env.readiness,
    }

    const verified = results.filter((r) => r.grade === 'verified').length
    await ensureLedger()
    await record({
      action: 'execution.finished',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: 'MER-1042',
      summary:
        `${execution.ref} ${failed ? 'failed' : 'passed'} — ${results.length} cases in ` +
        `${env.name} (${env.fingerprint.release}), ${verified} verified-grade.`,
      costUsd: execution.costUsd,
      durationSeconds: results.reduce((a, r) => a + r.durationSeconds, 0),
      workspaceId: 'ws-acme',
    })

    return execution
  },

  /* ------------------------------------------------------------- defects */

  getDefects: async (requirementId?: string): Promise<Defect[]> =>
    resolve(
      clone(requirementId ? DEFECTS.filter((d) => d.requirementId === requirementId) : DEFECTS),
      280,
    ),

  /** Raise a defect from a failed or deviating result. */
  raiseDefect: async (input: {
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
  }): Promise<Defect> => {
    await delay(360)
    const n = DEFECTS.length + 315
    const now = new Date().toISOString()
    const defect: Defect = {
      id: `def-${n}`,
      ref: `DEF-${n}`,
      requirementId: input.requirementId,
      executionId: input.executionId,
      caseId: input.caseId,
      caseRef: input.caseRef,
      title: input.title,
      expected: input.expected,
      actual: input.actual,
      severity: input.severity,
      status: 'open',
      owner: input.owner,
      raisedBy: CURRENT_USER.name,
      raisedByType: 'human_authored',
      raisedAt: now,
      updatedAt: now,
      notes: [
        { at: now, by: CURRENT_USER.name, text: `Raised from ${input.caseRef ?? 'a result'}.` },
      ],
      retestExecutionIds: [],
      verifiedByExecutionId: null,
      affectedNodeIds: input.affectedNodeIds ?? [],
    }
    DEFECTS.unshift(defect)

    await ensureLedger()
    await record({
      action: 'defect.raised',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: defect.ref,
      summary: `${defect.ref} raised at ${input.severity} severity from ${input.caseRef ?? 'a result'} — ${input.title}`,
      changes: [
        { field: 'expected', label: 'Expected', before: null, after: input.expected },
        { field: 'actual', label: 'Actual', before: null, after: input.actual },
      ],
      workspaceId: 'ws-acme',
    })

    return clone(defect)
  },

  setDefectStatus: async (
    id: string,
    status: DefectStatus,
    note?: string,
  ): Promise<Defect | null> => {
    await delay(280)
    const d = DEFECTS.find((x) => x.id === id)
    if (!d) return null
    const now = new Date().toISOString()
    const before = d.status
    d.status = status
    d.updatedAt = now
    if (note) d.notes.push({ at: now, by: CURRENT_USER.name, text: note })

    await ensureLedger()
    await record({
      action: 'defect.status_changed',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: d.ref,
      summary: `${d.ref} moved from ${before} to ${status}.`,
      changes: [{ field: 'status', label: 'Status', before, after: status }],
      reason: note,
      workspaceId: 'ws-acme',
    })

    return clone(d)
  },

  /**
   * Record that an execution re-tested a set of defects.
   *
   * A defect only closes when its case actually passed in that run. A fix
   * being *claimed* is not the same as a fix being *proven*, and the whole
   * point of the re-test step is to keep those apart.
   */
  recordRetest: async (execution: TestExecution, defectIds: string[]): Promise<Defect[]> => {
    await delay(300)
    const now = new Date().toISOString()
    const touched: Defect[] = []
    for (const id of defectIds) {
      const d = DEFECTS.find((x) => x.id === id)
      if (!d) continue
      d.retestExecutionIds.push(execution.id)
      const result = execution.results.find((r) => r.caseId === d.caseId)
      if (result && result.status === 'passed') {
        d.status = 'closed'
        d.verifiedByExecutionId = execution.id
        d.notes.push({
          at: now,
          by: CURRENT_USER.name,
          text: `Closed by re-test ${execution.ref} — ${d.caseRef ?? 'the case'} passed.`,
        })
      } else {
        d.status = 'open'
        d.notes.push({
          at: now,
          by: CURRENT_USER.name,
          text: `Re-test ${execution.ref} did not pass. Reopened.`,
        })
      }
      d.updatedAt = now
      touched.push(clone(d))
    }

    const closed = touched.filter((d) => d.status === 'closed').length
    await ensureLedger()
    await record({
      action: 'retest.recorded',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: execution.ref,
      summary:
        `Re-test ${execution.ref} recorded against ${touched.length} defect(s) — ` +
        `${closed} closed by a passing case, ${touched.length - closed} reopened.`,
      workspaceId: 'ws-acme',
    })

    return touched
  },

  /**
   * Simulated upload. Reports progress through the same stages the real
   * pipeline would, so the UI exercises its staged states rather than a
   * single spinner.
   */
  uploadArtifact: async (
    file: { name: string; sizeLabel: string },
    /**
     * Per-stage progress, for callers rendering a live job row. Optional: the
     * Knowledge Sources page ingests without a queue to update, and it should
     * not have to pass a no-op to say so.
     */
    onProgress: (job: IngestJob) => void = () => {},
  ): Promise<IngestJob> => {
    const id = `ing-${Math.random().toString(36).slice(2, 9)}`
    const base: IngestJob = {
      id,
      projectId: 'pj-hcm',
      name: file.name,
      kind: 'document',
      docKind: 'other',
      provider: 'Upload',
      stage: 'uploading',
      progress: 0,
      sizeLabel: file.sizeLabel,
      uploadedAt: new Date().toISOString(),
      uploadedBy: 'Sathish Kumar',
      entitiesExtracted: 0,
      linksProposed: 0,
      parseCoverage: 0,
      warnings: [],
    }

    const script: { stage: IngestJob['stage']; to: number }[] = [
      { stage: 'uploading', to: 100 },
      { stage: 'parsing', to: 100 },
      { stage: 'extracting', to: 100 },
      { stage: 'linking', to: 100 },
    ]

    let current = { ...base }
    for (const step of script) {
      for (let pct = 20; pct <= step.to; pct += 20) {
        await delay(140)
        current = { ...current, stage: step.stage, progress: pct }
        onProgress(current)
      }
    }

    await delay(200)
    const done: IngestJob = {
      ...current,
      stage: 'ready',
      progress: 100,
      entitiesExtracted: 28,
      linksProposed: 5,
      parseCoverage: 92,
    }
    onProgress(done)

    await ensureLedger()
    await record({
      action: 'artifact.uploaded',
      actor: CURRENT_USER.name,
      actorType: 'human',
      summary:
        `${file.name} ingested — ${done.entitiesExtracted} entities extracted, ` +
        `${done.linksProposed} links proposed at ${done.parseCoverage}% parse coverage.`,
      workspaceId: 'ws-acme',
    })

    return done
  },
  getAnalytics: (days = 30) =>
    resolve<{
      windowDays: number
      runs: RunPoint[]
      runTotals: RunTotals
      cost: CostPoint[]
      cycleTime: CycleTimePoint[]
      dora: DoraMetric[]
      modelSpend: ModelSpend[]
    }>(
      {
        windowDays: days,
        runs: RUN_SERIES,
        runTotals: RUN_TOTALS,
        cost: COST_SERIES,
        cycleTime: CYCLE_TIME_SERIES,
        dora: DORA_METRICS,
        modelSpend: MODEL_SPEND,
      },
      420,
    ),

  /* -------------------------------------------- approvals & human oversight */

  /**
   * Record a gate decision together with the evidence that it was considered.
   *
   * The oversight record is written in the same call as the decision rather
   * than inferred later, because Art. 14 asks whether oversight was effective
   * at the moment it was exercised. Reconstructing that afterwards from access
   * logs would be a guess.
   */
  decideGate: async (input: {
    packageId: string
    gateId: string
    decision: 'approved' | 'rejected'
    comment: string
    oversight: HumanOversightRecord
  }): Promise<ApprovalPackage | null> => {
    await delay(420)
    const pkg = APPROVAL_PACKAGES.find((p) => p.id === input.packageId)
    if (!pkg) return null
    const gate = pkg.gates.find((g) => g.id === input.gateId)
    if (!gate) return null

    const before = gate.decision
    gate.decision = input.decision
    gate.approver = CURRENT_USER.name
    gate.approverEmail = CURRENT_USER.email
    gate.decidedAt = new Date().toISOString()
    gate.comment = input.comment
    gate.oversight = input.oversight

    const o = input.oversight
    await ensureLedger()
    await record({
      action: input.decision === 'approved' ? 'approval.granted' : 'approval.rejected',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: pkg.requirementRef,
      summary:
        `${gate.name} gate ${input.decision} after ${Math.round(o.reviewDurationSeconds / 60)}m review; ` +
        `${o.artifactsOpened.length}/${o.artifactsAvailable} evidence artifacts opened` +
        (o.overridden ? ' — AI recommendation overridden.' : '.'),
      changes: [{ field: 'decision', label: 'Decision', before, after: input.decision }],
      reason: input.comment,
      durationSeconds: o.reviewDurationSeconds,
      retention: 'sox',
      legalHold: true,
      workspaceId: 'ws-acme',
    })

    return clone(pkg)
  },

  /* -------------------------------------------------------- AI incidents */

  getIncidents: () => resolve<AiIncident[]>(AI_INCIDENTS, 320),

  raiseIncident: async (input: {
    kind: IncidentKind
    severity: IncidentSeverity
    title: string
    description: string
    affectedRequirementRefs: string[]
    reportable: boolean
    reportableRationale: string
  }): Promise<AiIncident> => {
    await delay(400)
    const n = AI_INCIDENTS.length + 1
    const now = new Date().toISOString()
    const incident: AiIncident = {
      id: `inc-${n}`,
      ref: `AIR-${String(n).padStart(4, '0')}`,
      kind: input.kind,
      severity: input.severity,
      status: 'open',
      title: input.title,
      description: input.description,
      detectedAt: now,
      detectedBy: CURRENT_USER.name,
      detectionMethod: 'human_review',
      affectedRequirementRefs: input.affectedRequirementRefs,
      affectedArtifactIds: [],
      model: ACTIVE_MODEL.model,
      modelVersion: ACTIVE_MODEL.modelVersion,
      reportable: input.reportable,
      reportableRationale: input.reportableRationale,
      disclosedAt: null,
      disclosedTo: null,
      correctiveAction: null,
      resolvedAt: null,
      notes: [{ at: now, by: CURRENT_USER.name, text: 'Incident raised.' }],
    }
    AI_INCIDENTS.unshift(incident)

    await ensureLedger()
    await record({
      action: 'incident.raised',
      actor: CURRENT_USER.name,
      actorType: 'human',
      summary: `${incident.ref} raised (${input.severity}, ${input.kind.replace(/_/g, ' ')}) — ${input.title}`,
      reason: input.reportableRationale,
      retention: 'permanent',
      legalHold: input.reportable,
      workspaceId: 'ws-acme',
    })

    return clone(incident)
  },

  setIncidentStatus: async (
    id: string,
    status: IncidentStatus,
    note?: string,
  ): Promise<AiIncident | null> => {
    await delay(300)
    const inc = AI_INCIDENTS.find((i) => i.id === id)
    if (!inc) return null
    const before = inc.status
    const now = new Date().toISOString()
    inc.status = status
    if (status === 'resolved') inc.resolvedAt = now
    if (note) inc.notes.push({ at: now, by: CURRENT_USER.name, text: note })

    await ensureLedger()
    await record({
      action: 'incident.updated',
      actor: CURRENT_USER.name,
      actorType: 'human',
      summary: `${inc.ref} moved from ${before} to ${status}.`,
      changes: [{ field: 'status', label: 'Status', before, after: status }],
      reason: note,
      retention: 'permanent',
      workspaceId: 'ws-acme',
    })

    return clone(inc)
  },

  /* ------------------------------------------------------- evidence export */

  /**
   * Build a real, verifiable evidence pack.
   *
   * Returns the manifest as a string the caller downloads. The pack contains
   * the chain segment, a recomputed verification result, and the hash of the
   * manifest itself, so a recipient can check it without access to Meridian.
   * Exporting is itself recorded — who took a copy of the record, and when, is
   * part of the record.
   */
  exportEvidencePack: async (input: {
    requirementRef?: string | null
    scope: string
  }): Promise<{ filename: string; content: string; manifestHash: string }> => {
    await ensureLedger()
    await delay(900)

    const all = getEntries()
    const entries = input.requirementRef
      ? all.filter((e) => e.requirementRef === input.requirementRef)
      : all
    const verification = await verifyChain(all)

    const body = {
      generatedAt: new Date().toISOString(),
      generatedBy: { name: CURRENT_USER.name, email: CURRENT_USER.email },
      scope: input.scope,
      requirementRef: input.requirementRef ?? null,
      standards: [
        'EU AI Act Art. 12 (record-keeping)',
        'EU AI Act Art. 14 (human oversight)',
        'ISO/IEC 42001 A.6.2.8 (AI event logging)',
        '21 CFR Part 11 §11.10(e) (audit trail)',
        'NIST AI RMF (traceability, incident disclosure)',
      ],
      chainVerification: verification,
      entryCount: entries.length,
      /* Full entries, including field-level changes and model provenance. */
      entries,
      incidents: AI_INCIDENTS.filter((i) =>
        input.requirementRef
          ? i.affectedRequirementRefs.includes(input.requirementRef)
          : true,
      ),
    }

    const content = JSON.stringify(body, null, 2)
    const manifestHash = await sha256(content)
    const stamp = new Date().toISOString().slice(0, 10)
    const filename = `meridian-evidence-${input.requirementRef ?? 'all'}-${stamp}.json`

    await record({
      action: 'evidence.exported',
      actor: CURRENT_USER.name,
      actorType: 'human',
      requirementRef: input.requirementRef ?? null,
      summary:
        `Evidence pack exported (${entries.length} entries, scope: ${input.scope}). ` +
        `Manifest ${manifestHash.slice(0, 16)}…, chain ${verification.valid ? 'verified' : 'FAILED VERIFICATION'}.`,
      retention: 'sox',
      workspaceId: 'ws-acme',
    })

    return { filename, content, manifestHash }
  },

  /** Simulated assistant turn for the chat composer. */
  /**
   * Crawl an application to discover what is worth testing.
   *
   * Returns the completed crawl. In the built product this would be a job to
   * poll; the shape is the same either way, and the UI already renders the
   * 'running' state from the message that precedes this one.
   */
  crawlSite: async (startUrl: string): Promise<CrawlResult> => {
    await delay(2200)
    const host = safeHost(startUrl)
    return {
      id: `crawl-${Date.now().toString(36)}`,
      startUrl,
      status: 'complete',
      startedAt: new Date().toISOString(),
      maxDepth: 2,
      pages: [
        {
          url: startUrl,
          title: `${host} — storefront`,
          note: 'Public landing page. Search and category navigation are the entry points.',
        },
        {
          url: `${trimSlash(startUrl)}/search`,
          title: 'Search results',
          note: 'Free-text search over merchants. No login required to reach it.',
        },
        {
          url: `${trimSlash(startUrl)}/store/:id`,
          title: 'Merchant store page',
          note: 'Menu tabs, in-store search, and a delivery/pickup toggle.',
        },
        {
          url: `${trimSlash(startUrl)}/cart`,
          title: 'Cart',
          note: 'Line items with quantity controls. Proceeds to checkout.',
        },
        {
          url: `${trimSlash(startUrl)}/checkout`,
          title: 'Checkout',
          note: 'Address and payment step. The furthest point reachable without an account.',
        },
      ],
    }
  },

  /**
   * Propose test cases from a crawl.
   *
   * Proposed, not created: they are returned for review and only become real
   * cases when the reviewer accepts them. Generating straight into the plan
   * would put unreviewed machine output into the record this product exists to
   * make trustworthy.
   */
  generateCasesFromCrawl: async (crawl: CrawlResult): Promise<ProposedCase[]> => {
    await delay(1800)
    const host = safeHost(crawl.startUrl)
    return [
      {
        id: 'pc-1',
        ref: 'TC-NEW-01',
        title: 'Search for a merchant',
        group: 'Discovery',
        summary: 'A user can search from the storefront and open a matching merchant’s page.',
        steps: [
          `Open ${host} as an anonymous visitor`,
          'Enter a known merchant name in the search field',
          'Open the first matching result',
        ],
      },
      {
        id: 'pc-2',
        ref: 'TC-NEW-02',
        title: 'Filter merchants by category',
        group: 'Discovery',
        summary: 'A user can narrow the storefront to a category and see matching merchants.',
        steps: [
          'Open the storefront',
          'Select a category from the navigation',
          'Confirm every result carries that category',
        ],
      },
      {
        id: 'pc-3',
        ref: 'TC-NEW-03',
        title: 'Add an item to the cart',
        group: 'Ordering',
        summary: 'A user can open a merchant, add a menu item, and see it reflected in the cart.',
        steps: [
          'Open a merchant store page',
          'Add a menu item to the cart',
          'Confirm the cart count and line total update',
        ],
      },
      {
        id: 'pc-4',
        ref: 'TC-NEW-04',
        title: 'Proceed to checkout',
        group: 'Ordering',
        summary: 'A user with an item in the cart can proceed from the cart to the checkout page.',
        steps: [
          'Add an item to the cart',
          'Open the cart',
          'Proceed to checkout and confirm the address step renders',
        ],
      },
    ]
  },

  /**
   * Execute cases proposed in the conversation and report an outcome per case.
   *
   * Returns a status map rather than mutating anything: the chat holds the
   * result for its own panel, and nothing is written to the plan until the
   * cases are accepted through the normal path. A run against unaccepted
   * proposals is a rehearsal, not evidence.
   */
  runProposedCases: async (
    cases: ProposedCase[],
  ): Promise<{ statusById: Record<string, RunStatus>; durationMs: number }> => {
    await delay(2200)
    const statusById: Record<string, RunStatus> = {}
    cases.forEach((c) => {
      statusById[c.id] = 'passed'
    })
    await ensureLedger()
    await record({
      action: 'test.run',
      actor: `${ACTIVE_MODEL.model} · browser agent`,
      actorType: 'agent',
      summary: `Rehearsal run of ${cases.length} proposed cases — ${cases.length} passed.`,
      costUsd: 0.19,
      workspaceId: 'ws-acme',
    })
    return { statusById, durationMs: 41_000 }
  },

  /**
   * Chat is served live — see the hybrid list below.
   *
   * The fixture that stood here returned a canned "this is a mocked response"
   * turn carrying a fabricated citation to `n-cfg-approval` and an invented
   * $0.27 cost. It was removed rather than kept behind `VITE_USE_MOCK_API`:
   * an answer that *looks* grounded and cites a node that need not exist is
   * the one failure this product cannot afford to demonstrate, and it also
   * wrote a fictional row into the audit ledger on every turn.
   */
  sendMessage: (_requirementId: string, _text: string): Promise<ChatMessage> => {
    throw new NotImplementedYet('Chat without a backend')
  },
}


/* ------------------------------------------------------------------ hybrid */

/**
 * Live where the backend implements it, fixture where it does not.
 *
 * Written as an explicit list rather than a spread of `liveApi` over `mockApi`
 * because the important property is *knowing* which calls are real. A spread
 * would silently start serving a mock the day someone renamed a live method,
 * and the UI would look fine.
 */
const USE_MOCK = import.meta.env.VITE_USE_MOCK_API === '1'

/*
 * Connector setup is served live even in mock mode.
 *
 * The connection wizard is driven entirely by what the backend declares — the
 * Workday setup steps, its credential fields, its report pack. There is no
 * sensible fixture for that: a hardcoded copy would drift from the connector's
 * real requirements the first time one changed, and the wizard would then walk
 * someone through a setup that no longer works. So in mock mode these calls
 * still hit the server, and fail visibly if it is not running.
 */
const connectorSetupApi = {
  getConnectorSetup: liveApi.getConnectorSetup,
  createConnection: liveApi.createConnection,
  getConnection: liveApi.getConnection,
  updateConnectionCredentials: liveApi.updateConnectionCredentials,
  getConnectionCapabilities: liveApi.getConnectionCapabilities,
  // Sessions are live-only: a fixture session would be a fake credential,
  // and the whole point of the capture flow is that the session is real.
  getBrowserSession: liveApi.getBrowserSession,
  revokeBrowserSession: liveApi.revokeBrowserSession,

  /* Live-only graph operations. No fixture equivalent exists: confirming a
     link is a governance act that must reach the server, and searching a
     fixture graph would answer a question about data that is not there. */
  confirmEdge: liveApi.confirmEdge,
  searchGraph: liveApi.searchGraph,
  generateImpact: liveApi.generateImpact,
  generateTestPlan: liveApi.generateTestPlan,
  getGateBlockers: liveApi.getGateBlockers,
  getWorkspaces: liveApi.getWorkspaces,
  getProjects: liveApi.getProjects,
}

/*
 * Typed as the full surface rather than inferred from the ternary. Inference
 * produces a union, which narrows every call site to the mock's shape and
 * hides the live-only methods the pages actually need.
 */
type Api = typeof mockApi & typeof connectorSetupApi

export const api: Api = USE_MOCK
  ? { ...mockApi, ...connectorSetupApi }
  : {
      ...mockApi,
      ...connectorSetupApi,

      /* --- sources, connectors and the graph: fully live ----------------- */
      getSources: liveApi.getSources,
      getConnectors: liveApi.getConnectors,
      getConnections: liveApi.getConnections,
      getConnection: liveApi.getConnection,
      getConnectorSetup: liveApi.getConnectorSetup,
      createConnection: liveApi.createConnection,
      updateConnectionCredentials: liveApi.updateConnectionCredentials,
      getConnectionCapabilities: liveApi.getConnectionCapabilities,
      getBrowserSession: liveApi.getBrowserSession,
      revokeBrowserSession: liveApi.revokeBrowserSession,
      testConnection: liveApi.testConnection,
      syncConnection: liveApi.syncConnection,
      disconnectConnection: liveApi.disconnectConnection,
      getGraph: liveApi.getGraph,
      getIngestJobs: liveApi.getIngestJobs,

      /* --- requirements, impact and the STLC ---------------------------- */
      getRequirements: liveApi.getRequirements,
      getRequirement: liveApi.getRequirement,
      createRequirement: liveApi.createRequirement,
      setRequirementStage: liveApi.setRequirementStage,
      getThread: liveApi.getThread,
      getImpact: liveApi.getImpact,
      getImpactAnalyses: liveApi.getImpactAnalyses,
      getTestPlans: liveApi.getTestPlans,
      getTestPlan: liveApi.getTestPlan,
      setTestPlanState: liveApi.setTestPlanState,
      getTestCases: liveApi.getTestCases,
      saveTestCase: liveApi.saveTestCase,
      setTestCaseState: liveApi.setTestCaseState,
      getTestSuites: liveApi.getTestSuites,
      createTestSuite: liveApi.createTestSuite,
      updateTestSuite: liveApi.updateTestSuite,
      deleteTestSuite: liveApi.deleteTestSuite,
      getTestEnvironments: liveApi.getTestEnvironments,
      getTestExecutions: liveApi.getTestExecutions,
      getTestExecution: liveApi.getTestExecution,
      getTestRuns: liveApi.getTestRuns,
      getTestClosures: liveApi.getTestClosures,
      getTestClosure: liveApi.getTestClosure,
      getDefects: liveApi.getDefects,
      raiseDefect: liveApi.raiseDefect,
      setDefectStatus: liveApi.setDefectStatus,

      /* --- governance ---------------------------------------------------- */
      getApprovals: liveApi.getApprovals,
      getAudit: liveApi.getAudit,
      verifyAuditChain: liveApi.verifyAuditChain,
      simulateTamper: liveApi.simulateTamper,
      getIncidents: liveApi.getIncidents,
      raiseIncident: liveApi.raiseIncident,
      setIncidentStatus: liveApi.setIncidentStatus,
      getPolicies: liveApi.getPolicies,
      getAnalytics: liveApi.getAnalytics,
      /*
       * Chat is live. The fixture returned a canned "this is a mocked
       * response" turn with an invented citation, which is worse than an
       * error: it looks like a grounded answer and cites a node that may not
       * exist in this workspace. The backend answers from the graph or says
       * it cannot.
       */
      sendMessage: liveApi.sendMessage,
      exportEvidencePack: liveApi.exportEvidencePack,

      /*
       * Deliberately still mocked. `crawlSite`, `generateCasesFromCrawl` and
       * `runProposedCases` would require driving a browser against a live
       * application, which Meridian cannot do. The mock keeps the chat flow
       * demonstrable; the live client throws rather than fabricating a result.
       *
       * `decideGate`, `runTestExecution`, `recordRetest`, `uploadArtifact`,
       * `connectConnector`, `createCustomConnector`, `setConnectionCadence`
       * and `resetChain` keep their fixture implementations until the screens
       * that call them are migrated to the live signatures, which differ.
       */
    }

export { ApiError, NotImplementedYet, setActor } from './api-live'
export { apiBaseUrl } from './http'

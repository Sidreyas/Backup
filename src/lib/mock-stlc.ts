/**
 * STLC fixtures — test plan, cases, suites, environments, executions, closure.
 *
 * Anchored to req-1 (MER-1042, "Auto-approve overtime under 4 hours per week")
 * so the whole testing life cycle can be walked end to end against a
 * requirement that already has a chat thread and an impact analysis.
 *
 * The data deliberately contains an unmet exit criterion, an uncovered
 * impacted node and one asserted-grade result, because those are the states
 * the product exists to surface. A fixture where everything passes would hide
 * exactly the screens that matter.
 */
import type {
  CaseResult,
  TestCase,
  TestClosure,
  TestEnvironment,
  TestExecution,
  TestPlan,
  TestSuite,
  Defect,
} from './types'

/* ---------------------------------------------------------- environments */

export const TEST_ENVIRONMENTS: TestEnvironment[] = [
  {
    id: 'env-wd-impl',
    name: 'Workday Sandbox (Implementation)',
    kind: 'sandbox',
    platform: 'Workday HCM',
    status: 'ready',
    fingerprint: {
      environment: 'Sandbox (Implementation)',
      tenant: 'acme_hcm_impl',
      release: 'Workday 2026R1',
      refreshedAt: '2026-07-14T02:00:00Z',
      dataCoverage: 41,
    },
    readiness: [
      {
        id: 'rd-1',
        text: 'Tenant reachable and API credentials valid',
        met: true,
        evaluatedBy: 'system',
        detail: 'Handshake succeeded 4 minutes ago',
      },
      {
        id: 'rd-2',
        text: 'Release matches the release the plan was written against',
        met: true,
        evaluatedBy: 'system',
        detail: 'Workday 2026R1 — matches plan TP-1042',
      },
      {
        id: 'rd-3',
        text: 'Test data covers all production scenario classes',
        met: false,
        evaluatedBy: 'system',
        detail:
          'Data coverage 41%. No records exist for union-agreement workers or retroactive pay periods.',
      },
      {
        id: 'rd-4',
        text: 'Refreshed within the last 14 days',
        met: false,
        evaluatedBy: 'system',
        detail: 'Last refresh was 24 days ago (14 Jul 2026)',
      },
    ],
    lastRefreshedAt: '2026-07-14T02:00:00Z',
    ownedBy: 'Platform Engineering',
    hourlyCostUsd: 1.85,
    notes:
      'Shared with the Absence Reporting project. Coordinate refreshes — a refresh drops in-flight test data.',
  },
  {
    id: 'env-wd-preprod',
    name: 'Workday Pre-production',
    kind: 'preprod',
    platform: 'Workday HCM',
    status: 'degraded',
    fingerprint: {
      environment: 'Pre-production',
      tenant: 'acme_hcm_preprod',
      release: 'Workday 2026R1',
      refreshedAt: '2026-08-04T01:00:00Z',
      dataCoverage: 88,
    },
    readiness: [
      {
        id: 'rd-5',
        text: 'Tenant reachable and API credentials valid',
        met: true,
        evaluatedBy: 'system',
      },
      {
        id: 'rd-6',
        text: 'Release matches the release the plan was written against',
        met: true,
        evaluatedBy: 'system',
      },
      {
        id: 'rd-7',
        text: 'Test data covers all production scenario classes',
        met: true,
        evaluatedBy: 'system',
        detail: 'Data coverage 88% — production clone with PII masking',
      },
      {
        id: 'rd-8',
        text: 'Payroll outbound integration responding',
        met: false,
        evaluatedBy: 'system',
        detail: 'PAY_OUT_001 returning 503 since 06:12 UTC. Vendor incident INC-88214 open.',
      },
    ],
    lastRefreshedAt: '2026-08-04T01:00:00Z',
    ownedBy: 'Platform Engineering',
    hourlyCostUsd: 4.2,
    notes: 'Closest to production. Required for any test that asserts on payroll outcomes.',
  },
  {
    id: 'env-wd-ephemeral',
    name: 'Ephemeral tenant (per-run)',
    kind: 'ephemeral',
    platform: 'Workday HCM',
    status: 'provisioning',
    fingerprint: {
      environment: 'Ephemeral',
      tenant: 'acme_hcm_eph_7742',
      release: 'Workday 2026R1',
      refreshedAt: '2026-08-07T06:40:00Z',
      dataCoverage: 22,
    },
    readiness: [
      {
        id: 'rd-9',
        text: 'Tenant provisioned',
        met: null,
        evaluatedBy: null,
        detail: 'Provisioning — about 6 minutes remaining',
      },
      { id: 'rd-10', text: 'Seed data loaded', met: null, evaluatedBy: null },
      { id: 'rd-11', text: 'Release matches plan', met: true, evaluatedBy: 'system' },
    ],
    lastRefreshedAt: '2026-08-07T06:40:00Z',
    ownedBy: 'Meridian (automated)',
    hourlyCostUsd: 0.9,
    notes:
      'Created fresh per run and destroyed after. Cheapest option, but the thinnest data — unsuitable for payroll assertions.',
  },
]

/* ------------------------------------------------------------- test plan */

export const TEST_PLANS: TestPlan[] = [
  {
    id: 'tp-1042',
    ref: 'TP-1042',
    requirementId: 'req-1',
    requirementRef: 'MER-1042',
    title: 'Test plan — Auto-approve overtime under 4 hours per week',
    origin: 'ai_edited_by_human',
    state: 'in_review',
    version: 3,
    createdAt: '2026-08-04T11:20:00Z',
    updatedAt: '2026-08-06T15:42:00Z',
    author: 'Meridian agent',
    approvedBy: null,
    approvedAt: null,
    objective:
      'Prove that overtime requests of under four hours per week are auto-approved without changing the amount paid, the audit trail, or the behaviour of any request at or above the four-hour threshold. The change alters an approval chain that SOX ITGC controls depend on, so the plan treats the audit extract as a first-class assertion rather than a side effect.',
    scopeIn: [
      'BP Approval Chain — TIMEOFF_APPR routing behaviour at and around the 4-hour boundary',
      'Overtime calculation totals for auto-approved and manually approved requests',
      'Payroll outbound integration payload equivalence',
      'Approval Audit Extract completeness for auto-approved requests',
      'Manager notification suppression for auto-approved requests',
    ],
    scopeOut: [
      'Mobile push notification delivery (covered by MER-1051, a separate requirement)',
      'Historical back-fill of requests approved before this change ships',
      'Union-agreement workers — excluded by policy, see risk R-3',
    ],
    levels: ['integration', 'system', 'uat', 'regression'],
    types: ['functional', 'data_integrity', 'compliance'],
    entryCriteria: [
      {
        id: 'ec-1',
        text: 'Impact analysis reviewed and agreed with the requester',
        met: true,
        evaluatedBy: 'human',
        detail: 'Agreed by J. Almeida on 4 Aug 2026',
      },
      {
        id: 'ec-2',
        text: 'All graph links touching impacted nodes are confirmed',
        met: true,
        evaluatedBy: 'system',
        detail: '5 of 5 impacted-node links confirmed',
      },
      {
        id: 'ec-3',
        text: 'A test environment on the target release is available',
        met: true,
        evaluatedBy: 'system',
        detail: 'Workday Sandbox (Implementation) — 2026R1',
      },
      {
        id: 'ec-4',
        text: 'Blocking policies evaluated for this change',
        met: true,
        evaluatedBy: 'system',
        detail: 'POL-004 and POL-007 evaluated at planning time',
      },
    ],
    exitCriteria: [
      {
        id: 'xc-1',
        text: 'Every critical and high priority case has passed',
        met: false,
        evaluatedBy: 'system',
        detail: '7 of 8 passed. TC-1042-06 failed on the payroll payload comparison.',
      },
      {
        id: 'xc-2',
        text: 'Every impacted node carries at least one verified test',
        met: false,
        evaluatedBy: 'system',
        detail: 'Approval Audit Extract is covered only by an asserted result.',
      },
      {
        id: 'xc-3',
        text: 'No open defect of major severity or above',
        met: false,
        evaluatedBy: 'system',
        detail: 'DEF-311 (major) is open against the payroll payload difference.',
      },
      {
        id: 'xc-4',
        text: 'Flake rate across the suite is below 10%',
        met: true,
        evaluatedBy: 'system',
        detail: 'Measured 4.2% over 3 executions',
      },
      {
        id: 'xc-5',
        text: 'Residual risks recorded and accepted by an accountable owner',
        met: null,
        evaluatedBy: null,
        detail: 'Cannot be evaluated until closure is opened',
      },
    ],
    risks: [
      {
        id: 'r-1',
        risk: 'Sandbox data coverage is 41%, so scenario classes present in production are absent from the test set.',
        likelihood: 'high',
        mitigation:
          'Run the payroll-equivalence cases in Pre-production, which is a masked production clone at 88% coverage.',
      },
      {
        id: 'r-2',
        risk: 'The audit extract is asserted by an agent rather than verified by a replayable test, because the extract is generated asynchronously.',
        likelihood: 'medium',
        mitigation:
          'Add a deterministic polling assertion before sign-off, or accept as a residual risk with the SOX control owner.',
      },
      {
        id: 'r-3',
        risk: 'Union-agreement workers are out of scope but share the same approval chain, so a regression there would not be caught.',
        likelihood: 'low',
        mitigation:
          'Regression case TC-1042-08 asserts that union-flagged requests still route to a human approver.',
      },
    ],
    coveredNodeIds: ['n-cfg-approval', 'n-cfg-calc', 'n-int-payroll', 'n-rpt-ot'],
    uncoveredNodeIds: ['n-rpt-audit'],
    environmentIds: ['env-wd-impl', 'env-wd-preprod'],
    estimatedCases: 8,
    estimatedDurationHours: 3.5,
    generationCostUsd: 0.84,
    model: 'claude-opus-5',
  },
  {
    id: 'tp-1039',
    ref: 'TP-1039',
    requirementId: 'req-2',
    requirementRef: 'MER-1039',
    title: 'Test plan — Cost centre dimension on absence reporting',
    origin: 'ai_generated',
    state: 'approved',
    version: 1,
    createdAt: '2026-07-30T09:00:00Z',
    updatedAt: '2026-08-01T14:10:00Z',
    author: 'Meridian agent',
    approvedBy: 'K. Tan',
    approvedAt: '2026-08-01T14:10:00Z',
    objective:
      'Confirm that the cost centre dimension appears on absence reports and aggregates correctly, without altering existing report totals.',
    scopeIn: [
      'Overtime Cost by Cost Centre report output',
      'Aggregation correctness across cost centre hierarchies',
      'Existing report totals remain unchanged',
    ],
    scopeOut: ['Report scheduling and distribution', 'Historical restatement of prior periods'],
    levels: ['system', 'regression'],
    types: ['functional', 'data_integrity'],
    entryCriteria: [
      { id: 'ec-5', text: 'Impact analysis reviewed and agreed', met: true, evaluatedBy: 'human' },
      { id: 'ec-6', text: 'Reporting sandbox available', met: true, evaluatedBy: 'system' },
    ],
    exitCriteria: [
      { id: 'xc-6', text: 'All cases passed', met: true, evaluatedBy: 'system' },
      { id: 'xc-7', text: 'No open defects', met: true, evaluatedBy: 'system' },
      {
        id: 'xc-8',
        text: 'Report totals match the pre-change baseline',
        met: true,
        evaluatedBy: 'system',
        detail: 'Byte-identical for all 14 baseline periods',
      },
    ],
    risks: [
      {
        id: 'r-4',
        risk: 'Cost centre hierarchy changes mid-period could produce ambiguous aggregation.',
        likelihood: 'low',
        mitigation: 'Case TC-1039-04 exercises a mid-period hierarchy move.',
      },
    ],
    coveredNodeIds: ['n-rpt-ot', 'n-cfg-calc'],
    uncoveredNodeIds: [],
    environmentIds: ['env-wd-impl'],
    estimatedCases: 4,
    estimatedDurationHours: 1.0,
    generationCostUsd: 0.31,
    model: 'claude-opus-5',
  },
]

/* ------------------------------------------------------------ test cases */

export const TEST_CASES: TestCase[] = [
  {
    id: 'tc-1042-01',
    ref: 'TC-1042-01',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Overtime request of 3.5 hours is auto-approved without manager action',
    origin: 'ai_generated',
    state: 'approved',
    level: 'system',
    type: 'functional',
    priority: 'critical',
    automatable: true,
    preconditions: [
      'Worker W-4471 has no overtime recorded in the current week',
      'Worker is not flagged as union-agreement',
      'BP Approval Chain TIMEOFF_APPR is at version 15 or later',
    ],
    steps: [
      {
        id: 's-1',
        index: 1,
        action: 'Sign in as worker W-4471 and open the overtime request screen',
        expected: 'Request form loads with zero hours recorded for the current week',
      },
      {
        id: 's-2',
        index: 2,
        action: 'Submit an overtime request for 3.5 hours dated within the current week',
        expected: 'Request is accepted and acknowledged on screen',
      },
      {
        id: 's-3',
        index: 3,
        action: 'Inspect the request status immediately after submission',
        expected: 'Status reads Approved. No approval task is created for the line manager.',
      },
    ],
    expectedResult:
      'The request reaches Approved status without a manager task, and the approval event names the automated rule rather than a person.',
    testData: 'Worker W-4471 (non-union, weekly schedule, cost centre CC-2100)',
    coversNodeIds: ['n-cfg-approval', 'n-scr-request'],
    createdAt: '2026-08-04T11:22:00Z',
    updatedAt: '2026-08-04T11:22:00Z',
    author: 'Meridian agent',
    rationale:
      'This is the core happy path named in the requirement. It is the minimum proof that the rule fires at all.',
    rubric: {
      judgeModel: 'claude-opus-5',
      judgedAt: '2026-08-04T11:24:00Z',
      overall: 4.6,
      verdict: 'accept',
      summary:
        'The core happy path, stated precisely enough to run without interpretation. Scored down only on risk coverage, which is correct: this case is not meant to probe the boundary.',
      inputs: ['MER-1042 acceptance criteria', 'BP Approval Chain TIMEOFF_APPR v15', 'Impact analysis — 5 affected nodes'],
      scores: [
        {
          dimension: 'specificity',
          score: 5,
          rationale:
            'Names a concrete worker, a concrete duration and the exact status expected. Nothing is left for the tester to decide.',
          citations: ['Worker W-4471', 'MER-1042 §2.1'],
        },
        {
          dimension: 'traceability',
          score: 5,
          rationale: 'Maps directly onto the requirement’s first acceptance criterion and the approval-chain node it changes.',
          citations: ['MER-1042 §2.1', 'n-cfg-approval'],
        },
        {
          dimension: 'testability',
          score: 5,
          rationale: 'Every step has a machine-checkable expectation. Runs unattended.',
          citations: [],
        },
        {
          dimension: 'risk_coverage',
          score: 3.5,
          rationale:
            'Exercises the rule firing but not the boundary or any failure mode. Adequate as the base case; would be insufficient alone.',
          citations: ['MER-1042 §2.3'],
        },
        {
          dimension: 'evidence_grounding',
          score: 4.5,
          rationale:
            'Asserts on the approval event naming the rule rather than a person, which is the fact the audit extract later depends on.',
          citations: ['n-rpt-audit'],
        },
      ],
    },
    estimatedDurationSeconds: 95,
    tags: ['happy-path', 'approval-chain'],
  },
  {
    id: 'tc-1042-02',
    ref: 'TC-1042-02',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Overtime request of exactly 4.0 hours still routes to the line manager',
    origin: 'ai_edited_by_human',
    state: 'approved',
    level: 'system',
    type: 'functional',
    priority: 'critical',
    automatable: true,
    preconditions: [
      'Worker W-4471 has no overtime recorded in the current week',
      'BP Approval Chain TIMEOFF_APPR is at version 15 or later',
    ],
    steps: [
      {
        id: 's-4',
        index: 1,
        action: 'Submit an overtime request for exactly 4.0 hours',
        expected: 'Request is accepted',
      },
      {
        id: 's-5',
        index: 2,
        action: 'Inspect the request status and the line manager’s task inbox',
        expected: 'Status reads Awaiting approval and a task appears in the line manager’s inbox.',
      },
    ],
    expectedResult:
      'The threshold is exclusive: 4.0 hours is NOT auto-approved and a manager task is created.',
    testData: 'Worker W-4471 (non-union, weekly schedule)',
    coversNodeIds: ['n-cfg-approval'],
    createdAt: '2026-08-04T11:22:00Z',
    updatedAt: '2026-08-05T09:14:00Z',
    author: 'Meridian agent',
    rationale:
      'Boundary case. The requirement says "under 4 hours", so 4.0 exactly must not auto-approve. Edited by a human to assert on the manager inbox rather than only the status field.',
    rubric: {
      judgeModel: 'claude-opus-5',
      judgedAt: '2026-08-04T11:24:00Z',
      overall: 4.1,
      verdict: 'accept',
      // The edit this flag refers to is named in the rationale above: a human
      // strengthened the assertion after the judge had scored it.
      supersededByEdit: true,
      summary:
        'Correct reading of an exclusive threshold. Marked down at the time for asserting only on the status field — which is the gap the human edit then closed.',
      inputs: ['MER-1042 acceptance criteria', 'BP Approval Chain TIMEOFF_APPR v15'],
      scores: [
        {
          dimension: 'specificity',
          score: 4.5,
          rationale: 'States the exact boundary value and that the threshold is exclusive.',
          citations: ['MER-1042 §2.1'],
        },
        {
          dimension: 'traceability',
          score: 4.5,
          rationale:
            'Reads "under 4 hours" strictly, which is the interpretation the requirement text supports.',
          citations: ['MER-1042 §2.1', 'n-cfg-approval'],
        },
        {
          dimension: 'testability',
          score: 4.5,
          rationale: 'Single deterministic submission with an unambiguous expected outcome.',
          citations: [],
        },
        {
          dimension: 'risk_coverage',
          score: 4,
          rationale:
            'Off-by-one at the threshold is the classic defect for a rule of this shape. Covers it directly.',
          citations: [],
        },
        {
          dimension: 'evidence_grounding',
          score: 3,
          rationale:
            'Asserted on the status field alone. A rule that sets the right status but creates no manager task would have passed.',
          citations: [],
        },
      ],
    },
    estimatedDurationSeconds: 88,
    tags: ['boundary', 'approval-chain'],
  },
  {
    id: 'tc-1042-03',
    ref: 'TC-1042-03',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Cumulative weekly total crossing 4 hours routes the crossing request to a manager',
    origin: 'ai_generated',
    state: 'approved',
    level: 'system',
    type: 'functional',
    priority: 'critical',
    automatable: true,
    preconditions: ['Worker W-4472 has 3.0 hours of approved overtime in the current week'],
    steps: [
      {
        id: 's-6',
        index: 1,
        action: 'Submit a further overtime request of 1.5 hours in the same week',
        expected: 'Request is accepted',
      },
      {
        id: 's-7',
        index: 2,
        action: 'Inspect the status of the second request',
        expected: 'Status reads Awaiting approval, because the weekly total would reach 4.5 hours.',
      },
    ],
    expectedResult:
      'The rule evaluates the weekly cumulative total, not the size of the individual request.',
    testData: 'Worker W-4472 with 3.0 hours already approved this week',
    coversNodeIds: ['n-cfg-approval', 'n-cfg-calc'],
    createdAt: '2026-08-04T11:22:00Z',
    updatedAt: '2026-08-04T11:22:00Z',
    author: 'Meridian agent',
    rationale:
      'The requirement says "under 4 hours per week", which is a cumulative constraint. A per-request reading would be a misinterpretation that this case rules out.',
    rubric: {
      judgeModel: 'claude-opus-5',
      judgedAt: '2026-08-04T11:24:00Z',
      overall: 4.4,
      verdict: 'accept',
      summary:
        'Covers the cumulative-total path, which is where the rule is most likely to be implemented wrongly. Preconditions carry the state that makes the case meaningful.',
      inputs: ['MER-1042 acceptance criteria', 'Weekly overtime calculation — n-cfg-calc'],
      scores: [
        {
          dimension: 'specificity',
          score: 4.5,
          rationale: 'States the prior balance (3.0h) explicitly, so the crossing point is unambiguous.',
          citations: ['Worker W-4472'],
        },
        {
          dimension: 'traceability',
          score: 4.5,
          rationale: 'Traces to the per-week wording of the requirement, not merely the per-request reading.',
          citations: ['MER-1042 §2.2', 'n-cfg-calc'],
        },
        {
          dimension: 'testability',
          score: 4.5,
          rationale: 'Deterministic given the stated precondition. No timing dependency.',
          citations: [],
        },
        {
          dimension: 'risk_coverage',
          score: 4.5,
          rationale:
            'Targets the accumulation bug class directly — the most probable defect given the calculation node is being changed.',
          citations: ['Impact: n-cfg-calc, major'],
        },
        {
          dimension: 'evidence_grounding',
          score: 4,
          rationale:
            'Checks routing but does not capture the calculated total itself, so a correct route with a wrong total would still pass.',
          citations: [],
        },
      ],
    },
    estimatedDurationSeconds: 132,
    tags: ['boundary', 'cumulative'],
  },
  {
    id: 'tc-1042-04',
    ref: 'TC-1042-04',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Auto-approved overtime produces an identical payroll payload to manual approval',
    origin: 'ai_generated',
    state: 'approved',
    level: 'integration',
    type: 'data_integrity',
    priority: 'critical',
    automatable: true,
    preconditions: [
      'Payroll outbound integration PAY_OUT_001 is reachable',
      'A manually approved 3.5-hour baseline payload has been captured',
    ],
    steps: [
      {
        id: 's-8',
        index: 1,
        action: 'Submit and auto-approve a 3.5 hour overtime request',
        expected: 'Request reaches Approved status',
      },
      {
        id: 's-9',
        index: 2,
        action: 'Capture the outbound payroll payload for the pay period',
        expected: 'Payload is produced within the integration window',
      },
      {
        id: 's-10',
        index: 3,
        action:
          'Compare the payload against the manually approved baseline, ignoring identifiers and timestamps',
        expected: 'Payloads are field-for-field identical, including the earning code and rate.',
      },
    ],
    expectedResult:
      'Auto-approval changes who approved the request, and nothing about what is paid.',
    testData: 'Baseline payload PAY-BASE-3H5 captured 2026-08-02',
    coversNodeIds: ['n-int-payroll', 'n-cfg-calc'],
    createdAt: '2026-08-04T11:22:00Z',
    updatedAt: '2026-08-04T11:22:00Z',
    author: 'Meridian agent',
    rationale:
      'The requirement explicitly promises no change to payroll outcomes. This is the case that makes that promise falsifiable.',
    rubric: {
      judgeModel: 'claude-opus-5',
      judgedAt: '2026-08-04T11:24:00Z',
      overall: 4.8,
      verdict: 'accept',
      summary:
        'The strongest case in the set. Proves the change is invisible downstream by comparing payloads field for field rather than asserting a status.',
      inputs: ['MER-1042 acceptance criteria', 'Payroll integration contract', 'Impact analysis — n-int-payroll'],
      scores: [
        {
          dimension: 'specificity',
          score: 5,
          rationale: 'Names the comparison basis and requires field-level equality rather than a summary match.',
          citations: ['n-int-payroll'],
        },
        {
          dimension: 'traceability',
          score: 4.5,
          rationale:
            'Derives from the requirement’s "without changing payroll outcomes" clause, which no other case tests.',
          citations: ['MER-1042 §1', 'n-int-payroll'],
        },
        {
          dimension: 'testability',
          score: 5,
          rationale: 'A payload diff is fully mechanical and produces verified evidence.',
          citations: [],
        },
        {
          dimension: 'risk_coverage',
          score: 5,
          rationale:
            'Covers the highest-consequence failure available: a change that silently alters what people are paid.',
          citations: ['Impact: n-int-payroll, breaking'],
        },
        {
          dimension: 'evidence_grounding',
          score: 4.5,
          rationale:
            'Captures both payloads as artefacts, so the conclusion can be re-checked by someone who was not present.',
          citations: [],
        },
      ],
    },
    estimatedDurationSeconds: 340,
    tags: ['payroll', 'equivalence'],
  },
  {
    id: 'tc-1042-05',
    ref: 'TC-1042-05',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Auto-approved requests appear in the SOX approval audit extract',
    origin: 'ai_generated',
    state: 'in_review',
    level: 'integration',
    type: 'compliance',
    priority: 'critical',
    automatable: false,
    preconditions: ['At least one auto-approved request exists in the current period'],
    steps: [
      {
        id: 's-11',
        index: 1,
        action: 'Trigger generation of the Approval Audit Extract for the current period',
        expected: 'Extract completes',
      },
      {
        id: 's-12',
        index: 2,
        action: 'Locate the auto-approved request in the extract',
        expected:
          'A row exists showing the approver as the automated rule identifier, with the rule version.',
      },
    ],
    expectedResult:
      'Every auto-approved request is present in the audit extract and is attributable to a named, versioned rule.',
    testData: 'Current period extract',
    coversNodeIds: ['n-rpt-audit'],
    createdAt: '2026-08-04T11:22:00Z',
    updatedAt: '2026-08-06T15:40:00Z',
    author: 'Meridian agent',
    rationale:
      'SOX ITGC requires every approval to be attributable. An automated approver is still an approver and must appear in the extract.',
    rubric: {
      judgeModel: 'claude-opus-5',
      judgedAt: '2026-08-06T15:41:00Z',
      overall: 3.4,
      verdict: 'revise',
      summary:
        'The right thing to test, described too loosely to run the same way twice. It is also manual, so it cannot produce verified evidence — which matters because this is the case a SOX auditor will ask about.',
      inputs: ['MER-1042 acceptance criteria', 'SOX approval extract specification', 'Policy: evidence-grade'],
      scores: [
        {
          dimension: 'specificity',
          score: 2.5,
          rationale:
            'Says the request should "appear in the extract" without naming the columns or the value expected in the approver field. Two testers would check different things.',
          citations: [],
        },
        {
          dimension: 'traceability',
          score: 4,
          rationale: 'Clearly tied to the audit-extract node and to the SOX control it supports.',
          citations: ['n-rpt-audit', 'SOX-404'],
        },
        {
          dimension: 'testability',
          score: 2.5,
          rationale:
            'Marked not automatable and phrased as an inspection. Produces asserted rather than verified evidence.',
          citations: ['Policy: evidence-grade'],
        },
        {
          dimension: 'risk_coverage',
          score: 4.5,
          rationale:
            'Targets a genuine regulatory exposure: an approval with no named human is exactly what an auditor samples for.',
          citations: ['SOX-404'],
        },
        {
          dimension: 'evidence_grounding',
          score: 3.5,
          rationale: 'No artefact is captured, so the outcome rests on the tester’s word.',
          citations: [],
        },
      ],
    },
    estimatedDurationSeconds: 420,
    tags: ['sox', 'audit', 'needs-automation'],
  },
  {
    id: 'tc-1042-06',
    ref: 'TC-1042-06',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Retroactive overtime for a closed pay period does not auto-approve',
    origin: 'ai_generated',
    state: 'approved',
    level: 'system',
    type: 'functional',
    priority: 'high',
    automatable: true,
    preconditions: ['A pay period exists that is closed but within the retro window'],
    steps: [
      {
        id: 's-13',
        index: 1,
        action: 'Submit a 2.0 hour overtime request dated inside the closed pay period',
        expected: 'Request is accepted as a retroactive entry',
      },
      {
        id: 's-14',
        index: 2,
        action: 'Inspect the routing of the retroactive request',
        expected: 'Status reads Awaiting approval — retroactive entries always need a human.',
      },
    ],
    expectedResult:
      'Retroactive requests bypass auto-approval regardless of hours, because they affect a closed period.',
    testData: 'Pay period 2026-07 (closed 2026-08-03)',
    coversNodeIds: ['n-cfg-approval', 'n-int-payroll'],
    createdAt: '2026-08-04T11:22:00Z',
    updatedAt: '2026-08-04T11:22:00Z',
    author: 'Meridian agent',
    rationale:
      'Not stated in the requirement, but implied by the payroll integration contract. Flagged to the requester as an assumption during impact review.',
    rubric: {
      judgeModel: 'claude-opus-5',
      judgedAt: '2026-08-04T11:24:00Z',
      overall: 4.2,
      verdict: 'accept',
      summary:
        'A negative case for the retroactive path. Well grounded, though it leaves the closed-period boundary itself untested.',
      inputs: ['MER-1042 acceptance criteria', 'Pay period close rules', 'n-int-payroll'],
      scores: [
        {
          dimension: 'specificity',
          score: 4,
          rationale: 'Precondition pins the period state precisely; the expected refusal is stated in full.',
          citations: [],
        },
        {
          dimension: 'traceability',
          score: 4,
          rationale: 'Follows from the retro-window constraint rather than from the requirement text directly.',
          citations: ['Pay period close rules'],
        },
        {
          dimension: 'testability',
          score: 4.5,
          rationale: 'Deterministic once a closed period is seeded.',
          citations: [],
        },
        {
          dimension: 'risk_coverage',
          score: 4.5,
          rationale: 'Retroactive auto-approval into a closed period would be a restatement-grade defect.',
          citations: ['Impact: n-int-payroll, breaking'],
        },
        {
          dimension: 'evidence_grounding',
          score: 4,
          rationale: 'Checks the refusal but not the reason given, so a right answer for a wrong reason would pass.',
          citations: [],
        },
      ],
    },
    estimatedDurationSeconds: 210,
    tags: ['edge-case', 'retro'],
  },
  {
    id: 'tc-1042-07',
    ref: 'TC-1042-07',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Manager receives no approval notification for auto-approved requests',
    origin: 'ai_generated',
    state: 'approved',
    level: 'system',
    type: 'functional',
    priority: 'medium',
    automatable: true,
    preconditions: ['Line manager M-220 has notifications enabled'],
    steps: [
      {
        id: 's-15',
        index: 1,
        action: 'Submit a 1.0 hour overtime request as a worker reporting to M-220',
        expected: 'Request auto-approves',
      },
      {
        id: 's-16',
        index: 2,
        action: 'Inspect the manager notification queue',
        expected: 'No approval-request notification was generated.',
      },
    ],
    expectedResult:
      'Auto-approval suppresses the approval notification, which is the workload reduction the requirement asks for.',
    testData: 'Manager M-220, worker W-4473',
    coversNodeIds: ['n-cfg-approval', 'n-scr-request'],
    createdAt: '2026-08-04T11:22:00Z',
    updatedAt: '2026-08-04T11:22:00Z',
    author: 'Meridian agent',
    rationale:
      'The stated business benefit is reduced manager workload. If notifications still fire, the requirement is not met even though routing is correct.',
    rubric: {
      judgeModel: 'claude-opus-5',
      judgedAt: '2026-08-04T11:24:00Z',
      overall: 3.2,
      verdict: 'revise',
      summary:
        'Asserting the absence of a notification is the weakest shape of test there is: it passes when the queue is merely slow. Needs a bounded wait and a positive control.',
      inputs: ['MER-1042 acceptance criteria', 'Notification queue design note'],
      scores: [
        {
          dimension: 'specificity',
          score: 3.5,
          rationale: 'Names the manager and the channel, but not how long to wait before concluding nothing arrived.',
          citations: ['Manager M-220'],
        },
        {
          dimension: 'traceability',
          score: 4,
          rationale: 'Supports the "no manager action" clause from the requirement.',
          citations: ['MER-1042 §2.1'],
        },
        {
          dimension: 'testability',
          score: 2,
          rationale:
            'Timing-sensitive by construction. An empty queue read proves nothing without a bound, and this case has since been observed flaky.',
          citations: ['DEF-318'],
        },
        {
          dimension: 'risk_coverage',
          score: 3.5,
          rationale: 'A spurious notification is a nuisance rather than a control failure. Lower stakes than the payroll path.',
          citations: [],
        },
        {
          dimension: 'evidence_grounding',
          score: 3,
          rationale: 'Absence of a record is weak evidence. No positive control confirms the check itself works.',
          citations: [],
        },
      ],
    },
    estimatedDurationSeconds: 76,
    tags: ['notification'],
  },
  {
    id: 'tc-1042-08',
    ref: 'TC-1042-08',
    planId: 'tp-1042',
    requirementId: 'req-1',
    title: 'Union-agreement workers continue to route to a human approver',
    origin: 'human_authored',
    state: 'approved',
    level: 'regression',
    type: 'compliance',
    priority: 'high',
    automatable: true,
    preconditions: ['Worker W-4480 is flagged as union-agreement'],
    steps: [
      {
        id: 's-17',
        index: 1,
        action: 'Submit a 1.5 hour overtime request as W-4480',
        expected: 'Request is accepted',
      },
      {
        id: 's-18',
        index: 2,
        action: 'Inspect routing',
        expected: 'Status reads Awaiting approval despite being under the threshold.',
      },
    ],
    expectedResult:
      'The union exclusion holds. Auto-approval never applies to union-agreement workers.',
    testData: 'Worker W-4480 (union-agreement, local 512)',
    coversNodeIds: ['n-cfg-approval'],
    createdAt: '2026-08-05T10:02:00Z',
    updatedAt: '2026-08-05T10:02:00Z',
    author: 'S. Okonkwo',
    rationale:
      'Added by a human after the agent scoped union workers out. Scoping something out of a change does not scope it out of regression risk — they share the approval chain.',
    estimatedDurationSeconds: 84,
    tags: ['regression', 'union', 'human-added'],
  },
]

/* ----------------------------------------------------------------- suites */

export const TEST_SUITES: TestSuite[] = [
  {
    id: 'ts-smoke',
    ref: 'TS-01',
    name: 'Approval routing smoke',
    description:
      'The three routing cases that must pass before any deeper testing is worth running.',
    caseIds: ['tc-1042-01', 'tc-1042-02', 'tc-1042-03'],
    saved: true,
    createdAt: '2026-08-04T12:00:00Z',
    createdBy: 'Meridian agent',
  },
  {
    id: 'ts-payroll',
    ref: 'TS-02',
    name: 'Payroll equivalence',
    description:
      'Cases that assert payroll outcomes are unchanged. Must run in Pre-production — sandbox data is too thin.',
    caseIds: ['tc-1042-04', 'tc-1042-06'],
    saved: true,
    createdAt: '2026-08-04T12:00:00Z',
    createdBy: 'Meridian agent',
  },
  {
    id: 'ts-compliance',
    ref: 'TS-03',
    name: 'SOX compliance',
    description: 'Audit attributability and the union exclusion.',
    caseIds: ['tc-1042-05', 'tc-1042-08'],
    saved: true,
    createdAt: '2026-08-05T10:30:00Z',
    createdBy: 'S. Okonkwo',
  },
  {
    id: 'ts-full',
    ref: 'TS-04',
    name: 'Full regression',
    description: 'Every approved case for MER-1042.',
    caseIds: [
      'tc-1042-01',
      'tc-1042-02',
      'tc-1042-03',
      'tc-1042-04',
      'tc-1042-06',
      'tc-1042-07',
      'tc-1042-08',
    ],
    saved: true,
    createdAt: '2026-08-05T16:00:00Z',
    createdBy: 'Meridian agent',
  },
]

/* ------------------------------------------------------------- executions */

const WD_IMPL_FP = TEST_ENVIRONMENTS[0].fingerprint
const WD_PREPROD_FP = TEST_ENVIRONMENTS[1].fingerprint

const RESULTS_LATEST: CaseResult[] = [
  {
    id: 'cr-1',
    caseId: 'tc-1042-01',
    caseRef: 'TC-1042-01',
    caseTitle: 'Overtime request of 3.5 hours is auto-approved without manager action',
    status: 'passed',
    grade: 'verified',
    expected: 'Status reads Approved. No approval task is created for the line manager.',
    actual: 'Status read Approved at +1.2s. Manager task inbox count unchanged (0 new tasks).',
    deviation: null,
    durationSeconds: 92,
    attempts: 1,
    startedAt: '2026-08-06T14:02:11Z',
    artifacts: [
      {
        id: 'a-1',
        kind: 'video',
        label: 'Session recording',
        sizeLabel: '4.2 MB',
        sha256: 'b41c9e7a5d2f8e13',
      },
      {
        id: 'a-2',
        kind: 'trace',
        label: 'Execution trace',
        sizeLabel: '812 KB',
        sha256: '7fa2c04e91bd6a55',
      },
    ],
    coversNodeIds: ['n-cfg-approval', 'n-scr-request'],
  },
  {
    id: 'cr-2',
    caseId: 'tc-1042-02',
    caseRef: 'TC-1042-02',
    caseTitle: 'Overtime request of exactly 4.0 hours still routes to the line manager',
    status: 'passed',
    grade: 'verified',
    expected: 'Status reads Awaiting approval and a task appears in the line manager’s inbox.',
    actual: 'Status read Awaiting approval. One task created for M-220 at +0.9s.',
    deviation: null,
    durationSeconds: 85,
    attempts: 1,
    startedAt: '2026-08-06T14:03:47Z',
    artifacts: [
      {
        id: 'a-3',
        kind: 'video',
        label: 'Session recording',
        sizeLabel: '3.8 MB',
        sha256: 'c92d1f60b7e4a238',
      },
    ],
    coversNodeIds: ['n-cfg-approval'],
  },
  {
    id: 'cr-3',
    caseId: 'tc-1042-03',
    caseRef: 'TC-1042-03',
    caseTitle: 'Cumulative weekly total crossing 4 hours routes the crossing request to a manager',
    status: 'passed',
    grade: 'verified',
    expected: 'Status reads Awaiting approval, because the weekly total would reach 4.5 hours.',
    actual: 'Status read Awaiting approval. Rule log shows cumulative evaluation at 4.5h.',
    deviation: null,
    durationSeconds: 128,
    attempts: 1,
    startedAt: '2026-08-06T14:05:14Z',
    artifacts: [
      {
        id: 'a-4',
        kind: 'trace',
        label: 'Rule evaluation log',
        sizeLabel: '96 KB',
        sha256: '2ed7b8c1449f0a6d',
      },
    ],
    coversNodeIds: ['n-cfg-approval', 'n-cfg-calc'],
  },
  {
    id: 'cr-4',
    caseId: 'tc-1042-04',
    caseRef: 'TC-1042-04',
    caseTitle: 'Auto-approved overtime produces an identical payroll payload to manual approval',
    status: 'failed',
    grade: 'verified',
    expected: 'Payloads are field-for-field identical, including the earning code and rate.',
    actual:
      'All fields matched except approvalSource, which read "RULE:OT_AUTO_APPR" against the baseline "USER:M-220". The earning code, hours and rate were identical.',
    deviation:
      'One field differs. The payroll vendor contract does not list approvalSource as an accepted value domain, so a rule identifier may be rejected downstream even though the paid amount is unchanged.',
    durationSeconds: 356,
    attempts: 2,
    startedAt: '2026-08-06T14:07:29Z',
    artifacts: [
      {
        id: 'a-5',
        kind: 'network',
        label: 'Payload diff',
        sizeLabel: '18 KB',
        sha256: 'e5b3971c02da4f88',
      },
      {
        id: 'a-6',
        kind: 'log',
        label: 'Integration log',
        sizeLabel: '244 KB',
        sha256: '1c8fa4d7e3902b56',
      },
    ],
    coversNodeIds: ['n-int-payroll', 'n-cfg-calc'],
    defectRef: 'DEF-311',
  },
  {
    id: 'cr-5',
    caseId: 'tc-1042-05',
    caseRef: 'TC-1042-05',
    caseTitle: 'Auto-approved requests appear in the SOX approval audit extract',
    status: 'passed',
    grade: 'asserted',
    expected:
      'A row exists showing the approver as the automated rule identifier, with the rule version.',
    actual:
      'Agent reported that it located the auto-approved request in the extract with approver "RULE:OT_AUTO_APPR v15". No deterministic artifact was produced — the extract is generated asynchronously and the agent polled until it appeared.',
    deviation: null,
    durationSeconds: 402,
    attempts: 1,
    startedAt: '2026-08-06T14:13:25Z',
    artifacts: [
      {
        id: 'a-7',
        kind: 'screenshot',
        label: 'Extract row (agent capture)',
        sizeLabel: '188 KB',
        sha256: '9d1e740fb26c3a81',
      },
    ],
    coversNodeIds: ['n-rpt-audit'],
  },
  {
    id: 'cr-6',
    caseId: 'tc-1042-06',
    caseRef: 'TC-1042-06',
    caseTitle: 'Retroactive overtime for a closed pay period does not auto-approve',
    status: 'passed',
    grade: 'verified',
    expected: 'Status reads Awaiting approval — retroactive entries always need a human.',
    actual: 'Status read Awaiting approval. Retro flag present on the request record.',
    deviation: null,
    durationSeconds: 198,
    attempts: 1,
    startedAt: '2026-08-06T14:20:07Z',
    artifacts: [
      {
        id: 'a-8',
        kind: 'trace',
        label: 'Execution trace',
        sizeLabel: '412 KB',
        sha256: '6b0af92d15e8c374',
      },
    ],
    coversNodeIds: ['n-cfg-approval', 'n-int-payroll'],
  },
  {
    id: 'cr-7',
    caseId: 'tc-1042-07',
    caseRef: 'TC-1042-07',
    caseTitle: 'Manager receives no approval notification for auto-approved requests',
    status: 'flaky',
    grade: 'verified',
    expected: 'No approval-request notification was generated.',
    actual:
      'Passed on attempt 2. Attempt 1 observed a notification, which a retry did not reproduce — the notification queue is eventually consistent and was read too early.',
    deviation:
      'Result is correct but the case has a timing weakness: it reads the queue without waiting for it to settle.',
    durationSeconds: 154,
    attempts: 2,
    startedAt: '2026-08-06T14:23:31Z',
    artifacts: [
      {
        id: 'a-9',
        kind: 'log',
        label: 'Notification queue log',
        sizeLabel: '64 KB',
        sha256: 'af27e6031b9d485c',
      },
    ],
    coversNodeIds: ['n-cfg-approval', 'n-scr-request'],
  },
  {
    id: 'cr-8',
    caseId: 'tc-1042-08',
    caseRef: 'TC-1042-08',
    caseTitle: 'Union-agreement workers continue to route to a human approver',
    status: 'passed',
    grade: 'verified',
    expected: 'Status reads Awaiting approval despite being under the threshold.',
    actual: 'Status read Awaiting approval. Union exclusion matched on worker flag.',
    deviation: null,
    durationSeconds: 81,
    attempts: 1,
    startedAt: '2026-08-06T14:26:12Z',
    artifacts: [
      {
        id: 'a-10',
        kind: 'video',
        label: 'Session recording',
        sizeLabel: '3.1 MB',
        sha256: '4e8c25a70fd193b6',
      },
    ],
    coversNodeIds: ['n-cfg-approval'],
  },
]

export const TEST_EXECUTIONS: TestExecution[] = [
  {
    id: 'te-3',
    ref: 'EX-1042-03',
    requirementId: 'req-1',
    planId: 'tp-1042',
    suiteId: 'ts-full',
    suiteName: 'Full regression',
    environmentId: 'env-wd-impl',
    environment: WD_IMPL_FP,
    status: 'failed',
    triggeredBy: 'S. Okonkwo',
    triggeredByType: 'human',
    startedAt: '2026-08-06T14:02:00Z',
    finishedAt: '2026-08-06T14:27:40Z',
    results: RESULTS_LATEST,
    costUsd: 3.42,
    preflight: [
      { id: 'pf-1', text: 'Environment reachable', met: true, evaluatedBy: 'system' },
      { id: 'pf-2', text: 'Release matches plan', met: true, evaluatedBy: 'system' },
      {
        id: 'pf-3',
        text: 'Data coverage sufficient for selected cases',
        met: false,
        evaluatedBy: 'system',
        detail:
          'Sandbox coverage is 41%. TC-1042-04 asserts on payroll and would be better run in Pre-production. Proceeded with acknowledgement.',
      },
    ],
  },
  {
    id: 'te-2',
    ref: 'EX-1042-02',
    requirementId: 'req-1',
    planId: 'tp-1042',
    suiteId: 'ts-smoke',
    suiteName: 'Approval routing smoke',
    environmentId: 'env-wd-impl',
    environment: WD_IMPL_FP,
    status: 'passed',
    triggeredBy: 'Meridian agent',
    triggeredByType: 'agent',
    startedAt: '2026-08-05T17:10:00Z',
    finishedAt: '2026-08-05T17:16:22Z',
    results: RESULTS_LATEST.slice(0, 3),
    costUsd: 0.91,
    preflight: [
      { id: 'pf-4', text: 'Environment reachable', met: true, evaluatedBy: 'system' },
      { id: 'pf-5', text: 'Release matches plan', met: true, evaluatedBy: 'system' },
    ],
  },
  {
    id: 'te-1',
    ref: 'EX-1042-01',
    requirementId: 'req-1',
    planId: 'tp-1042',
    suiteId: 'ts-payroll',
    suiteName: 'Payroll equivalence',
    environmentId: 'env-wd-preprod',
    environment: WD_PREPROD_FP,
    status: 'blocked',
    triggeredBy: 'S. Okonkwo',
    triggeredByType: 'human',
    startedAt: '2026-08-05T11:30:00Z',
    finishedAt: '2026-08-05T11:30:12Z',
    results: [],
    costUsd: 0,
    preflight: [
      { id: 'pf-6', text: 'Environment reachable', met: true, evaluatedBy: 'system' },
      { id: 'pf-7', text: 'Release matches plan', met: true, evaluatedBy: 'system' },
      {
        id: 'pf-8',
        text: 'Payroll outbound integration responding',
        met: false,
        evaluatedBy: 'system',
        detail: 'PAY_OUT_001 returning 503. Vendor incident INC-88214.',
      },
    ],
    blockedReason:
      'The payroll outbound integration was unavailable. Running would have produced a false failure on every payload comparison, so the execution was stopped before any case ran.',
  },
]

/* -------------------------------------------------------------- closure */

export const TEST_CLOSURES: TestClosure[] = [
  {
    id: 'cl-1042',
    requirementId: 'req-1',
    requirementRef: 'MER-1042',
    planId: 'tp-1042',
    executionIds: ['te-1', 'te-2', 'te-3'],
    exitCriteria: TEST_PLANS[0].exitCriteria,
    state: 'open',
    closedBy: null,
    closedAt: null,
    summary: {
      casesTotal: 8,
      passed: 6,
      failed: 1,
      blocked: 0,
      notRun: 1,
      verified: 6,
      asserted: 1,
    },
    openDefects: [
      {
        ref: 'DEF-311',
        title:
          'Payroll payload carries a rule identifier in approvalSource, which is outside the vendor’s accepted value domain',
        severity: 'major',
        owner: 'Integration Engineering',
      },
      {
        ref: 'DEF-314',
        title: 'Notification queue read is timing-sensitive, making TC-1042-07 flaky',
        severity: 'minor',
        owner: 'QA Automation',
      },
    ],
    residualRisks: [
      {
        area: 'Audit extract attributability',
        reason:
          'Proven only by an agent assertion, not a replayable test. If the extract format changes, nothing would catch it.',
        acceptedBy: null,
      },
      {
        area: 'Union-agreement workers',
        reason:
          'One regression case covers the exclusion, but no case exercises a union worker crossing the 4-hour threshold.',
        acceptedBy: null,
      },
      {
        area: 'Sandbox data coverage',
        reason:
          'Executed at 41% scenario coverage. Production contains worker categories absent from the test set.',
        acceptedBy: 'S. Okonkwo',
      },
    ],
    lessons: [
      'Payload equivalence should have been run in Pre-production from the start; the sandbox run cost a full cycle to discover a difference that Pre-production data would have surfaced immediately.',
      'The audit extract needs a deterministic polling assertion before this pattern is reused on any other SOX-controlled approval chain.',
    ],
    totalCostUsd: 4.33,
    totalDurationHours: 2.1,
  },
  {
    id: 'cl-1039',
    requirementId: 'req-2',
    requirementRef: 'MER-1039',
    planId: 'tp-1039',
    executionIds: [],
    exitCriteria: TEST_PLANS[1].exitCriteria,
    state: 'closed',
    closedBy: 'K. Tan',
    closedAt: '2026-08-05T16:22:00Z',
    summary: {
      casesTotal: 4,
      passed: 4,
      failed: 0,
      blocked: 0,
      notRun: 0,
      verified: 4,
      asserted: 0,
    },
    openDefects: [],
    residualRisks: [
      {
        area: 'Mid-period hierarchy moves',
        reason:
          'Covered by one case, but the production hierarchy changes more often than the test data reflects.',
        acceptedBy: 'K. Tan',
      },
    ],
    lessons: ['Report baselines held byte-identical, so the regression approach is worth reusing.'],
    totalCostUsd: 1.12,
    totalDurationHours: 0.8,
  },
]

/* ------------------------------------------------------------- defects */

/**
 * Defects raised from execution results.
 *
 * These are the two already named in the closure record — modelled properly
 * rather than as bare refs, so the cycle can account for what happened between
 * "a test failed" and "sign it off".
 *
 * Deliberately unhappy, in the same spirit as the rest of this data: one major
 * defect is claimed fixed but has never been re-tested, which is exactly the
 * state a closure gate must catch rather than wave through.
 */
export const DEFECTS: Defect[] = [
  {
    id: 'def-311',
    ref: 'DEF-311',
    requirementId: 'req-1',
    executionId: 'exe-1042-03',
    caseId: 'tc-1042-04',
    caseRef: 'TC-1042-04',
    title:
      'Payroll payload carries a rule identifier in approvalSource, which is outside the vendor’s accepted value domain',
    expected: 'Payloads are field-for-field identical, including the earning code and rate.',
    actual:
      'All fields matched except approvalSource, which read "RULE:OT_AUTO_APPR" against the baseline "USER:M-220".',
    severity: 'major',
    status: 'fixed',
    owner: 'Integration Engineering',
    raisedBy: 'S. Okonkwo',
    raisedByType: 'human_authored',
    raisedAt: '2026-08-06T14:22:00Z',
    updatedAt: '2026-08-07T09:15:00Z',
    notes: [
      {
        at: '2026-08-06T14:22:00Z',
        by: 'S. Okonkwo',
        text: 'Raised from TC-1042-04. Paid amount is unchanged, but the vendor contract does not list approvalSource as an accepted value domain.',
      },
      {
        at: '2026-08-07T09:15:00Z',
        by: 'D. Fischer',
        text: 'Mapping updated to emit USER:SYSTEM with the rule id moved into the audit annotation. Needs a re-test against the payroll integration.',
      },
    ],
    /* Claimed fixed, never re-tested — the gap the closure gate must catch. */
    retestExecutionIds: [],
    verifiedByExecutionId: null,
    affectedNodeIds: ['n-int-payroll', 'n-cfg-calc'],
  },
  {
    id: 'def-314',
    ref: 'DEF-314',
    requirementId: 'req-1',
    executionId: 'exe-1042-03',
    caseId: 'tc-1042-07',
    caseRef: 'TC-1042-07',
    title: 'Notification queue read is timing-sensitive, making TC-1042-07 flaky',
    expected: 'No approval notification is sent for an auto-approved request.',
    actual:
      'The assertion passes on a warm queue and intermittently fails on a cold one — the read happens before the queue has drained.',
    severity: 'minor',
    status: 'open',
    owner: 'QA Automation',
    raisedBy: 'Meridian agent',
    raisedByType: 'ai_generated',
    raisedAt: '2026-08-06T14:31:00Z',
    updatedAt: '2026-08-06T14:31:00Z',
    notes: [
      {
        at: '2026-08-06T14:31:00Z',
        by: 'Meridian agent',
        text: 'Flagged after the case passed on attempt 2 having failed on attempt 1 with no code change in between.',
      },
    ],
    retestExecutionIds: [],
    verifiedByExecutionId: null,
    affectedNodeIds: ['n-cfg-approval'],
  },
]

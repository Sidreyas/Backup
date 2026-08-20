import { useMemo } from 'react'
import { api } from './api'
import { useAsync, useAsyncList } from './useAsync'
import { TEST_LEVEL_LABEL } from '@/components/domain/status'
import type { StlcPhase, StlcSubject } from '@/components/domain/StlcRail'
import type { Criterion, TestCase, TestClosure, TestExecution, TestLevel, TestPlan } from './types'

/** Every phase hangs off one requirement, so the whole rail is scoped by it. */
export const DEFAULT_REQUIREMENT_ID = 'req-1'

/** Lifecycle order, not alphabetical — this is the sequence the STLC runs in. */
export const LEVEL_ORDER: TestLevel[] = ['unit', 'integration', 'system', 'uat', 'regression']

export function criteriaMet(list: Criterion[]) {
  return list.filter((c) => c.met === true).length
}

export function criteriaUnmet(list: Criterion[]) {
  return list.filter((c) => c.met === false).length
}

/** All exit criteria explicitly satisfied — null (unevaluated) does not count. */
export function allMet(list: Criterion[]) {
  return list.length > 0 && list.every((c) => c.met === true)
}

/**
 * Loads every STLC artefact for a requirement and derives the phase rail from
 * it. Both the rail and each page read from this, so the navigation can never
 * claim a phase is open while the page inside it says otherwise.
 */
export function useStlc(requirementId: string = DEFAULT_REQUIREMENT_ID) {
  const { data: plan, loading: planLoading } = useAsync(
    () => api.getTestPlan(requirementId),
    [requirementId],
  )
  const { items: allCases, loading: casesLoading } = useAsyncList(() => api.getTestCases(), [])
  const { items: executions, loading: execLoading } = useAsyncList(
    () => api.getTestExecutions(),
    [],
  )
  const { data: closure, loading: closureLoading } = useAsync(
    () => api.getTestClosure(requirementId),
    [requirementId],
  )

  /* The requirement is what travels through the cycle, so the rail names it. */
  const { data: requirement } = useAsync(() => api.getRequirement(requirementId), [requirementId])

  const cases = useMemo(
    () => allCases.filter((c) => c.requirementId === requirementId),
    [allCases, requirementId],
  )

  const runs = useMemo(
    () => executions.filter((e) => e.requirementId === requirementId),
    [executions, requirementId],
  )

  const phases = useMemo(
    () => derivePhases({ plan, cases, runs, closure }),
    [plan, cases, runs, closure],
  )

  const subject: StlcSubject | undefined = requirement
    ? {
        ref: requirement.ref,
        title: requirement.title,
        to: `/requirements/${requirement.id}`,
      }
    : undefined

  return {
    plan,
    cases,
    executions: runs,
    closure,
    phases,
    requirement,
    subject,
    loading: planLoading || casesLoading || execLoading || closureLoading,
  }
}

function derivePhases({
  plan,
  cases,
  runs,
  closure,
}: {
  plan: TestPlan | null | undefined
  cases: TestCase[]
  runs: TestExecution[]
  closure: TestClosure | null | undefined
}): StlcPhase[] {
  const planApproved = plan?.state === 'approved'
  const approvedCases = cases.filter((c) => c.state === 'approved')
  const inReview = cases.filter((c) => c.state === 'in_review').length
  const hasRun = runs.some((r) => r.results.length > 0)
  const exitReady = closure ? allMet(closure.exitCriteria) : false

  /*
   * Planning is always reachable — it is the entry point of the cycle.
   *
   * The detail line states this step's *status*, not the artefact's ref. The
   * requirement is the subject of the cycle and is named once above the rail;
   * repeating TP-1042 here put the plan's identity where the subject's belongs.
   */
  const planPhase: StlcPhase = {
    id: 'plan',
    label: 'Test plan',
    to: '/test-plan',
    detail: plan
      ? plan.state === 'approved'
        ? `Approved · v${plan.version}`
        : plan.state === 'in_review'
          ? `In review · v${plan.version}`
          : `Draft · v${plan.version}`
      : 'Not started',
    state: planApproved ? 'done' : 'current',
  }

  /*
   * Design opens as soon as a plan exists, even before approval — teams draft
   * cases against a plan under review, and blocking that would be pedantic
   * rather than safe. Execution is where the plan's approval starts to matter.
   */
  const designPhase: StlcPhase = {
    id: 'design',
    label: 'Test cases',
    to: '/test-cases',
    detail: plan
      ? `${cases.length} case${cases.length === 1 ? '' : 's'}${inReview > 0 ? ` · ${inReview} in review` : ''}`
      : 'Needs a plan',
    state: !plan
      ? 'locked'
      : approvedCases.length > 0 && inReview === 0
        ? 'done'
        : planApproved
          ? 'current'
          : 'available',
    lockedReason: 'A test plan must exist before cases can be written against it.',
  }

  /*
   * The execution step names the test levels in play. "3 executions · 7
   * runnable" said how much work there was but not what kind — and in the
   * STLC the kind is the point: system, UAT and regression testing answer
   * different questions and are signed off against different criteria.
   */
  const levelsInPlay = LEVEL_ORDER.filter((l) => approvedCases.some((c) => c.level === l)).map(
    (l) => TEST_LEVEL_LABEL[l],
  )

  const executePhase: StlcPhase = {
    id: 'execute',
    label: 'Test execution',
    to: '/test-runs',
    detail:
      approvedCases.length === 0
        ? 'Needs approved cases'
        : levelsInPlay.length > 0
          ? levelsInPlay.join(' · ')
          : `${approvedCases.length} runnable`,
    state:
      approvedCases.length === 0
        ? 'locked'
        : hasRun
          ? closure?.state === 'closed'
            ? 'done'
            : 'current'
          : 'available',
    lockedReason:
      'At least one test case must be approved before it can be executed. Approve cases on the Test cases screen.',
  }

  const closePhase: StlcPhase = {
    id: 'close',
    label: 'Test closure',
    to: '/test-closure',
    detail: !hasRun
      ? 'Needs an execution'
      : closure?.state === 'closed'
        ? `Closed ${closure.closedBy ? `by ${closure.closedBy}` : ''}`.trim()
        : exitReady
          ? 'Ready to close'
          : `${criteriaUnmet(closure?.exitCriteria ?? [])} exit criteri${
              criteriaUnmet(closure?.exitCriteria ?? []) === 1 ? 'on' : 'a'
            } unmet`,
    state: !hasRun
      ? 'locked'
      : closure?.state === 'closed' || closure?.state === 'closed_with_deviations'
        ? 'done'
        : 'current',
    lockedReason: 'A cycle cannot be closed before any tests have run.',
  }

  return [planPhase, designPhase, executePhase, closePhase]
}

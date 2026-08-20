import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Bug,
  CheckCircle2,
  ChevronRight,
  CircleStop,
  Clock,
  FlaskConical,
  Layers,
  Loader2,
  Play,
  RotateCcw,
  Server,
  ShieldCheck,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Meter,
  SectionLabel,
  Segmented,
  Skeleton,
  StatTile,
} from '@/components/ui/primitives'
import { Drawer, Modal, Tooltip, useToast } from '@/components/ui/overlays'
import {
  CriterionIcon,
  DefectSeverityBadge,
  DefectStatusBadge,
  EnvironmentStatusBadge,
  EvidenceGradeBadge,
  ExecutionStatusBadge,
  PriorityBadge,
  RunStatusBadge,
  TEST_LEVEL_LABEL,
} from '@/components/domain/status'
import { StlcRail } from '@/components/domain/StlcRail'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { DEFAULT_REQUIREMENT_ID, LEVEL_ORDER, criteriaUnmet, useStlc } from '@/lib/useStlc'
import { blockingDefects, isSettled, isUnverifiedFix, useDefects } from '@/lib/useDefects'
import { cn, formatDateTime, formatDuration, formatUsd, relativeTime } from '@/lib/utils'
import type {
  CaseResult,
  Defect,
  DefectSeverity,
  DefectStatus,
  TestCase,
  TestEnvironment,
  TestExecution,
  TestSuite,
} from '@/lib/types'

export function TestRunsPage() {
  const { cases, executions: fetchedRuns, phases, subject, loading } = useStlc()
  const { items: environments } = useAsyncList(() => api.getTestEnvironments(), [])
  const { items: suites } = useAsyncList(() => api.getTestSuites(), [])

  const [runs, setRuns] = useState<TestExecution[]>([])
  const [selectedCases, setSelectedCases] = useState<Set<string>>(new Set())
  const [envId, setEnvId] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const [liveResults, setLiveResults] = useState<CaseResult[]>([])
  const [liveTotal, setLiveTotal] = useState(0)
  const [openRun, setOpenRun] = useState<TestExecution | null>(null)
  const [tab, setTab] = useState<'setup' | 'history' | 'defects'>('setup')
  const { defects, raise, setStatus, recordRetest } = useDefects()
  /** Defects the cycle still owes something on — the re-test worklist. */
  const unsettledDefects = useMemo(() => blockingDefects(defects), [defects])
  const [raiseFrom, setRaiseFrom] = useState<{ run: TestExecution; result: CaseResult } | null>(
    null,
  )
  const { push } = useToast()

  useEffect(() => {
    if (fetchedRuns.length > 0) setRuns(fetchedRuns)
  }, [fetchedRuns])

  useEffect(() => {
    if (!envId && environments.length > 0) setEnvId(environments[0].id)
  }, [environments, envId])

  /** Only approved cases may be executed — the gate the design phase enforces. */
  const runnable = useMemo(() => cases.filter((c) => c.state === 'approved'), [cases])
  const env = useMemo(() => environments.find((e) => e.id === envId) ?? null, [environments, envId])

  const selectedList = useMemo(
    () => runnable.filter((c) => selectedCases.has(c.id)),
    [runnable, selectedCases],
  )

  /**
   * Cases grouped by test level, in STLC order.
   *
   * The order is fixed rather than derived from the data: unit → integration →
   * system → UAT → regression is the sequence the lifecycle runs in, and
   * sorting by case count or name would scramble a meaningful progression.
   */
  const levelGroups = useMemo(
    () =>
      LEVEL_ORDER.map((level) => ({
        level,
        cases: runnable.filter((c) => c.level === level),
      })).filter((g) => g.cases.length > 0),
    [runnable],
  )

  /** Level labels present in the current selection, in lifecycle order. */
  const selectedLevels = useMemo(
    () =>
      levelGroups
        .filter((g) => g.cases.some((c) => selectedCases.has(c.id)))
        .map((g) => TEST_LEVEL_LABEL[g.level]),
    [levelGroups, selectedCases],
  )

  /** Select or clear a whole level at once. */
  const toggleLevel = useCallback((ids: string[], select: boolean) => {
    setSelectedCases((s) => {
      const next = new Set(s)
      for (const id of ids) {
        if (select) next.add(id)
        else next.delete(id)
      }
      return next
    })
  }, [])

  const estimate = useMemo(
    () => ({
      seconds: selectedList.reduce((a, c) => a + c.estimatedDurationSeconds, 0),
      costUsd: selectedList.length * 0.42 + (env ? env.hourlyCostUsd * 0.15 : 0),
      manual: selectedList.filter((c) => !c.automatable).length,
    }),
    [selectedList, env],
  )

  const blockers = env ? criteriaUnmet(env.readiness) : 0
  const unevaluated = env ? env.readiness.filter((r) => r.met === null).length : 0
  const canRun = selectedList.length > 0 && env !== null && env.status !== 'offline' && !running

  const toggleCase = useCallback((id: string) => {
    setSelectedCases((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const applySuite = useCallback(
    (suite: TestSuite) => {
      // A suite may name cases that are not approved; only offer the runnable ones.
      const ids = suite.caseIds.filter((id) => runnable.some((c) => c.id === id))
      setSelectedCases(new Set(ids))
      const skipped = suite.caseIds.length - ids.length
      push({
        tone: skipped > 0 ? 'warn' : 'info',
        title: `${suite.name} selected`,
        description:
          skipped > 0
            ? `${ids.length} of ${suite.caseIds.length} cases selected. ${skipped} skipped because they are not approved.`
            : `${ids.length} cases selected.`,
      })
    },
    [runnable, push],
  )

  async function launch() {
    if (!env) return
    setConfirmOpen(false)
    setRunning(true)
    setLiveResults([])
    setLiveTotal(selectedList.length)

    const execution = await api.runTestExecution(
      {
        caseIds: selectedList.map((c) => c.id),
        environmentId: env.id,
        suiteName: `Ad-hoc selection (${selectedList.length} cases)`,
      },
      ({ result }) => setLiveResults((r) => [...r, result]),
    )

    setRunning(false)
    setRuns((list) => [execution, ...list])
    setLiveResults([])
    setSelectedCases(new Set())
    // Land on the result rather than on an emptied picker: the run that just
    // finished is what the user is now asking about.
    setTab('history')
    push({
      tone: execution.status === 'passed' ? 'ok' : 'danger',
      title:
        execution.status === 'passed' ? 'Execution passed' : 'Execution finished with failures',
      description: `${execution.ref} — ${execution.results.filter((r) => r.status === 'passed').length} of ${execution.results.length} cases passed.`,
    })
  }

  /**
   * Re-test a defect: run its case again and let the result decide the outcome.
   *
   * The defect is not closed by this function — `recordRetest` closes it only
   * if the case actually passed. Deciding here would let a re-test that failed
   * still mark the defect fixed, which is precisely the hole this step exists
   * to close.
   */
  async function retest(defect: Defect) {
    if (!env || !defect.caseId) return
    const target = cases.find((c) => c.id === defect.caseId)
    if (!target) {
      push({
        tone: 'warn',
        title: 'Cannot re-test',
        description: `${defect.caseRef ?? 'That case'} is no longer in this plan.`,
      })
      return
    }

    setTab('setup')
    setRunning(true)
    setLiveResults([])
    setLiveTotal(1)

    const execution = await api.runTestExecution(
      {
        caseIds: [target.id],
        environmentId: env.id,
        suiteName: `Re-test of ${defect.ref}`,
        retestDefectIds: [defect.id],
      },
      ({ result }) => setLiveResults((r) => [...r, result]),
    )

    const [updated] = await recordRetest(execution, [defect.id])

    setRunning(false)
    setRuns((list) => [execution, ...list])
    setLiveResults([])
    setTab('defects')

    const passed = execution.results.every((r) => r.status === 'passed')
    push({
      tone: passed ? 'ok' : 'danger',
      title: passed ? `${defect.ref} closed by re-test` : `${defect.ref} still failing`,
      description: passed
        ? `${defect.caseRef} passed in ${execution.ref}. The defect is now verified, not just claimed fixed.`
        : `${defect.caseRef} did not pass in ${execution.ref}. ${updated?.ref ?? defect.ref} has been reopened.`,
    })
  }

  if (loading && runs.length === 0) {
    return (
      <>
        <PageHeader
          title="Test execution"
          icon={<FlaskConical aria-hidden="true" />}
          tone="accent"
        />
        <PageBody className="space-y-4">
          <Skeleton className="h-[76px] w-full rounded-xl" />
          <Skeleton className="h-[520px] w-full rounded-xl" />
        </PageBody>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Test execution"
        icon={<FlaskConical aria-hidden="true" />}
        tone="accent"
        subject={subject?.title}
        // The stepper is wayfinding for a four-screen sequence, so it stays
        // pinned with the title rather than scrolling away with the content.
        below={<StlcRail phases={phases} subject={subject} />}
        actions={
          <>
            <Link to="/test-cases">
              <Button variant="secondary">Back to cases</Button>
            </Link>
            <Link to="/test-closure">
              <Button
                variant="primary"
                icon={<ChevronRight className="size-4" aria-hidden="true" />}
                disabled={runs.length === 0}
              >
                Go to closure
              </Button>
            </Link>
          </>
        }
      />

      <PageBody className="space-y-4">
        {running ? (
          <LiveRunCard results={liveResults} total={liveTotal} envName={env?.name ?? ''} />
        ) : null}

        {/*
         * Setting up a run and reviewing past runs are two different jobs, and
         * stacking history under the picker pushed the launch decision further
         * from the fold. Tabs keep each job's content whole.
         */}
        <div className="flex items-center justify-between gap-3">
          <Segmented
            label="Execution view"
            value={tab}
            onChange={(v) => setTab(v)}
            options={[
              { id: 'setup' as const, label: 'New run' },
              { id: 'history' as const, label: `History ${runs.length}` },
              { id: 'defects' as const, label: `Defects ${unsettledDefects.length}` },
            ]}
          />
          {tab === 'setup' && runnable.length > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedCases(new Set(runnable.map((c) => c.id)))}
              disabled={selectedCases.size === runnable.length}
            >
              Select all {runnable.length}
            </Button>
          ) : null}
        </div>

        {tab === 'defects' ? (
          <DefectsPanel
            defects={defects}
            environmentReady={env !== null && env.status !== 'offline'}
            running={running}
            onRetest={retest}
            onSetStatus={setStatus}
          />
        ) : tab === 'history' ? (
          <RunHistory runs={runs} onOpen={setOpenRun} />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
            <div className="min-w-0 space-y-4">
              {/* 1 — what to run */}
              <Card>
                <CardHeader
                  title="Select what to run"
                  description="Run a single case, or combine several into a suite."
                  icon={<Layers aria-hidden="true" />}
                  actions={
                    selectedCases.size > 0 ? (
                      <Badge tone="accent">{selectedCases.size} selected</Badge>
                    ) : null
                  }
                />

                {suites.length > 0 ? (
                  <div className="border-b border-[var(--border-subtle)] p-3">
                    <SectionLabel>Saved suites</SectionLabel>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      {suites.map((s) => {
                        const available = s.caseIds.filter((id) =>
                          runnable.some((c) => c.id === id),
                        ).length
                        return (
                          <button
                            key={s.id}
                            onClick={() => applySuite(s)}
                            className="cursor-pointer rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3 text-left transition-colors duration-200 hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <p className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
                                {s.name}
                              </p>
                              <Badge tone={available < s.caseIds.length ? 'warn' : 'neutral'}>
                                {available}/{s.caseIds.length}
                              </Badge>
                            </div>
                            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                              {s.description}
                            </p>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ) : null}

                {runnable.length === 0 ? (
                  <EmptyState
                    icon={<AlertTriangle className="size-5" aria-hidden="true" />}
                    title="No approved cases to run"
                    description="Only approved test cases can be executed. Review and approve cases first — running unreviewed cases would produce evidence nobody has agreed is meaningful."
                    action={
                      <Link to="/test-cases">
                        <Button variant="primary">Go to test cases</Button>
                      </Link>
                    }
                  />
                ) : (
                  /*
                   * Grouped by test level, because the STLC distinguishes them:
                   * system, integration, UAT and regression answer different
                   * questions and are typically run as a block. A flat list hid
                   * that entirely — every case looked like every other case.
                   */
                  <div>
                    {levelGroups.map((group) => {
                      const ids = group.cases.map((c) => c.id)
                      const selectedInGroup = ids.filter((id) => selectedCases.has(id)).length
                      const allSelected = selectedInGroup === ids.length
                      return (
                        <section key={group.level}>
                          <div className="flex items-center justify-between gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-4 py-2">
                            <div className="flex min-w-0 items-center gap-2">
                              <h4 className="text-[13px] font-semibold text-[var(--text-primary)]">
                                {TEST_LEVEL_LABEL[group.level]} testing
                              </h4>
                              <span className="numeral text-[11px] text-[var(--text-tertiary)]">
                                {selectedInGroup > 0
                                  ? `${selectedInGroup}/${ids.length} selected`
                                  : `${ids.length} case${ids.length === 1 ? '' : 's'}`}
                              </span>
                            </div>
                            <button
                              onClick={() => toggleLevel(ids, !allSelected)}
                              className="shrink-0 cursor-pointer text-xs text-[var(--text-tertiary)] underline underline-offset-2 hover:text-[var(--text-primary)]"
                            >
                              {allSelected ? 'Deselect' : 'Select'} all
                            </button>
                          </div>
                          <ul className="divide-y divide-[var(--border-subtle)]">
                            {group.cases.map((c) => (
                              <CaseRow
                                key={c.id}
                                testCase={c}
                                checked={selectedCases.has(c.id)}
                                onToggle={() => toggleCase(c.id)}
                              />
                            ))}
                          </ul>
                        </section>
                      )
                    })}
                  </div>
                )}
              </Card>

              {estimate.manual > 0 ? (
                <p className="rounded-xl border border-[var(--asserted-border)] bg-[var(--asserted-subtle)] p-3 text-xs leading-relaxed text-[var(--text-secondary)]">
                  {estimate.manual} selected case
                  {estimate.manual === 1 ? '' : 's'} cannot be automated, so{' '}
                  {estimate.manual === 1 ? 'it' : 'they'} will produce asserted evidence, which
                  cannot satisfy a sign-off gate on its own.
                </p>
              ) : null}
            </div>

            {/* 2 — where to run */}
            <aside className="space-y-4">
              <Card>
                <CardHeader title="Target environment" icon={<Server aria-hidden="true" />} />
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {environments.map((e) => (
                    <EnvironmentOption
                      key={e.id}
                      environment={e}
                      selected={e.id === envId}
                      onSelect={() => setEnvId(e.id)}
                    />
                  ))}
                </ul>
              </Card>

              {env ? <ReadinessCard environment={env} /> : null}
            </aside>
          </div>
        )}

        {tab === 'setup' ? (
          <LaunchBar
            selectedCount={selectedList.length}
            totalRunnable={runnable.length}
            selectedLevels={selectedLevels}
            estimate={estimate}
            environment={env}
            blockers={blockers}
            canRun={canRun}
            running={running}
            onClear={() => setSelectedCases(new Set())}
            onLaunch={() => setConfirmOpen(true)}
          />
        ) : null}
      </PageBody>

      {/* Preflight confirmation — the environment gate */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={blockers > 0 ? 'Environment is not fully ready' : 'Start this execution?'}
        description={
          blockers > 0
            ? 'Some readiness checks did not pass. Running anyway is allowed, but the result will carry these conditions on it.'
            : 'Every readiness check passed for the selected environment.'
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant={blockers > 0 ? 'danger' : 'primary'}
              icon={<Play className="size-4" aria-hidden="true" />}
              onClick={launch}
            >
              {blockers > 0 ? 'Run anyway' : 'Start execution'}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {env ? (
            <>
              <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
                <SectionLabel>Environment</SectionLabel>
                <p className="mt-1 text-[13px] font-medium text-[var(--text-primary)]">
                  {env.name}
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-[var(--text-tertiary)]">
                  {env.fingerprint.tenant} · {env.fingerprint.release} ·{' '}
                  {env.fingerprint.dataCoverage}% data coverage
                </p>
              </div>

              <ul className="space-y-2">
                {env.readiness.map((r) => (
                  <li key={r.id} className="flex items-start gap-2.5">
                    <span className="mt-px">
                      <CriterionIcon met={r.met} />
                    </span>
                    <div className="min-w-0">
                      <p className="text-[13px] leading-snug text-[var(--text-primary)]">
                        {r.text}
                      </p>
                      {r.detail ? (
                        <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
                          {r.detail}
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>

              {unevaluated > 0 ? (
                <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
                  {unevaluated} check has not been evaluated yet — an unevaluated check is not the
                  same as a passing one.
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      </Modal>

      <RunDrawer
        run={openRun}
        defects={defects}
        onClose={() => setOpenRun(null)}
        onRaiseDefect={(result) => {
          if (openRun) setRaiseFrom({ run: openRun, result })
        }}
      />

      <RaiseDefectModal
        state={raiseFrom}
        onClose={() => setRaiseFrom(null)}
        onRaise={async ({ title, severity, owner }) => {
          if (!raiseFrom) return
          const { run, result } = raiseFrom
          const created = await raise({
            requirementId: DEFAULT_REQUIREMENT_ID,
            executionId: run.id,
            caseId: result.caseId,
            caseRef: result.caseRef,
            title,
            expected: result.expected,
            actual: result.actual,
            severity,
            owner,
            affectedNodeIds: result.coversNodeIds,
          })
          setRaiseFrom(null)
          setOpenRun(null)
          setTab('defects')
          push({
            tone: 'ok',
            title: `${created.ref} raised`,
            description: `Owned by ${owner}. Re-test it here once a fix is claimed.`,
          })
        }}
      />
    </>
  )
}

/* -------------------------------------------------------------- sub-views */

/**
 * The launch bar: what you selected, where it will run, what is in the way,
 * and the button — pinned to the viewport.
 *
 * This replaced a "Launch" card in the right rail. On a 900px viewport that
 * card's button sat at y≈1238: the entire point of the screen was more than a
 * screenful below the fold, and the readiness failures that ought to inform
 * the click were in a different column again. Keeping the decision and its
 * consequences in one place is the whole job of this component.
 *
 * It states blockers rather than disabling the button. Running against a
 * degraded environment is a legitimate choice a human may need to make; what
 * is not legitimate is making it without being told.
 */
function LaunchBar({
  selectedCount,
  totalRunnable,
  selectedLevels,
  estimate,
  environment,
  blockers,
  canRun,
  running,
  onClear,
  onLaunch,
}: {
  selectedCount: number
  totalRunnable: number
  /** Level labels covered by the selection, e.g. ["System", "UAT"] */
  selectedLevels: string[]
  estimate: { seconds: number; costUsd: number; manual: number }
  environment: TestEnvironment | null
  blockers: number
  canRun: boolean
  running: boolean
  onClear: () => void
  onLaunch: () => void
}) {
  const nothingSelected = selectedCount === 0
  const offline = environment?.status === 'offline'

  return (
    /*
     * Opaque, not translucent. A blurred/alpha bar let case rows bleed through
     * it — at a glance the numbers in the bar and the rows behind them ran
     * together, which is the opposite of what a summary is for.
     */
    <div className="sticky bottom-0 z-20 -mx-4 mt-4 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 shadow-[0_-6px_16px_-8px_rgb(0_0_0/0.18)] sm:-mx-6 sm:px-6">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        {/* What is selected */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="numeral text-[15px] font-semibold text-[var(--text-primary)]">
              {selectedCount}
            </span>
            <span className="text-[13px] text-[var(--text-secondary)]">
              of {totalRunnable} case{totalRunnable === 1 ? '' : 's'} selected
            </span>
            {selectedCount > 0 ? (
              <button
                onClick={onClear}
                className="cursor-pointer text-xs text-[var(--text-tertiary)] underline underline-offset-2 hover:text-[var(--text-primary)]"
              >
                Clear
              </button>
            ) : null}
          </div>

          {/* Consequences of the current selection, stated inline */}
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--text-tertiary)]">
            {nothingSelected ? (
              <span>Select at least one case to run.</span>
            ) : (
              <>
                {/* Which levels this run covers — the STLC-meaningful summary
                    of a selection, not just how many rows are ticked. */}
                {selectedLevels.length > 0 ? (
                  <>
                    <span className="font-medium text-[var(--text-secondary)]">
                      {selectedLevels.join(' · ')}
                    </span>
                    <span aria-hidden="true">·</span>
                  </>
                ) : null}
                <span className="tabular">≈ {formatDuration(estimate.seconds)}</span>
                <span aria-hidden="true">·</span>
                <span className="tabular">≈ {formatUsd(estimate.costUsd)}</span>
                {environment ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="truncate">in {environment.name}</span>
                  </>
                ) : null}
                {estimate.manual > 0 ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="text-[var(--asserted-text,var(--warn))]">
                      {estimate.manual} asserted-only
                    </span>
                  </>
                ) : null}
              </>
            )}
          </p>
        </div>

        {/*
         * Blockers travel with the button. Previously they lived in a card in
         * another column, so a run could be launched without ever seeing them.
         */}
        {offline ? (
          <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--danger)]">
            <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
            {environment?.name} is offline
          </p>
        ) : blockers > 0 ? (
          <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--warn)]">
            <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
            {blockers} readiness check{blockers === 1 ? '' : 's'} failing
          </p>
        ) : environment ? (
          <p className="flex items-center gap-1.5 text-xs text-[var(--ok)]">
            <ShieldCheck className="size-3.5 shrink-0" aria-hidden="true" />
            Environment ready
          </p>
        ) : null}

        <Button
          variant={blockers > 0 && !nothingSelected ? 'danger' : 'primary'}
          disabled={!canRun}
          loading={running}
          icon={running ? undefined : <Play className="size-4" aria-hidden="true" />}
          onClick={onLaunch}
        >
          {/*
           * Built as a whole string per branch. Interpolating an empty count
           * mid-template produced the literal label "Run  cases".
           */}
          {running
            ? 'Running…'
            : nothingSelected
              ? 'Run selected cases'
              : `Run ${selectedCount} case${selectedCount === 1 ? '' : 's'}`}
        </Button>
      </div>
    </div>
  )
}

/**
 * Defects raised from results, and the re-test that settles them.
 *
 * This is the step between execution and closure: a failed case produces a
 * defect, a fix is claimed against it, and a passing re-test is what turns
 * that claim into evidence. A defect marked "fixed" with no re-test is called
 * out explicitly, because it is the one state that looks finished and is not.
 */
function DefectsPanel({
  defects,
  environmentReady,
  running,
  onRetest,
  onSetStatus,
}: {
  defects: Defect[]
  environmentReady: boolean
  running: boolean
  onRetest: (d: Defect) => void
  onSetStatus: (id: string, status: DefectStatus, note?: string) => void
}) {
  const unsettled = defects.filter((d) => !isSettled(d))
  const settled = defects.filter(isSettled)
  const awaitingRetest = defects.filter(isUnverifiedFix)

  if (defects.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Bug className="size-5" aria-hidden="true" />}
          title="No defects raised"
          description="Raise a defect from a failed or deviating result in the execution history. Nothing here means nothing found — not that nothing was looked for."
        />
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      {awaitingRetest.length > 0 ? (
        <Card className="border-[var(--warn-border)] p-4">
          <div className="flex items-start gap-3">
            <RotateCcw className="mt-px size-4 shrink-0 text-[var(--warn)]" aria-hidden="true" />
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-[var(--warn)]">
                {awaitingRetest.length} defect{awaitingRetest.length === 1 ? '' : 's'} claimed fixed
                but never re-tested
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                A fix is a claim until a re-test proves it. Closure cannot be signed against an
                unverified fix.
              </p>
            </div>
          </div>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Open defects"
          description="Raised from execution results. Each must be settled or explicitly accepted before closure."
          icon={<Bug aria-hidden="true" />}
          actions={
            <Badge tone={unsettled.length > 0 ? 'warn' : 'ok'}>{unsettled.length} open</Badge>
          }
        />
        {unsettled.length === 0 ? (
          <EmptyState
            icon={<CheckCircle2 className="size-5" aria-hidden="true" />}
            title="Every defect is settled"
            description="Nothing is outstanding against this cycle."
          />
        ) : (
          <ul className="divide-y divide-[var(--border-subtle)]">
            {unsettled.map((d) => (
              <DefectRow
                key={d.id}
                defect={d}
                environmentReady={environmentReady}
                running={running}
                onRetest={() => onRetest(d)}
                onSetStatus={onSetStatus}
              />
            ))}
          </ul>
        )}
      </Card>

      {settled.length > 0 ? (
        <Card>
          <CardHeader
            title="Settled"
            description="Closed by a passing re-test, or explicitly accepted."
            icon={<CheckCircle2 aria-hidden="true" />}
            actions={<Badge tone="ok">{settled.length}</Badge>}
          />
          <ul className="divide-y divide-[var(--border-subtle)]">
            {settled.map((d) => (
              <DefectRow
                key={d.id}
                defect={d}
                environmentReady={environmentReady}
                running={running}
                onRetest={() => onRetest(d)}
                onSetStatus={onSetStatus}
              />
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  )
}

function DefectRow({
  defect: d,
  environmentReady,
  running,
  onRetest,
  onSetStatus,
}: {
  defect: Defect
  environmentReady: boolean
  running: boolean
  onRetest: () => void
  onSetStatus: (id: string, status: DefectStatus, note?: string) => void
}) {
  const [open, setOpen] = useState(false)
  const needsRetest = isUnverifiedFix(d)
  const settled = isSettled(d)

  return (
    <li className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="numeral shrink-0 text-[11px] font-semibold whitespace-nowrap text-[var(--text-tertiary)]">
              {d.ref}
            </span>
            <DefectSeverityBadge severity={d.severity} />
            <DefectStatusBadge status={d.status} />
            {d.caseRef ? (
              <span className="font-mono text-[11px] text-[var(--text-tertiary)]">{d.caseRef}</span>
            ) : null}
          </div>
          <p className="mt-1 text-[13px] leading-snug font-medium text-[var(--text-primary)]">
            {d.title}
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">
            {d.owner} · raised by {d.raisedBy} · {relativeTime(d.raisedAt)}
            {d.retestExecutionIds.length > 0
              ? ` · ${d.retestExecutionIds.length} re-test${d.retestExecutionIds.length === 1 ? '' : 's'}`
              : ''}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>
            {open ? 'Hide' : 'Details'}
          </Button>
          {!settled ? (
            <>
              {d.status !== 'fixed' ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onSetStatus(d.id, 'fixed', 'Marked fixed — awaiting re-test.')}
                >
                  Mark fixed
                </Button>
              ) : null}
              <Tooltip
                label={
                  !environmentReady
                    ? 'Select a usable environment before re-testing'
                    : !d.caseId
                      ? 'This defect is not linked to a runnable case'
                      : 'Run this case again to prove the fix'
                }
              >
                <span>
                  <Button
                    variant={needsRetest ? 'primary' : 'secondary'}
                    size="sm"
                    icon={<RotateCcw className="size-3.5" aria-hidden="true" />}
                    disabled={!environmentReady || !d.caseId || running}
                    onClick={onRetest}
                  >
                    Re-test
                  </Button>
                </span>
              </Tooltip>
            </>
          ) : null}
        </div>
      </div>

      {needsRetest ? (
        <p className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--warn)]">
          <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span>
            Marked fixed, but no re-test has proven it. Until one passes, this counts as unverified.
          </span>
        </p>
      ) : null}

      {open ? (
        <div className="mt-3 space-y-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <SectionLabel>Expected</SectionLabel>
              <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                {d.expected}
              </p>
            </div>
            <div>
              <SectionLabel>Actual</SectionLabel>
              <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                {d.actual}
              </p>
            </div>
          </div>
          <div>
            <SectionLabel>History</SectionLabel>
            <ul className="mt-1.5 space-y-1.5">
              {d.notes.map((n, i) => (
                <li key={i} className="text-xs leading-relaxed text-[var(--text-secondary)]">
                  <span className="font-medium text-[var(--text-primary)]">{n.by}</span>
                  <span className="text-[var(--text-tertiary)]"> · {relativeTime(n.at)}</span>
                  <span className="block">{n.text}</span>
                </li>
              ))}
            </ul>
          </div>
          {!isSettled(d) ? (
            <div className="flex flex-wrap gap-2 border-t border-[var(--border-subtle)] pt-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onSetStatus(d.id, 'in_progress', 'Picked up.')}
              >
                Mark in progress
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  onSetStatus(d.id, 'wont_fix', 'Accepted as a known limitation for this cycle.')
                }
              >
                Won't fix
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

/**
 * Raise a defect from a result.
 *
 * Prefilled from the result rather than asking the user to retype it: the
 * expected/actual pair is already recorded, and re-entering it by hand is how
 * a defect ends up describing something subtly different from what failed.
 */
function RaiseDefectModal({
  state,
  onClose,
  onRaise,
}: {
  state: { run: TestExecution; result: CaseResult } | null
  onClose: () => void
  onRaise: (input: {
    title: string
    severity: DefectSeverity
    owner: string
  }) => void | Promise<void>
}) {
  const [title, setTitle] = useState('')
  const [severity, setSeverity] = useState<DefectSeverity>('major')
  const [owner, setOwner] = useState('Integration Engineering')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (state) {
      setTitle(state.result.deviation ?? state.result.caseTitle)
      setSeverity(state.result.status === 'failed' ? 'major' : 'minor')
      setTouched(false)
    }
  }, [state])

  if (!state) return null
  const { result } = state
  const error =
    touched && title.trim().length < 10 ? 'Describe the defect in at least 10 characters.' : null

  return (
    <Modal
      open
      onClose={onClose}
      title="Raise a defect"
      description={`From ${result.caseRef} — ${result.caseTitle}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon={<Bug className="size-4" aria-hidden="true" />}
            onClick={() => {
              setTouched(true)
              if (title.trim().length < 10) return
              onRaise({ title: title.trim(), severity, owner })
            }}
          >
            Raise defect
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3 sm:grid-cols-2">
          <div>
            <SectionLabel>Expected</SectionLabel>
            <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
              {result.expected}
            </p>
          </div>
          <div>
            <SectionLabel>Actual</SectionLabel>
            <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
              {result.actual}
            </p>
          </div>
        </div>

        <div>
          <label
            htmlFor="defect-title"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            What is wrong{' '}
            <span className="text-[var(--danger)]" aria-hidden="true">
              *
            </span>
          </label>
          <textarea
            id="defect-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => setTouched(true)}
            rows={3}
            aria-invalid={Boolean(error)}
            className="w-full resize-y rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 py-2 text-sm outline-none transition-colors duration-200 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
          />
          {error ? (
            <p role="alert" className="mt-1.5 text-xs text-[var(--danger)]">
              {error}
            </p>
          ) : (
            <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
              Prefilled from the deviation this run recorded. Edit if it needs saying differently.
            </p>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label
              htmlFor="defect-severity"
              className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
            >
              Severity
            </label>
            <select
              id="defect-severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as DefectSeverity)}
              className="w-full cursor-pointer rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
            >
              <option value="breaking">Breaking</option>
              <option value="major">Major</option>
              <option value="minor">Minor</option>
              <option value="none">Trivial</option>
            </select>
          </div>
          <div>
            <label
              htmlFor="defect-owner"
              className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
            >
              Owner
            </label>
            <input
              id="defect-owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              className="w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
            />
          </div>
        </div>
      </div>
    </Modal>
  )
}

/**
 * Past executions.
 *
 * Split out of the setup column: reviewing what already ran is a different job
 * from choosing what to run next, and stacking it below the picker pushed the
 * launch decision further off-screen.
 */
function RunHistory({
  runs,
  onOpen,
}: {
  runs: TestExecution[]
  onOpen: (r: TestExecution) => void
}) {
  return (
    <Card>
      <CardHeader
        title="Execution history"
        description="Every run, including the ones that were blocked before they started."
        icon={<Clock aria-hidden="true" />}
        actions={<Badge tone="neutral">{runs.length} total</Badge>}
      />
      {runs.length === 0 ? (
        <EmptyState
          icon={<Play className="size-5" aria-hidden="true" />}
          title="Nothing has been executed yet"
          description="Select cases and an environment on the New run tab, then launch."
        />
      ) : (
        <ul className="divide-y divide-[var(--border-subtle)]">
          {runs.map((r) => {
            const passed = r.results.filter((x) => x.status === 'passed').length
            return (
              <li key={r.id}>
                <button
                  onClick={() => onOpen(r)}
                  className="flex w-full cursor-pointer items-center gap-3 p-4 text-left transition-colors duration-200 hover:bg-[var(--bg-hover)]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                        {r.ref}
                      </span>
                      <ExecutionStatusBadge status={r.status} />
                      <span className="text-[13px] font-medium text-[var(--text-primary)]">
                        {r.suiteName}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                      {r.environment.environment} · {r.triggeredBy} · {relativeTime(r.startedAt)}
                      {r.results.length > 0 ? ` · ${passed}/${r.results.length} passed` : ''}
                    </p>
                    {r.blockedReason ? (
                      <p className="mt-1 text-xs leading-relaxed text-[var(--warn)]">
                        {r.blockedReason}
                      </p>
                    ) : null}
                  </div>
                  <span className="tabular shrink-0 text-xs text-[var(--text-tertiary)]">
                    {formatUsd(r.costUsd)}
                  </span>
                  <ChevronRight
                    className="size-4 shrink-0 text-[var(--text-tertiary)]"
                    aria-hidden="true"
                  />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function CaseRow({
  testCase: c,
  checked,
  onToggle,
}: {
  testCase: TestCase
  checked: boolean
  onToggle: () => void
}) {
  return (
    <li>
      <label
        className={cn(
          'flex cursor-pointer items-start gap-3 p-3.5 transition-colors duration-200',
          checked ? 'bg-[var(--accent-subtle)]' : 'hover:bg-[var(--bg-hover)]',
        )}
      >
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-0.5 size-4 shrink-0 cursor-pointer accent-[var(--accent)]"
          aria-label={`Select ${c.ref} — ${c.title}`}
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] text-[var(--text-tertiary)]">{c.ref}</span>
            <PriorityBadge priority={c.priority} />
            <span className="text-[11px] text-[var(--text-tertiary)]">
              {TEST_LEVEL_LABEL[c.level]}
            </span>
            {!c.automatable ? <Badge tone="asserted">Asserted only</Badge> : null}
          </span>
          <span className="mt-1 block text-[13px] leading-snug font-medium text-[var(--text-primary)]">
            {c.title}
          </span>
        </span>
        <span className="tabular shrink-0 text-xs text-[var(--text-tertiary)]">
          {c.estimatedDurationSeconds}s
        </span>
      </label>
    </li>
  )
}

function EnvironmentOption({
  environment: e,
  selected,
  onSelect,
}: {
  environment: TestEnvironment
  selected: boolean
  onSelect: () => void
}) {
  const disabled = e.status === 'offline'
  return (
    <li>
      <label
        className={cn(
          'flex items-start gap-2.5 p-3.5 transition-colors duration-200',
          disabled ? 'cursor-not-allowed opacity-55' : 'cursor-pointer',
          selected && !disabled
            ? 'bg-[var(--accent-subtle)]'
            : !disabled && 'hover:bg-[var(--bg-hover)]',
        )}
      >
        <input
          type="radio"
          name="environment"
          checked={selected}
          onChange={onSelect}
          disabled={disabled}
          className="mt-0.5 size-4 shrink-0 accent-[var(--accent)] disabled:cursor-not-allowed"
          aria-label={`Run in ${e.name}`}
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] font-medium text-[var(--text-primary)]">{e.name}</span>
            <EnvironmentStatusBadge status={e.status} />
          </span>
          <span className="mt-1 block font-mono text-[11px] text-[var(--text-tertiary)]">
            {e.fingerprint.release}
          </span>
          <span className="mt-1.5 flex items-center gap-2">
            <Meter
              value={e.fingerprint.dataCoverage}
              tone={
                e.fingerprint.dataCoverage >= 80
                  ? 'ok'
                  : e.fingerprint.dataCoverage >= 50
                    ? 'warn'
                    : 'danger'
              }
              label={`${e.name} data coverage`}
            />
            <span className="tabular shrink-0 text-[11px] text-[var(--text-tertiary)]">
              {e.fingerprint.dataCoverage}%
            </span>
          </span>
          <span className="mt-1 block text-[11px] text-[var(--text-tertiary)]">
            {formatUsd(e.hourlyCostUsd)}/hr · refreshed {relativeTime(e.lastRefreshedAt)}
          </span>
        </span>
      </label>
    </li>
  )
}

function ReadinessCard({ environment: e }: { environment: TestEnvironment }) {
  const unmet = criteriaUnmet(e.readiness)
  return (
    <Card>
      <CardHeader
        title="Readiness"
        description="Checked before every run."
        icon={<ShieldCheck aria-hidden="true" />}
        actions={
          unmet > 0 ? <Badge tone="warn">{unmet} failing</Badge> : <Badge tone="ok">Ready</Badge>
        }
      />
      <ul className="divide-y divide-[var(--border-subtle)]">
        {e.readiness.map((r) => (
          <li key={r.id} className="flex items-start gap-2.5 p-3">
            <span className="mt-px">
              <CriterionIcon met={r.met} />
            </span>
            <div className="min-w-0">
              <p className="text-xs leading-snug text-[var(--text-primary)]">{r.text}</p>
              {r.detail ? (
                <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                  {r.detail}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      {e.notes ? (
        <p className="border-t border-[var(--border-subtle)] p-3 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
          {e.notes}
        </p>
      ) : null}
    </Card>
  )
}

/**
 * Live run feedback. Showing results as they land — rather than a spinner then
 * a finished table — is what makes a long execution legible while it happens.
 */
function LiveRunCard({
  results,
  total,
  envName,
}: {
  results: CaseResult[]
  total: number
  envName: string
}) {
  const done = results.length
  const passed = results.filter((r) => r.status === 'passed').length
  const failed = results.filter((r) => r.status === 'failed').length

  return (
    <Card className="border-[var(--info-border)]">
      <CardHeader
        title="Execution in progress"
        description={`Running ${total} case${total === 1 ? '' : 's'} against ${envName}`}
        icon={<Loader2 className="animate-spin" aria-hidden="true" />}
        actions={
          <Button
            variant="secondary"
            size="sm"
            icon={<CircleStop className="size-3.5" aria-hidden="true" />}
          >
            Abort
          </Button>
        }
      />
      <div className="space-y-3 p-4">
        <div className="flex items-center gap-3">
          <Meter value={(done / Math.max(1, total)) * 100} tone="info" label="Execution progress" />
          <span className="tabular shrink-0 text-xs text-[var(--text-secondary)]">
            {done}/{total}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="ok">{passed} passed</Badge>
          {failed > 0 ? <Badge tone="danger">{failed} failed</Badge> : null}
        </div>
        {results.length > 0 ? (
          <ul className="space-y-1.5">
            {results.map((r) => (
              <li key={r.id} className="flex items-center gap-2 text-xs">
                <RunStatusBadge status={r.status} />
                <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                  {r.caseRef}
                </span>
                <span className="min-w-0 flex-1 truncate text-[var(--text-secondary)]">
                  {r.caseTitle}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------- run drawer */

function RunDrawer({
  run,
  defects,
  onClose,
  onRaiseDefect,
}: {
  run: TestExecution | null
  defects: Defect[]
  onClose: () => void
  onRaiseDefect: (result: CaseResult) => void
}) {
  if (!run) return null
  const passed = run.results.filter((r) => r.status === 'passed').length
  const deviations = run.results.filter((r) => r.deviation)

  return (
    <Drawer
      open={Boolean(run)}
      onClose={onClose}
      width="lg"
      title={`${run.ref} — ${run.suiteName}`}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <ExecutionStatusBadge status={run.status} />
          <Badge tone="neutral">{run.environment.environment}</Badge>
          <span>
            {run.triggeredBy} · {formatDateTime(run.startedAt)}
          </span>
        </div>
      }
      footer={
        <Link to="/test-closure">
          <Button variant="primary" icon={<ArrowRight className="size-4" aria-hidden="true" />}>
            Analyse in closure
          </Button>
        </Link>
      }
    >
      <div className="space-y-5 p-5">
        {run.blockedReason ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
            <AlertTriangle
              className="mt-px size-4 shrink-0 text-[var(--warn)]"
              aria-hidden="true"
            />
            <div>
              <p className="text-xs font-semibold text-[var(--warn)]">Execution blocked</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                {run.blockedReason}
              </p>
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-3 gap-3">
          <StatTile label="Passed" value={passed} tone="ok" />
          <StatTile
            label="Failed"
            value={run.results.filter((r) => r.status === 'failed').length}
            tone="danger"
          />
          <StatTile label="Cost" value={formatUsd(run.costUsd)} />
        </div>

        <div>
          <SectionLabel>Preflight at launch</SectionLabel>
          <ul className="mt-2 space-y-2">
            {run.preflight.map((p) => (
              <li key={p.id} className="flex items-start gap-2.5">
                <span className="mt-px">
                  <CriterionIcon met={p.met} />
                </span>
                <div className="min-w-0">
                  <p className="text-[13px] leading-snug text-[var(--text-primary)]">{p.text}</p>
                  {p.detail ? (
                    <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
                      {p.detail}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>

        {deviations.length > 0 ? (
          <div>
            <SectionLabel>Deviations ({deviations.length})</SectionLabel>
            <ul className="mt-2 space-y-2">
              {deviations.map((r) => (
                <li
                  key={r.id}
                  className="rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3"
                >
                  <p className="font-mono text-[11px] text-[var(--text-tertiary)]">{r.caseRef}</p>
                  <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                    {r.deviation}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {run.results.length > 0 ? (
          <div>
            <SectionLabel>Case results</SectionLabel>
            <ul className="mt-2 space-y-2">
              {run.results.map((r) => {
                /*
                 * A result earns a defect when it failed or deviated. Offering
                 * the action on a clean pass would invite noise; withholding it
                 * on a deviation would let a known divergence go unrecorded.
                 */
                const raisable = r.status === 'failed' || Boolean(r.deviation)
                const existing = defects.find((d) => d.caseId === r.caseId)
                return (
                  <li
                    key={r.id}
                    className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <RunStatusBadge status={r.status} />
                      <EvidenceGradeBadge grade={r.grade} />
                      <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                        {r.caseRef}
                      </span>
                    </div>
                    <p className="mt-1.5 text-[13px] leading-snug font-medium text-[var(--text-primary)]">
                      {r.caseTitle}
                    </p>
                    {r.deviation ? (
                      <p className="mt-1 text-[11px] leading-relaxed text-[var(--warn)]">
                        {r.deviation}
                      </p>
                    ) : null}
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-[11px] text-[var(--text-tertiary)]">
                        {formatDuration(r.durationSeconds)} · {r.attempts} attempt
                        {r.attempts === 1 ? '' : 's'}
                      </p>
                      {raisable ? (
                        existing ? (
                          <span className="flex items-center gap-1.5 text-[11px] text-[var(--text-tertiary)]">
                            <Bug className="size-3" aria-hidden="true" />
                            {existing.ref} raised
                          </span>
                        ) : (
                          <Button
                            variant="secondary"
                            size="sm"
                            icon={<Bug className="size-3.5" aria-hidden="true" />}
                            onClick={() => onRaiseDefect(r)}
                          >
                            Raise defect
                          </Button>
                        )
                      ) : null}
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : null}
      </div>
    </Drawer>
  )
}

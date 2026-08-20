import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Bug,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileWarning,
  FlaskConical,
  Lightbulb,
  ListChecks,
  LogOut,
  ShieldCheck,
  Wallet,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  SectionLabel,
  Segmented,
  Skeleton,
  StatTile,
} from '@/components/ui/primitives'
import { Modal, useToast } from '@/components/ui/overlays'
import {
  CriterionIcon,
  DefectSeverityBadge,
  DefectStatusBadge,
  EvidenceGradeBadge,
  RunStatusBadge,
} from '@/components/domain/status'
import { StlcRail } from '@/components/domain/StlcRail'
import {
  DocCriteria,
  DocFacts,
  DocList,
  DocSection,
  DocumentPreview,
} from '@/components/domain/DocumentPreview'
import { allMet, criteriaUnmet, useStlc } from '@/lib/useStlc'
import { blockingDefects, isUnverifiedFix, useDefects } from '@/lib/useDefects'
import { cn, formatDuration, formatUsd, relativeTime } from '@/lib/utils'
import type { CaseResult, Defect, TestClosure } from '@/lib/types'

type ResultFilter = 'all' | 'deviations' | 'failed' | 'asserted'

export function TestClosurePage() {
  const { closure: fetched, executions, phases, subject, loading } = useStlc()
  const [closure, setClosure] = useState<TestClosure | null>(null)
  const [filter, setFilter] = useState<ResultFilter>('all')
  const [closeOpen, setCloseOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [accepted, setAccepted] = useState<Set<number>>(new Set())
  const { defects } = useDefects()
  const { push } = useToast()

  const current = closure ?? fetched ?? null

  /** The live defect register, not the closure snapshot — a re-test must count. */
  const liveOpenDefects = useMemo(() => blockingDefects(defects), [defects])
  const unverifiedFixes = useMemo(() => defects.filter(isUnverifiedFix), [defects])

  /** Latest execution's results are what closure analyses. */
  const results = useMemo(() => {
    const withResults = executions.filter((e) => e.results.length > 0)
    return withResults.length > 0 ? withResults[0].results : []
  }, [executions])

  const filtered = useMemo(() => {
    if (filter === 'deviations') return results.filter((r) => r.deviation)
    if (filter === 'failed') return results.filter((r) => r.status === 'failed')
    if (filter === 'asserted') return results.filter((r) => r.grade === 'asserted')
    return results
  }, [results, filter])

  const counts = useMemo(
    () => ({
      all: results.length,
      deviations: results.filter((r) => r.deviation).length,
      failed: results.filter((r) => r.status === 'failed').length,
      asserted: results.filter((r) => r.grade === 'asserted').length,
    }),
    [results],
  )

  const exitUnmet = current ? criteriaUnmet(current.exitCriteria) : 0
  const exitReady = current ? allMet(current.exitCriteria) : false
  const isClosed = current?.state === 'closed' || current?.state === 'closed_with_deviations'

  /** Every residual risk needs an accountable owner before closure. */
  const risksNeedingAcceptance = current
    ? current.residualRisks.filter((r, i) => !r.acceptedBy && !accepted.has(i)).length
    : 0

  function close(withDeviations: boolean) {
    if (!current) return
    setCloseOpen(false)
    setClosure({
      ...current,
      state: withDeviations ? 'closed_with_deviations' : 'closed',
      closedBy: 'Sathish Kumar',
      closedAt: new Date().toISOString(),
    })
    push({
      tone: withDeviations ? 'warn' : 'ok',
      title: withDeviations ? 'Closed with deviations' : 'Test cycle closed',
      description: withDeviations
        ? 'Unmet criteria and open defects are carried into the approval package.'
        : 'All exit criteria met. The approval package can now be assembled.',
    })
  }

  if (loading && !current) {
    return (
      <>
        <PageHeader
          title="Test closure"
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

  if (!current) {
    return (
      <>
        <PageHeader title="Test closure" icon={<FlaskConical aria-hidden="true" />} tone="accent" />
        <PageBody>
          <Card>
            <EmptyState
              icon={<ClipboardCheck className="size-5" aria-hidden="true" />}
              title="Nothing to close yet"
              description="A cycle can only be closed once tests have run against a plan."
              action={
                <Link to="/test-runs">
                  <Button variant="primary">Go to test execution</Button>
                </Link>
              }
            />
          </Card>
        </PageBody>
      </>
    )
  }

  const s = current.summary

  return (
    <>
      <PageHeader
        title="Test closure"
        icon={<FlaskConical aria-hidden="true" />}
        tone="accent"
        subject={subject?.title}
        // The stepper is wayfinding for a four-screen sequence, so it stays
        // pinned with the title rather than scrolling away with the content.
        below={<StlcRail phases={phases} subject={subject} />}
        actions={
          <>
            <Button
              variant="secondary"
              icon={<Download className="size-4" aria-hidden="true" />}
              onClick={() => setExportOpen(true)}
            >
              Export report
            </Button>
            {isClosed ? (
              <Link to="/approvals">
                <Button
                  variant="primary"
                  icon={<ArrowRight className="size-4" aria-hidden="true" />}
                >
                  Go to approvals
                </Button>
              </Link>
            ) : (
              <Button
                variant="primary"
                icon={<LogOut className="size-4" aria-hidden="true" />}
                onClick={() => setCloseOpen(true)}
              >
                Close cycle
              </Button>
            )}
          </>
        }
      />

      <PageBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Cases executed"
            value={`${s.passed + s.failed}/${s.casesTotal}`}
            sublabel={s.notRun > 0 ? `${s.notRun} never ran` : 'All planned cases ran'}
            tone={s.notRun > 0 ? 'warn' : 'ok'}
            icon={<ListChecks aria-hidden="true" />}
          />
          <StatTile
            label="Passed"
            value={s.passed}
            tone={s.failed === 0 ? 'ok' : 'warn'}
            sublabel={s.failed > 0 ? `${s.failed} failed` : 'No failures'}
            icon={<CheckCircle2 aria-hidden="true" />}
          />
          <StatTile
            label="Verified evidence"
            value={`${s.verified}/${s.verified + s.asserted}`}
            tone={s.asserted > 0 ? 'asserted' : 'verified'}
            sublabel={
              s.asserted > 0
                ? `${s.asserted} asserted — cannot satisfy a gate`
                : 'All evidence is replayable'
            }
            icon={<ShieldCheck aria-hidden="true" />}
          />
          <StatTile
            label="Cycle cost"
            value={formatUsd(current.totalCostUsd)}
            sublabel={`${current.totalDurationHours}h across ${current.executionIds.length} executions`}
            icon={<Wallet aria-hidden="true" />}
          />
        </div>

        {/* Exit criteria decide whether closure is legitimate, so they lead. */}
        <Card className={exitUnmet > 0 ? 'border-[var(--warn-border)]' : undefined}>
          <CardHeader
            title="Exit criteria"
            description="Set by the test plan before testing began. Closure is evaluated against these."
            icon={<LogOut aria-hidden="true" />}
            actions={
              exitUnmet > 0 ? (
                <Badge tone="warn">{exitUnmet} unmet</Badge>
              ) : (
                <Badge tone="ok">All met</Badge>
              )
            }
          />
          <ul className="divide-y divide-[var(--border-subtle)]">
            {current.exitCriteria.map((c) => (
              <li key={c.id} className="flex items-start gap-2.5 p-4">
                <span className="mt-px">
                  <CriterionIcon met={c.met} />
                </span>
                <div className="min-w-0">
                  <p className="text-[13px] leading-snug text-[var(--text-primary)]">{c.text}</p>
                  {c.detail ? (
                    <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
                      {c.detail}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </Card>

        {/* Expected vs actual — the analysis this page exists for */}
        <Card>
          <CardHeader
            title="Expected vs actual"
            description="Every case result, side by side with what the case said should happen."
            icon={<ClipboardCheck aria-hidden="true" />}
            actions={
              <Segmented
                size="sm"
                label="Filter results"
                value={filter}
                onChange={(v) => setFilter(v as ResultFilter)}
                options={[
                  { id: 'all', label: `All ${counts.all}` },
                  { id: 'deviations', label: `Deviations ${counts.deviations}` },
                  { id: 'failed', label: `Failed ${counts.failed}` },
                  { id: 'asserted', label: `Asserted ${counts.asserted}` },
                ]}
              />
            }
          />
          {filtered.length === 0 ? (
            <EmptyState
              icon={<CheckCircle2 className="size-5" aria-hidden="true" />}
              title={
                filter === 'deviations'
                  ? 'No deviations'
                  : filter === 'failed'
                    ? 'No failures'
                    : filter === 'asserted'
                      ? 'No asserted results'
                      : 'No results'
              }
              description={
                filter === 'all'
                  ? 'This cycle has no executed results yet.'
                  : 'Every result in this cycle passed this filter cleanly.'
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--border-subtle)]">
              {filtered.map((r) => (
                <ResultComparison key={r.id} result={r} />
              ))}
            </ul>
          )}
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          {/*
           * Reads the live defect register rather than the closure snapshot, so
           * a defect closed by a re-test actually leaves this list. A closure
           * screen that still showed a settled defect would be arguing with the
           * evidence.
           */}
          <Card
            className={liveOpenDefects.length > 0 ? 'border-[var(--danger-border)]' : undefined}
          >
            <CardHeader
              title="Open defects at closure"
              description="Carried into the approval package rather than resolved silently."
              icon={<Bug aria-hidden="true" />}
              actions={
                liveOpenDefects.length > 0 ? (
                  <Badge tone="danger">{liveOpenDefects.length} open</Badge>
                ) : (
                  <Badge tone="ok">None</Badge>
                )
              }
            />
            {liveOpenDefects.length === 0 ? (
              <EmptyState
                icon={<CheckCircle2 className="size-5" aria-hidden="true" />}
                title="No open defects"
                description="Every defect raised in this cycle has been settled or explicitly accepted."
              />
            ) : (
              <ul className="divide-y divide-[var(--border-subtle)]">
                {liveOpenDefects.map((d) => (
                  <li key={d.ref} className="p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                        {d.ref}
                      </span>
                      <DefectSeverityBadge severity={d.severity} />
                      <DefectStatusBadge status={d.status} />
                      <span className="text-[11px] text-[var(--text-tertiary)]">{d.owner}</span>
                    </div>
                    <p className="mt-1 text-[13px] leading-snug text-[var(--text-primary)]">
                      {d.title}
                    </p>
                    {isUnverifiedFix(d) ? (
                      <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--warn)]">
                        <AlertTriangle className="mt-px size-3 shrink-0" aria-hidden="true" />
                        <span>
                          Claimed fixed but never re-tested — this cannot satisfy a closure gate.
                        </span>
                      </p>
                    ) : null}
                    <div className="mt-2">
                      <Link to="/test-runs">
                        <Button variant="ghost" size="sm">
                          {isUnverifiedFix(d) ? 'Re-test it' : 'Open in defects'}
                        </Button>
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Residual risks"
              description="What this cycle could not prove. Each needs an accountable owner."
              icon={<FileWarning aria-hidden="true" />}
              actions={
                risksNeedingAcceptance > 0 ? (
                  <Badge tone="warn">{risksNeedingAcceptance} unaccepted</Badge>
                ) : (
                  <Badge tone="ok">All accepted</Badge>
                )
              }
            />
            <ul className="divide-y divide-[var(--border-subtle)]">
              {current.residualRisks.map((r, i) => {
                const owner = r.acceptedBy ?? (accepted.has(i) ? 'Sathish Kumar' : null)
                return (
                  <li key={r.area} className="p-4">
                    <p className="text-[13px] font-semibold text-[var(--text-primary)]">{r.area}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                      {r.reason}
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      {owner ? (
                        <Badge
                          tone="ok"
                          icon={<CheckCircle2 className="size-3" aria-hidden="true" />}
                        >
                          Accepted by {owner}
                        </Badge>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={isClosed}
                          onClick={() => setAccepted((set) => new Set(set).add(i))}
                        >
                          Accept this risk
                        </Button>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          </Card>
        </div>

        {current.lessons.length > 0 ? (
          <Card>
            <CardHeader
              title="Lessons for the next cycle"
              description="Captured at closure, while the reasons are still known."
              icon={<Lightbulb aria-hidden="true" />}
            />
            <ul className="divide-y divide-[var(--border-subtle)]">
              {current.lessons.map((l) => (
                <li
                  key={l}
                  className="p-4 text-[13px] leading-relaxed text-[var(--text-secondary)]"
                >
                  {l}
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </PageBody>

      <Modal
        open={closeOpen}
        onClose={() => setCloseOpen(false)}
        title={exitReady ? 'Close this test cycle?' : 'Exit criteria are not met'}
        description={
          exitReady
            ? 'Every exit criterion the plan set is satisfied.'
            : 'This cycle can still be closed, but it will be recorded as closed with deviations and the unmet criteria will be carried into the approval package.'
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setCloseOpen(false)}>
              Cancel
            </Button>
            <Button
              variant={exitReady ? 'primary' : 'danger'}
              icon={<LogOut className="size-4" aria-hidden="true" />}
              onClick={() => close(!exitReady)}
            >
              {exitReady ? 'Close cycle' : 'Close with deviations'}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {/*
           * Open defects stated at the point of closing. They live on a
           * different screen, so a closer who never visited the defects tab
           * would otherwise sign the cycle off without ever seeing them.
           */}
          {liveOpenDefects.length > 0 ? (
            <div className="rounded-xl border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-[var(--danger)]">
                <Bug className="size-3.5 shrink-0" aria-hidden="true" />
                {liveOpenDefects.length} defect{liveOpenDefects.length === 1 ? '' : 's'} still open
              </p>
              <ul className="mt-1.5 space-y-1">
                {liveOpenDefects.map((d) => (
                  <li key={d.id} className="text-xs leading-relaxed text-[var(--text-secondary)]">
                    · <span className="font-mono">{d.ref}</span> ({d.severity}) — {d.title}
                    {isUnverifiedFix(d) ? (
                      <span className="font-medium text-[var(--warn)]">
                        {' '}
                        — claimed fixed, never re-tested
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
              {unverifiedFixes.length > 0 ? (
                <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                  A re-test would settle {unverifiedFixes.length === 1 ? 'it' : 'them'} properly.
                  Closing now carries {unverifiedFixes.length === 1 ? 'it' : 'them'} into the
                  approval package as unverified.
                </p>
              ) : null}
            </div>
          ) : null}

          {!exitReady ? (
            <ul className="space-y-2">
              {current.exitCriteria
                .filter((c) => c.met === false)
                .map((c) => (
                  <li
                    key={c.id}
                    className="flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3"
                  >
                    <AlertTriangle
                      className="mt-px size-4 shrink-0 text-[var(--warn)]"
                      aria-hidden="true"
                    />
                    <div>
                      <p className="text-xs font-semibold text-[var(--text-primary)]">{c.text}</p>
                      {c.detail ? (
                        <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                          {c.detail}
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
            </ul>
          ) : null}

          {risksNeedingAcceptance > 0 ? (
            <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">
              {risksNeedingAcceptance} residual risk
              {risksNeedingAcceptance === 1 ? ' has' : 's have'} no accountable owner. Closing now
              records {risksNeedingAcceptance === 1 ? 'it' : 'them'} as unaccepted, which the
              approval gate will surface.
            </p>
          ) : null}
        </div>
      </Modal>

      <DocumentPreview
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title={`Test closure report — ${current.requirementRef}`}
        subtitle={
          isClosed
            ? `Closed by ${current.closedBy} · ${relativeTime(current.closedAt)}`
            : `Open · ${exitUnmet} exit criteri${exitUnmet === 1 ? 'on' : 'a'} unmet`
        }
        filename={`${current.requirementRef}-test-closure.pdf`}
      >
        <ClosureDocument closure={current} results={results} openDefects={liveOpenDefects} />
      </DocumentPreview>
    </>
  )
}

/**
 * Closure rendered as a document. Open defects and unaccepted residual risks
 * are included deliberately — a closure report that omitted them would be the
 * exact document an auditor should not be able to rely on.
 */
function ClosureDocument({
  closure,
  results,
  openDefects,
}: {
  closure: TestClosure
  results: CaseResult[]
  /** Live defect register, so the export matches what the screen shows. */
  openDefects: Defect[]
}) {
  const s = closure.summary
  return (
    <>
      <DocSection title="Document control">
        <DocFacts
          facts={[
            ['Requirement', closure.requirementRef],
            ['Plan', closure.planId.toUpperCase()],
            [
              'State',
              closure.state === 'closed'
                ? 'Closed'
                : closure.state === 'closed_with_deviations'
                  ? 'Closed with deviations'
                  : 'Open',
            ],
            ['Closed by', closure.closedBy ?? '—'],
            ['Executions', String(closure.executionIds.length)],
            ['Total cost', formatUsd(closure.totalCostUsd)],
          ]}
        />
      </DocSection>

      <DocSection title="Result summary">
        <DocFacts
          facts={[
            ['Cases planned', String(s.casesTotal)],
            ['Passed', String(s.passed)],
            ['Failed', String(s.failed)],
            ['Never run', String(s.notRun)],
            ['Verified evidence', String(s.verified)],
            ['Asserted only', String(s.asserted)],
          ]}
        />
      </DocSection>

      <DocSection title="Exit criteria">
        <DocCriteria items={closure.exitCriteria} />
      </DocSection>

      <DocSection title="Deviations">
        {results.filter((r) => r.deviation).length === 0 ? (
          <p className="text-[13px] text-[var(--text-tertiary)]">None recorded.</p>
        ) : (
          <ul className="space-y-3">
            {results
              .filter((r) => r.deviation)
              .map((r) => (
                <li key={r.id}>
                  <p className="font-mono text-[11px] text-[var(--text-tertiary)]">{r.caseRef}</p>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--text-secondary)]">
                    {r.deviation}
                  </p>
                </li>
              ))}
          </ul>
        )}
      </DocSection>

      {/* Live register, matching the screen. An exported report that still
          listed a defect the re-test closed would contradict the record it is
          supposed to be. */}
      <DocSection title="Open defects at closure">
        {openDefects.length === 0 ? (
          <p className="text-[13px] text-[var(--text-tertiary)]">None.</p>
        ) : (
          <ul className="space-y-2">
            {openDefects.map((d) => (
              <li key={d.ref}>
                <p className="text-[13px] leading-snug text-[var(--text-primary)]">
                  <span className="font-mono text-[11px] text-[var(--text-tertiary)]">{d.ref}</span>{' '}
                  {d.title}
                </p>
                <p className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">
                  {d.severity} · {d.owner} · {d.status.replace('_', ' ')}
                  {isUnverifiedFix(d) ? ' — claimed fixed, never re-tested' : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
      </DocSection>

      <DocSection title="Residual risks">
        <ul className="space-y-2.5">
          {closure.residualRisks.map((r) => (
            <li key={r.area}>
              <p className="text-[13px] font-medium text-[var(--text-primary)]">{r.area}</p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                {r.reason}
              </p>
              <p
                className={cn(
                  'mt-0.5 text-[11px]',
                  r.acceptedBy ? 'text-[var(--ok)]' : 'text-[var(--warn)]',
                )}
              >
                {r.acceptedBy ? `Accepted by ${r.acceptedBy}` : 'Not yet accepted'}
              </p>
            </li>
          ))}
        </ul>
      </DocSection>

      {closure.lessons.length > 0 ? (
        <DocSection title="Lessons">
          <DocList items={closure.lessons} />
        </DocSection>
      ) : null}
    </>
  )
}

/**
 * One case result rendered as an expected/actual pair.
 *
 * Both sides are always shown, even when they agree. Hiding the comparison on
 * a pass would make "expected" look like something only failures have, when it
 * is actually the thing that makes a pass mean anything.
 */
function ResultComparison({ result: r }: { result: CaseResult }) {
  const diverged = r.status === 'failed' || Boolean(r.deviation)

  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <RunStatusBadge status={r.status} />
        <EvidenceGradeBadge grade={r.grade} />
        <span className="font-mono text-[11px] text-[var(--text-tertiary)]">{r.caseRef}</span>
        {r.defectRef ? <Badge tone="danger">{r.defectRef}</Badge> : null}
        <span className="tabular ml-auto text-[11px] text-[var(--text-tertiary)]">
          {formatDuration(r.durationSeconds)} · {r.attempts} attempt{r.attempts === 1 ? '' : 's'}
        </span>
      </div>

      <p className="mt-1.5 text-[13px] leading-snug font-medium text-[var(--text-primary)]">
        {r.caseTitle}
      </p>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <SectionLabel>Expected</SectionLabel>
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
            {r.expected}
          </p>
        </div>
        <div
          className={cn(
            'rounded-xl border p-3',
            diverged
              ? 'border-[var(--danger-border)] bg-[var(--danger-subtle)]'
              : 'border-[var(--ok-border)] bg-[var(--ok-subtle)]',
          )}
        >
          <SectionLabel>Actual</SectionLabel>
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">{r.actual}</p>
        </div>
      </div>

      {r.deviation ? (
        <div className="mt-2 flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
          <AlertTriangle className="mt-px size-4 shrink-0 text-[var(--warn)]" aria-hidden="true" />
          <div>
            <p className="text-xs font-semibold text-[var(--warn)]">Deviation</p>
            <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
              {r.deviation}
            </p>
          </div>
        </div>
      ) : null}

      {r.artifacts.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {r.artifacts.map((a) => (
            <Badge key={a.id} tone="neutral">
              {a.label} · {a.sizeLabel}
            </Badge>
          ))}
        </div>
      ) : null}
    </li>
  )
}

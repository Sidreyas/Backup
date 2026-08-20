import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  ClipboardCheck,
  Cpu,
  Download,
  FileVideo,
  FlaskConical,
  Hash,
  RotateCw,
  Search,
  ShieldCheck,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SectionLabel,
  StatTile,
  TableSkeleton,
  SearchInput,
} from '@/components/ui/primitives'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Drawer, Tabs, useToast } from '@/components/ui/overlays'
import { EvidenceGradeBadge, RunStatusBadge } from '@/components/domain/status'
import { EnvironmentCard } from './ImpactPage'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { cn, formatDateTime, formatDuration, formatUsd, humanize, relativeTime } from '@/lib/utils'
import type { TestRun } from '@/lib/types'

export function EvidencePage() {
  const { items: runs, loading } = useAsyncList(() => api.getTestRuns(), [])
  const [tab, setTab] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<TestRun | null>(null)

  const counts = useMemo(
    () => ({
      all: runs.length,
      verified: runs.filter((r) => r.grade === 'verified').length,
      asserted: runs.filter((r) => r.grade === 'asserted').length,
      failing: runs.filter((r) => r.status === 'failed' || r.status === 'flaky').length,
    }),
    [runs],
  )

  const filtered = useMemo(() => {
    let list = runs
    if (tab === 'verified') list = list.filter((r) => r.grade === 'verified')
    if (tab === 'asserted') list = list.filter((r) => r.grade === 'asserted')
    if (tab === 'failing') list = list.filter((r) => r.status === 'failed' || r.status === 'flaky')
    const q = query.trim().toLowerCase()
    if (q)
      list = list.filter(
        (r) => r.title.toLowerCase().includes(q) || r.ref.toLowerCase().includes(q),
      )
    return list
  }, [runs, tab, query])

  const columns: Column<TestRun>[] = [
    {
      id: 'ref',
      header: 'Ref',
      sortValue: (r) => r.ref,
      className: 'w-[86px]',
      cell: (r) => <span className="font-mono text-xs text-[var(--text-tertiary)]">{r.ref}</span>,
    },
    {
      id: 'title',
      header: 'Assertion under test',
      sortValue: (r) => r.title,
      className: 'min-w-[300px]',
      cell: (r) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--text-primary)]">{r.title}</p>
          <p className="truncate font-mono text-[10px] text-[var(--text-tertiary)]">
            {r.suite ?? 'No committed suite — agent run only'}
          </p>
        </div>
      ),
    },
    {
      id: 'grade',
      header: 'Grade',
      sortValue: (r) => r.grade,
      cell: (r) => <EvidenceGradeBadge grade={r.grade} />,
    },
    {
      id: 'status',
      header: 'Result',
      sortValue: (r) => r.status,
      cell: (r) => <RunStatusBadge status={r.status} />,
    },
    {
      id: 'flake',
      header: 'Flake',
      align: 'right',
      sortValue: (r) => r.flakeRate,
      cell: (r) => (
        <span
          className={cn('tabular text-xs', r.flakeRate > 0.1 && 'font-medium text-[var(--warn)]')}
        >
          {r.flakeRate > 0 ? `${Math.round(r.flakeRate * 100)}%` : '—'}
        </span>
      ),
    },
    {
      id: 'duration',
      header: 'Duration',
      align: 'right',
      sortValue: (r) => r.durationSeconds,
      cell: (r) => <span className="tabular text-xs">{formatDuration(r.durationSeconds)}</span>,
    },
    {
      id: 'artifacts',
      header: 'Artifacts',
      align: 'right',
      sortValue: (r) => r.artifacts.length,
      cell: (r) => <span className="tabular text-xs">{r.artifacts.length}</span>,
    },
    {
      id: 'started',
      header: 'Started',
      sortValue: (r) => r.startedAt,
      cell: (r) => <span className="whitespace-nowrap text-xs">{relativeTime(r.startedAt)}</span>,
    },
  ]

  return (
    <>
      <PageHeader
        title="Evidence Runs"
        icon={<ClipboardCheck aria-hidden="true" />}
        tone="ok"
        actions={
          <Button variant="secondary" icon={<Download className="size-4" aria-hidden="true" />}>
            Export evidence pack
          </Button>
        }
      />

      <PageBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Verified"
            value={counts.verified}
            tone="verified"
            icon={<ShieldCheck className="size-4" aria-hidden="true" />}
            sublabel="Deterministic, replayable, artifact-backed"
          />
          <StatTile
            label="Asserted"
            value={counts.asserted}
            tone="asserted"
            icon={<Cpu className="size-4" aria-hidden="true" />}
            sublabel="Agent claim — cannot satisfy a gate"
          />
          <StatTile
            label="Failing or flaky"
            value={counts.failing}
            tone={counts.failing > 0 ? 'danger' : 'ok'}
            sublabel="Blocking at least one approval"
          />
          <StatTile
            label="Evidence spend"
            value={formatUsd(
              runs.reduce((a, r) => a + r.costUsd, 0),
              { precise: true },
            )}
            tone="info"
            sublabel="Compute + model cost for these runs"
          />
        </div>

        <div className="flex items-start gap-2.5 rounded-xl border border-[var(--asserted-border)] bg-[var(--asserted-subtle)] p-3">
          <Cpu className="mt-px size-4 shrink-0 text-[var(--asserted)]" aria-hidden="true" />
          <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
            <span className="font-semibold text-[var(--asserted)]">
              Why the distinction matters.
            </span>{' '}
            A browser agent that reports "it works" produces a claim, not proof — it cannot be
            replayed and its failure rate is unknown. Meridian records those runs as{' '}
            <span className="font-medium">asserted</span> and refuses to let them close a gate. To
            convert an assertion into evidence, promote it to a committed deterministic spec.
          </p>
        </div>

        <Card>
          <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] p-3 sm:flex-row sm:items-center sm:justify-between">
            <Tabs
              className="border-b-0"
              value={tab}
              onChange={setTab}
              items={[
                { id: 'all', label: 'All runs', count: counts.all },
                { id: 'verified', label: 'Verified', count: counts.verified },
                { id: 'asserted', label: 'Asserted', count: counts.asserted },
                { id: 'failing', label: 'Failing', count: counts.failing },
              ]}
            />
            <SearchInput
              className="sm:w-64"
              value={query}
              onChange={setQuery}
              placeholder="Filter evidence…"
              label="Filter evidence runs"
              icon={<Search className="size-3.5" aria-hidden="true" />}
            />
          </div>

          {loading ? (
            <TableSkeleton rows={8} cols={8} />
          ) : (
            <DataTable
              rows={filtered}
              columns={columns}
              getRowId={(r) => r.id}
              onRowClick={setSelected}
              selectedId={selected?.id ?? null}
              initialSort={{ columnId: 'started', dir: 'desc' }}
              emptyState={
                <EmptyState
                  icon={<FlaskConical className="size-5" aria-hidden="true" />}
                  title="No evidence matches this filter"
                  description="Evidence appears here once a regression suite has been generated and run against a sandbox."
                  action={
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setTab('all')
                        setQuery('')
                      }}
                    >
                      Clear filters
                    </Button>
                  }
                />
              }
            />
          )}
        </Card>
      </PageBody>

      <RunDrawer run={selected} onClose={() => setSelected(null)} />
    </>
  )
}

function RunDrawer({ run, onClose }: { run: TestRun | null; onClose: () => void }) {
  const { push } = useToast()
  if (!run) return null

  return (
    <Drawer
      open={Boolean(run)}
      onClose={onClose}
      width="lg"
      title={run.title}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="neutral" mono>
            {run.ref}
          </Badge>
          <EvidenceGradeBadge grade={run.grade} />
          <RunStatusBadge status={run.status} />
        </div>
      }
      footer={
        <>
          <Button
            variant="secondary"
            icon={<RotateCw className="size-4" aria-hidden="true" />}
            onClick={() => push({ tone: 'info', title: 'Re-run queued', description: run.ref })}
          >
            Re-run
          </Button>
          {run.grade === 'asserted' ? (
            <Button
              variant="primary"
              icon={<ShieldCheck className="size-4" aria-hidden="true" />}
              onClick={() =>
                push({
                  tone: 'ok',
                  title: 'Promotion started',
                  description: 'The agent will author a deterministic spec from this run.',
                })
              }
            >
              Promote to verified
            </Button>
          ) : (
            <Button variant="primary" icon={<Download className="size-4" aria-hidden="true" />}>
              Download artifacts
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4 p-5">
        {run.grade === 'asserted' ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--asserted-border)] bg-[var(--asserted-subtle)] p-3">
            <Cpu className="mt-px size-4 shrink-0 text-[var(--asserted)]" aria-hidden="true" />
            <div>
              <p className="text-xs font-semibold text-[var(--asserted)]">Asserted, not verified</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                An agent performed this check once and reported success. There is no committed spec,
                so it cannot be replayed deterministically and no flake rate is known. This evidence
                will not satisfy any gate that requires verified grade.
              </p>
            </div>
          </div>
        ) : null}

        {run.failureReason ? (
          <div
            className={cn(
              'flex items-start gap-2.5 rounded-xl border p-3',
              run.status === 'failed'
                ? 'border-[var(--danger-border)] bg-[var(--danger-subtle)]'
                : 'border-[var(--warn-border)] bg-[var(--warn-subtle)]',
            )}
          >
            <AlertTriangle
              className={cn(
                'mt-px size-4 shrink-0',
                run.status === 'failed' ? 'text-[var(--danger)]' : 'text-[var(--warn)]',
              )}
              aria-hidden="true"
            />
            <div>
              <p
                className={cn(
                  'text-xs font-semibold',
                  run.status === 'failed' ? 'text-[var(--danger)]' : 'text-[var(--warn)]',
                )}
              >
                {run.status === 'failed' ? 'Failure' : 'Instability detected'}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                {run.failureReason}
              </p>
            </div>
          </div>
        ) : null}

        <EnvironmentCard fingerprint={run.environment} />

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
          {[
            ['Runner', run.runner],
            ['Started', formatDateTime(run.startedAt)],
            ['Duration', formatDuration(run.durationSeconds)],
            ['Attempts', String(run.attempts)],
            [
              'Flake rate',
              run.flakeRate > 0 ? `${Math.round(run.flakeRate * 100)}%` : 'None observed',
            ],
            ['Cost', formatUsd(run.costUsd, { precise: true })],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[10px] tracking-wide text-[var(--text-tertiary)] uppercase">
                {k}
              </dt>
              <dd className="tabular mt-0.5 text-xs text-[var(--text-primary)]">{v}</dd>
            </div>
          ))}
        </dl>

        {run.suite ? (
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
            <SectionLabel>Committed spec</SectionLabel>
            <p className="mt-1.5 font-mono text-xs break-all text-[var(--text-primary)]">
              {run.suite}
            </p>
            <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
              This spec lives in the repository and re-runs on every release. That is what makes the
              result replayable rather than a one-off observation.
            </p>
          </div>
        ) : null}

        <div>
          <SectionLabel>Artifacts ({run.artifacts.length})</SectionLabel>
          {run.artifacts.length === 0 ? (
            <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
              No artifacts yet — this run is still in progress.
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {run.artifacts.map((a) => (
                <li
                  key={a.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-2.5"
                >
                  <div className="flex min-w-0 items-center gap-2.5">
                    <FileVideo
                      className="size-4 shrink-0 text-[var(--text-tertiary)]"
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs text-[var(--text-primary)]">
                        {a.label}
                      </p>
                      <p className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)]">
                        <Hash className="size-2.5" aria-hidden="true" />
                        <span className="font-mono">{a.sha256}</span>
                        <span aria-hidden="true">·</span>
                        {humanize(a.kind)} · {a.sizeLabel}
                      </p>
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" aria-label={`Download ${a.label}`}>
                    <Download className="size-3.5" aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
            Every artifact is content-hashed and committed into the audit chain, so the evidence
            attached to a sign-off cannot be swapped after the fact.
          </p>
        </div>
      </div>
    </Drawer>
  )
}

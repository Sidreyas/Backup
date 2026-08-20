import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  Beaker,
  Database,
  EyeOff,
  FlaskConical,
  Search,
  ShieldAlert,
  Target,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  SearchInput,
  SectionLabel,
  Skeleton,
  TableSkeleton,
} from '@/components/ui/primitives'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Drawer, Tabs } from '@/components/ui/overlays'
import {
  ConfidenceBadge,
  NodeKindBadge,
  RiskBadge,
  SeverityBadge,
  StageBadge,
} from '@/components/domain/status'
import { api } from '@/lib/api'
import { useAsync, useAsyncList } from '@/lib/useAsync'
import { cn, formatDateTime, formatDuration, formatUsd, relativeTime } from '@/lib/utils'
import type { ImpactAnalysis, ImpactItem, Requirement } from '@/lib/types'

/**
 * `/impact` lists every analysis; `/impact/:id` opens one.
 *
 * The index exists because an analysis only means something next to the others
 * — which changes are riskiest, which have coverage gaps, and which
 * requirements have not been analysed at all.
 */
export function ImpactPage() {
  const { id } = useParams()
  return id ? <ImpactDetail id={id} /> : <ImpactIndex />
}

function ImpactDetail({ id }: { id: string }) {
  const { data: impact, loading } = useAsync(() => api.getImpact(id), [id])
  const { data: requirement } = useAsync(() => api.getRequirement(id), [id])
  const [selected, setSelected] = useState<ImpactItem | null>(null)

  const items = useMemo(() => impact?.items ?? [], [impact])

  const summary = useMemo(
    () => ({
      breaking: items.filter((i) => i.severity === 'breaking').length,
      major: items.filter((i) => i.severity === 'major').length,
      gaps: items.filter((i) => i.coverageGap).length,
      unconfirmed: items.filter((i) => i.confidence !== 'confirmed').length,
    }),
    [items],
  )

  const columns: Column<ImpactItem>[] = [
    {
      id: 'node',
      header: 'Impacted object',
      sortValue: (r) => r.nodeLabel,
      className: 'min-w-[260px]',
      cell: (r) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--text-primary)]">{r.nodeLabel}</p>
          <p className="truncate font-mono text-[10px] text-[var(--text-tertiary)]">
            {r.provenance}
          </p>
        </div>
      ),
    },
    {
      id: 'kind',
      header: 'Type',
      sortValue: (r) => r.nodeKind,
      cell: (r) => <NodeKindBadge kind={r.nodeKind} />,
    },
    {
      id: 'severity',
      header: 'Severity',
      sortValue: (r) => ['breaking', 'major', 'minor', 'none'].indexOf(r.severity),
      cell: (r) => <SeverityBadge severity={r.severity} />,
    },
    {
      id: 'confidence',
      header: 'Confidence',
      sortValue: (r) => r.confidence,
      cell: (r) => <ConfidenceBadge confidence={r.confidence} />,
    },
    {
      id: 'coverage',
      header: 'Test coverage',
      sortValue: (r) => (r.coverageGap ? 0 : r.coveredByTestIds.length),
      cell: (r) =>
        r.coverageGap ? (
          <Badge tone="danger" icon={<AlertTriangle className="size-3" aria-hidden="true" />}>
            No coverage
          </Badge>
        ) : (
          <span className="tabular text-xs">
            {r.coveredByTestIds.length} test{r.coveredByTestIds.length === 1 ? '' : 's'}
          </span>
        ),
    },
    {
      id: 'owner',
      header: 'Owner',
      sortValue: (r) => r.owner,
      cell: (r) => <span className="text-xs whitespace-nowrap">{r.owner}</span>,
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Impact analysis"
        title={requirement?.title ?? 'Impact Analysis'}
        icon={<Target aria-hidden="true" />}
        tone="warn"
        meta={
          requirement ? (
            <>
              <Badge tone="neutral" mono>
                {requirement.ref}
              </Badge>
              <StageBadge stage={requirement.stage} />
              <RiskBadge risk={requirement.riskLevel} />
            </>
          ) : null
        }
        actions={
          <>
            <Link to="/impact">
              <Button variant="ghost" icon={<ArrowLeft className="size-4" aria-hidden="true" />}>
                All analyses
              </Button>
            </Link>
            <Link to={`/requirements/${id}`}>
              <Button variant="ghost">Discussion</Button>
            </Link>
            {/* Agreeing the impact analysis is what opens the testing cycle —
                this is the handoff from "what will this change" to "how will
                we prove it". */}
            <Link to="/test-plan">
              <Button
                variant="primary"
                icon={<FlaskConical className="size-4" aria-hidden="true" />}
              >
                Proceed to test plan
              </Button>
            </Link>
          </>
        }
      />

      <PageBody className="space-y-4">
        {loading ? (
          <div className="space-y-4">
            {/* One block, matching the content that actually loads — the tile
                row it used to mimic is gone. */}
            <Skeleton className="h-80 rounded-2xl" />
          </div>
        ) : !impact ? (
          <Card>
            <EmptyState
              icon={<Target className="size-5" aria-hidden="true" />}
              title="No impact analysis yet"
              description="Impact analysis runs once a requirement has an agreed approach. Return to the discussion to settle the approach first."
              action={
                <Link to={`/requirements/${id}`}>
                  <Button variant="primary">Open discussion</Button>
                </Link>
              }
            />
          </Card>
        ) : (
          <>
            {summary.gaps > 0 ? (
              <div className="flex items-start gap-2.5 rounded-xl border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-3">
                <ShieldAlert
                  className="mt-px size-4 shrink-0 text-[var(--danger)]"
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-[var(--danger)]">
                    Policy POL-004 will block sign-off
                  </p>
                  <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                    This change is payroll-relevant, and {summary.gaps} impacted object
                    {summary.gaps === 1 ? ' has' : 's have'} no verified regression coverage.
                    Generate tests for the gaps, or an accountable approver must explicitly override
                    the policy and record why.
                  </p>
                </div>
              </div>
            ) : null}

            <Card>
              <CardHeader
                title="Impacted objects"
                description={`${items.length} objects reached from the change. Select any row for the reasoning behind it.`}
                icon={<Target className="size-4" aria-hidden="true" />}
              />
              <DataTable
                rows={items}
                columns={columns}
                getRowId={(r) => r.id}
                onRowClick={setSelected}
                selectedId={selected?.id ?? null}
                initialSort={{ columnId: 'severity', dir: 'asc' }}
              />
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader
                  title="Declared blind spots"
                  description="Meridian states what it cannot analyse rather than implying full coverage."
                  icon={<EyeOff className="size-4" aria-hidden="true" />}
                />
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {impact.blindSpots.map((b) => (
                    <li key={b.area} className="flex items-start gap-2.5 p-3">
                      <AlertTriangle
                        className="mt-px size-4 shrink-0 text-[var(--warn)]"
                        aria-hidden="true"
                      />
                      <div>
                        <p className="text-xs font-semibold text-[var(--text-primary)]">{b.area}</p>
                        <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                          {b.reason}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>

              <Card>
                <CardHeader
                  title="Analysis provenance"
                  description="Which environment this was computed against, and what it cost."
                  icon={<Database className="size-4" aria-hidden="true" />}
                />
                <div className="space-y-3 p-4">
                  <EnvironmentCard fingerprint={impact.environmentFingerprint} />
                  <dl className="grid grid-cols-2 gap-3">
                    {[
                      ['Generated', formatDateTime(impact.generatedAt)],
                      ['Model', impact.model],
                      ['Duration', formatDuration(impact.durationSeconds)],
                      ['Cost', formatUsd(impact.costUsd, { precise: true })],
                    ].map(([k, v]) => (
                      <div key={k}>
                        <dt className="text-[10px] tracking-wide text-[var(--text-tertiary)] uppercase">
                          {k}
                        </dt>
                        <dd className="tabular mt-0.5 font-mono text-xs text-[var(--text-primary)]">
                          {v}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </Card>
            </div>
          </>
        )}
      </PageBody>

      <ImpactDrawer item={selected} onClose={() => setSelected(null)} />
    </>
  )
}

/* ------------------------------------------------------------------ index */

interface AnalysisRow {
  requirementId: string
  ref: string
  title: string
  stage: Requirement['stage']
  risk: Requirement['riskLevel']
  platform: string
  /** null when the requirement has not been analysed yet */
  analysis: ImpactAnalysis | null
  breaking: number
  gaps: number
  unconfirmed: number
}

function ImpactIndex() {
  const { items: requirements, loading: reqLoading } = useAsyncList(() => api.getRequirements(), [])
  const { items: analyses, loading: anLoading } = useAsyncList(() => api.getImpactAnalyses(), [])
  const navigate = useNavigate()
  const [tab, setTab] = useState('analysed')
  const [query, setQuery] = useState('')

  const loading = reqLoading || anLoading

  const rows: AnalysisRow[] = useMemo(() => {
    const byReq = new Map(analyses.map((a) => [a.requirementId, a]))
    return requirements.map((r) => {
      const analysis = byReq.get(r.id) ?? null
      const items = analysis?.items ?? []
      return {
        requirementId: r.id,
        ref: r.ref,
        title: r.title,
        stage: r.stage,
        risk: r.riskLevel,
        platform: r.platform,
        analysis,
        breaking: items.filter((i) => i.severity === 'breaking').length,
        gaps: items.filter((i) => i.coverageGap).length,
        unconfirmed: items.filter((i) => i.confidence !== 'confirmed').length,
      }
    })
  }, [requirements, analyses])

  const counts = useMemo(
    () => ({
      analysed: rows.filter((r) => r.analysis).length,
      pending: rows.filter((r) => !r.analysis).length,
      all: rows.length,
    }),
    [rows],
  )

  const filtered = useMemo(() => {
    let list = rows
    if (tab === 'analysed') list = list.filter((r) => r.analysis)
    if (tab === 'pending') list = list.filter((r) => !r.analysis)
    const q = query.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (r) => r.title.toLowerCase().includes(q) || r.ref.toLowerCase().includes(q),
      )
    }
    return list
  }, [rows, tab, query])

  const columns: Column<AnalysisRow>[] = [
    {
      id: 'ref',
      header: 'Ref',
      sortValue: (r) => r.ref,
      className: 'w-[92px]',
      cell: (r) => <span className="font-mono text-xs text-[var(--text-tertiary)]">{r.ref}</span>,
    },
    {
      id: 'title',
      header: 'Requirement',
      sortValue: (r) => r.title,
      className: 'min-w-[280px]',
      cell: (r) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--text-primary)]">{r.title}</p>
          <p className="truncate text-xs text-[var(--text-tertiary)]">{r.platform}</p>
        </div>
      ),
    },
    {
      id: 'stage',
      header: 'Stage',
      sortValue: (r) => r.stage,
      cell: (r) => <StageBadge stage={r.stage} />,
    },
    {
      id: 'objects',
      header: 'Impacted',
      align: 'right',
      sortValue: (r) => r.analysis?.items.length ?? -1,
      cell: (r) =>
        r.analysis ? (
          <span className="tabular">{r.analysis.items.length}</span>
        ) : (
          <span className="text-xs text-[var(--text-tertiary)]">—</span>
        ),
    },
    {
      id: 'breaking',
      header: 'Breaking',
      align: 'right',
      sortValue: (r) => r.breaking,
      cell: (r) =>
        !r.analysis ? (
          <span className="text-xs text-[var(--text-tertiary)]">—</span>
        ) : r.breaking > 0 ? (
          <Badge tone="danger">{r.breaking}</Badge>
        ) : (
          <span className="tabular text-[var(--text-tertiary)]">0</span>
        ),
    },
    {
      id: 'gaps',
      header: 'Coverage gaps',
      align: 'right',
      sortValue: (r) => r.gaps,
      cell: (r) =>
        !r.analysis ? (
          <span className="text-xs text-[var(--text-tertiary)]">—</span>
        ) : r.gaps > 0 ? (
          <Badge tone="warn" icon={<AlertTriangle className="size-3" aria-hidden="true" />}>
            {r.gaps}
          </Badge>
        ) : (
          <Badge tone="ok">None</Badge>
        ),
    },
    {
      id: 'generated',
      header: 'Analysed',
      sortValue: (r) => r.analysis?.generatedAt ?? '',
      cell: (r) =>
        r.analysis ? (
          <span className="text-xs whitespace-nowrap">{relativeTime(r.analysis.generatedAt)}</span>
        ) : (
          <span className="text-xs whitespace-nowrap text-[var(--text-tertiary)]">
            Not yet analysed
          </span>
        ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Impact Analysis"
        icon={<Target aria-hidden="true" />}
        tone="warn"
      />

      <PageBody className="space-y-4">
        <Card>
          <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] p-3 sm:flex-row sm:items-center sm:justify-between">
            <Tabs
              className="border-b-0"
              value={tab}
              onChange={setTab}
              items={[
                { id: 'analysed', label: 'Analysed', count: counts.analysed },
                { id: 'pending', label: 'Not analysed', count: counts.pending },
                { id: 'all', label: 'All', count: counts.all },
              ]}
            />
            <SearchInput
              className="sm:w-64"
              value={query}
              onChange={setQuery}
              placeholder="Filter analyses…"
              label="Filter analyses"
              icon={<Search className="size-3.5" aria-hidden="true" />}
            />
          </div>

          {loading ? (
            <TableSkeleton rows={5} cols={columns.length} />
          ) : (
            <DataTable
              rows={filtered}
              columns={columns}
              getRowId={(r) => r.requirementId}
              // A row without an analysis goes to the discussion instead — that
              // is where the analysis gets unblocked.
              onRowClick={(r) =>
                navigate(
                  r.analysis ? `/impact/${r.requirementId}` : `/requirements/${r.requirementId}`,
                )
              }
              initialSort={{ columnId: 'generated', dir: 'desc' }}
              emptyState={
                <EmptyState
                  icon={<Target className="size-5" aria-hidden="true" />}
                  title="No analyses match this filter"
                  description="Impact analysis runs once a requirement has an agreed approach, so a change still in discussion will not appear here."
                  action={
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setQuery('')
                        setTab('all')
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
    </>
  )
}

export function EnvironmentCard({
  fingerprint,
}: {
  fingerprint: import('@/lib/types').EnvironmentFingerprint
}) {
  const lowFidelity = fingerprint.dataCoverage < 60
  return (
    <div
      className={cn(
        'rounded-xl border p-3',
        lowFidelity
          ? 'border-[var(--warn-border)] bg-[var(--warn-subtle)]'
          : 'border-[var(--border-subtle)] bg-[var(--bg-surface-2)]',
      )}
    >
      <div className="flex items-center gap-1.5">
        <Beaker className="size-3.5 text-[var(--text-tertiary)]" aria-hidden="true" />
        <SectionLabel>Environment fingerprint</SectionLabel>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-[var(--text-tertiary)]">Environment</dt>
          <dd className="truncate text-right font-medium text-[var(--text-primary)]">
            {fingerprint.environment}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-[var(--text-tertiary)]">Release</dt>
          <dd className="truncate text-right font-mono text-[var(--text-primary)]">
            {fingerprint.release}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-[var(--text-tertiary)]">Tenant</dt>
          <dd className="truncate text-right font-mono text-[var(--text-primary)]">
            {fingerprint.tenant}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-[var(--text-tertiary)]">Refreshed</dt>
          <dd className="truncate text-right text-[var(--text-primary)]">
            {relativeTime(fingerprint.refreshedAt)}
          </dd>
        </div>
      </dl>
      <p
        className={cn(
          'mt-2 text-[11px] leading-relaxed',
          lowFidelity ? 'text-[var(--warn)]' : 'text-[var(--text-tertiary)]',
        )}
      >
        {lowFidelity ? <AlertTriangle className="mr-1 inline size-3" aria-hidden="true" /> : null}
        Data coverage {fingerprint.dataCoverage}% — evidence produced here represents{' '}
        {fingerprint.dataCoverage}% of production scenario classes.
      </p>
    </div>
  )
}

function ImpactDrawer({ item, onClose }: { item: ImpactItem | null; onClose: () => void }) {
  if (!item) return null
  return (
    <Drawer
      open={Boolean(item)}
      onClose={onClose}
      title={item.nodeLabel}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <NodeKindBadge kind={item.nodeKind} />
          <SeverityBadge severity={item.severity} />
          <ConfidenceBadge confidence={item.confidence} />
        </div>
      }
      footer={
        <Button variant="primary" icon={<FlaskConical className="size-4" aria-hidden="true" />}>
          {item.coverageGap ? 'Generate test for this gap' : 'View covering tests'}
        </Button>
      }
    >
      <div className="space-y-4 p-5">
        <div>
          <SectionLabel>Why this is impacted</SectionLabel>
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--text-secondary)]">
            {item.reason}
          </p>
        </div>

        {item.confidence !== 'confirmed' ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
            <AlertTriangle
              className="mt-px size-4 shrink-0 text-[var(--warn)]"
              aria-hidden="true"
            />
            <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
              This finding rests on an unconfirmed graph link. Confirming the link in the Graph
              Explorer raises confidence and improves every future analysis touching this object.
            </p>
          </div>
        ) : null}

        {item.coverageGap ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-3">
            <ShieldAlert
              className="mt-px size-4 shrink-0 text-[var(--danger)]"
              aria-hidden="true"
            />
            <div>
              <p className="text-xs font-semibold text-[var(--danger)]">No regression coverage</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                Meridian flagged this object as impacted but has no deterministic test proving its
                behaviour. Under POL-004 this blocks sign-off for payroll-relevant changes.
              </p>
            </div>
          </div>
        ) : null}

        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <SectionLabel>Provenance</SectionLabel>
          <p className="mt-1.5 font-mono text-xs break-all text-[var(--text-primary)]">
            {item.provenance}
          </p>
        </div>

        <dl className="grid grid-cols-2 gap-3">
          <div>
            <dt className="text-[10px] tracking-wide text-[var(--text-tertiary)] uppercase">
              Owner
            </dt>
            <dd className="mt-0.5 text-sm text-[var(--text-primary)]">{item.owner}</dd>
          </div>
          <div>
            <dt className="text-[10px] tracking-wide text-[var(--text-tertiary)] uppercase">
              Covering tests
            </dt>
            <dd className="tabular mt-0.5 text-sm text-[var(--text-primary)]">
              {item.coveredByTestIds.length || '—'}
            </dd>
          </div>
        </dl>
      </div>
    </Drawer>
  )
}

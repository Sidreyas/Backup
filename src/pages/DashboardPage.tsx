import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Database,
  Download,
  LayoutGrid,
  MessagesSquare,
  ShieldCheck,
} from 'lucide-react'
import { PageBody, PageFilters, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  SectionTitle,
  Segmented,
  Skeleton,
  StatTile,
} from '@/components/ui/primitives'
import { RiskBadge, StageBadge } from '@/components/domain/status'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { formatUsd, relativeTime } from '@/lib/utils'

/** Deterministic mock trend series for the KPI sparklines. */
const TRENDS = {
  open: [3, 4, 4, 5, 4, 6, 5, 4],
  decisions: [1, 2, 2, 3, 2, 4, 3, 3],
  evidence: [5, 6, 6, 7, 7, 8, 8, 8],
  sources: [4, 3, 3, 2, 3, 2, 2, 2],
}

export function DashboardPage() {
  const [range, setRange] = useState<'today' | 'week' | 'month'>('week')
  const { items: requirements, loading: reqLoading } = useAsyncList(() => api.getRequirements(), [])
  const { items: approvals } = useAsyncList(() => api.getApprovals(), [])
  const { items: runs } = useAsyncList(() => api.getTestRuns(), [])
  const { items: sources } = useAsyncList(() => api.getSources(), [])

  const openReqs = requirements.filter((r) => r.stage !== 'signed_off' && r.stage !== 'rejected')
  const pendingGates = approvals.flatMap((p) => p.gates).filter((g) => g.decision === 'pending')
  const blockedGates = pendingGates.filter((g) => g.blockedBy.length > 0)
  const failingRuns = runs.filter((r) => r.status === 'failed' || r.status === 'flaky')
  const brokenSources = sources.filter((s) => s.status === 'error' || s.status === 'stale')

  const verified = runs.filter((r) => r.grade === 'verified').length
  const asserted = runs.filter((r) => r.grade === 'asserted').length

  return (
    <>
      <PageHeader
        title="Overview"
        icon={<LayoutGrid aria-hidden="true" />}
        tone="accent"
        actions={
          <>
            <Button variant="secondary" icon={<Download className="size-4" aria-hidden="true" />}>
              Export
            </Button>
            <Link to="/requirements">
              <Button
                variant="primary"
                icon={<MessagesSquare className="size-4" aria-hidden="true" />}
              >
                New requirement
              </Button>
            </Link>
          </>
        }
      />

      <PageFilters>
        <Segmented
          label="Time range"
          value={range}
          onChange={setRange}
          options={[
            { id: 'today', label: 'Today' },
            { id: 'week', label: 'This week' },
            { id: 'month', label: 'This month' },
          ]}
        />
      </PageFilters>

      <PageBody className="space-y-4">
        {/*
         * KPIs first, then what is blocked, then the work itself. The lifecycle
         * strip used to open the page: it is an orientation device you need
         * once, and it was costing the top of every visit thereafter. It now
         * sits at the bottom, where someone looking for "where does this go
         * next" can still find it.
         */}
        <SectionTitle>Performance</SectionTitle>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Open requirements"
            value={openReqs.length}
            tone="neutral"
            icon={<MessagesSquare aria-hidden="true" />}
            tileTone="accent"
            sublabel="In discussion, analysis or build"
            spark={TRENDS.open}
          />
          <StatTile
            label="Awaiting your decision"
            value={pendingGates.length}
            tone={pendingGates.length > 0 ? 'danger' : 'ok'}
            icon={<BadgeCheck aria-hidden="true" />}
            tileTone="warn"
            sublabel={`${blockedGates.length} blocked by policy`}
            spark={TRENDS.decisions}
          />
          <StatTile
            label="Evidence health"
            value={`${verified}/${verified + asserted}`}
            tone={asserted > 0 ? 'warn' : 'ok'}
            sublabel={`${verified} verified · ${asserted} asserted only`}
            icon={<ShieldCheck aria-hidden="true" />}
            tileTone="ok"
            spark={TRENDS.evidence}
          />
          <StatTile
            label="Sources needing attention"
            value={brokenSources.length}
            tone={brokenSources.length > 0 ? 'danger' : 'ok'}
            icon={<Database aria-hidden="true" />}
            tileTone="purple"
            sublabel="Stale or disconnected"
            spark={TRENDS.sources}
          />
        </div>

        {/* Attention queue — the highest-value thing on the page */}
        {(blockedGates.length > 0 || failingRuns.length > 0 || brokenSources.length > 0) && (
          <Card>
            <CardHeader
              title="Needs attention"
              description="Blockers preventing changes from completing right now."
              icon={<AlertTriangle aria-hidden="true" />}
              tone="danger"
            />
            <ul className="divide-y divide-[var(--border-subtle)]">
              {blockedGates.slice(0, 2).map((g) => (
                <li
                  key={g.id}
                  className="flex flex-col gap-2 p-3.5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-[var(--text-primary)]">
                      <Badge tone="danger">Gate blocked</Badge>
                      {g.name}
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
                      {g.blockedBy[0]}
                    </p>
                  </div>
                  <Link to="/approvals" className="shrink-0">
                    <Button variant="secondary" size="sm">
                      Review
                    </Button>
                  </Link>
                </li>
              ))}
              {failingRuns.slice(0, 2).map((r) => (
                <li
                  key={r.id}
                  className="flex flex-col gap-2 p-3.5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-[var(--text-primary)]">
                      <Badge tone={r.status === 'failed' ? 'danger' : 'warn'}>
                        {r.status === 'failed' ? 'Test failed' : 'Test flaky'}
                      </Badge>
                      <span className="font-mono text-xs text-[var(--text-tertiary)]">{r.ref}</span>
                      <span className="truncate">{r.title}</span>
                    </p>
                    {r.failureReason ? (
                      <p className="mt-0.5 truncate text-xs text-[var(--text-tertiary)]">
                        {r.failureReason}
                      </p>
                    ) : null}
                  </div>
                  <Link to="/evidence" className="shrink-0">
                    <Button variant="secondary" size="sm">
                      Inspect
                    </Button>
                  </Link>
                </li>
              ))}
              {brokenSources.slice(0, 1).map((s) => (
                <li
                  key={s.id}
                  className="flex flex-col gap-2 p-3.5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-[var(--text-primary)]">
                      <Badge tone={s.status === 'error' ? 'danger' : 'warn'}>
                        {s.status === 'error' ? 'Source error' : 'Source stale'}
                      </Badge>
                      {s.name}
                    </p>
                    <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
                      {s.error ??
                        `Last synced ${relativeTime(s.lastSyncedAt)} — analyses may be out of date.`}
                    </p>
                  </div>
                  <Link to="/sources" className="shrink-0">
                    <Button variant="secondary" size="sm">
                      Fix
                    </Button>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}

        <SectionTitle>Work in flight</SectionTitle>
        <div className="grid gap-4 lg:grid-cols-3">
          {/* min-w-0 so long requirement titles cannot force the grid child wider than the viewport */}
          <Card className="min-w-0 lg:col-span-2">
            <CardHeader
              title="Active requirements"
              actions={
                <Link to="/requirements">
                  <Button variant="ghost" size="sm">
                    View all
                    <ArrowRight className="size-3.5" aria-hidden="true" />
                  </Button>
                </Link>
              }
            />
            {reqLoading ? (
              <div className="space-y-2 p-4">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : (
              <ul className="divide-y divide-[var(--border-subtle)]">
                {openReqs.slice(0, 5).map((r) => (
                  <li key={r.id}>
                    <Link
                      to={`/requirements/${r.id}`}
                      className="flex items-center justify-between gap-3 p-3.5 transition-colors duration-200 hover:bg-[var(--bg-hover)]"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-baseline gap-x-1.5">
                          <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                            {r.ref}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--text-primary)]">
                            {r.title}
                          </span>
                        </p>
                        <p className="mt-1 flex flex-wrap items-center gap-1.5">
                          <StageBadge stage={r.stage} />
                          <RiskBadge risk={r.riskLevel} />
                          <span className="text-[11px] text-[var(--text-tertiary)]">
                            {r.requestedBy} · {relativeTime(r.updatedAt)}
                          </span>
                        </p>
                      </div>
                      <span className="tabular shrink-0 text-xs text-[var(--text-tertiary)]">
                        {formatUsd(r.actualCostUsd, { precise: true })}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* overflow-hidden so the grey body is clipped by the card radius
              rather than squaring off its corners. */}
          <Card className="overflow-hidden">
            <CardHeader
              title="This month"
              icon={<Activity className="size-4" aria-hidden="true" />}
            />
            <div className="space-y-3 bg-[var(--bg-surface-2)] p-4">
              <MiniStat label="Changes signed off" value="14" tone="ok" />
              <MiniStat
                label="Change failure rate"
                value="4.2%"
                tone="ok"
                hint="vs 6.8% baseline"
              />
              <MiniStat label="Median lead time" value="71h" tone="ok" hint="vs 168h baseline" />
              <MiniStat label="Model spend" value={formatUsd(1381.84)} tone="info" />
              <MiniStat
                label="Asserted-only evidence"
                value={String(asserted)}
                tone="warn"
                hint="Cannot satisfy a gate"
              />
            </div>
            <div className="border-t border-[var(--border-subtle)] p-3">
              <Link to="/analytics">
                <Button variant="secondary" size="sm" className="w-full justify-center">
                  Full analytics
                  <ArrowRight className="size-3.5" aria-hidden="true" />
                </Button>
              </Link>
            </div>
          </Card>
        </div>

      </PageBody>
    </>
  )
}

function MiniStat({
  label,
  value,
  tone,
  hint,
}: {
  label: string
  value: string
  tone: 'ok' | 'warn' | 'info'
  hint?: string
}) {
  const colors = {
    ok: 'text-[var(--ok)]',
    warn: 'text-[var(--warn)]',
    info: 'text-[var(--info)]',
  }
  return (
    <div className="flex items-baseline justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs text-[var(--text-secondary)]">{label}</p>
        {hint ? <p className="text-[10px] text-[var(--text-tertiary)]">{hint}</p> : null}
      </div>
      <span className={`tabular shrink-0 text-sm font-semibold ${colors[tone]}`}>{value}</span>
    </div>
  )
}

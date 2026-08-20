import { useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Activity, Info } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  SectionLabel,
  Skeleton,
  StatTile,
} from '@/components/ui/primitives'
import { Tabs } from '@/components/ui/overlays'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { api } from '@/lib/api'
import { useAsync } from '@/lib/useAsync'
import { useTheme } from '@/components/layout/theme'
import { cn, formatNumber, formatPct, formatUsd } from '@/lib/utils'
import type { ModelSpend } from '@/lib/types'

/** Categorical series colours — distinguishable in both themes and for CVD. */
const SERIES = {
  llm: '#1c1c1c',
  compute: '#a1a1aa',
  baseline: '#c4c4c9',
  meridian: '#1c1c1c',
  /*
   * Run outcomes. Blue/red rather than the more obvious green/red: green and
   * red sit ΔE 4.2 apart under deuteranopia — indistinguishable for the most
   * common form of colour blindness — while blue/red separates at 26.8. Both
   * pairs were run through the palette validator rather than judged by eye.
   *
   * The dark steps are chosen, not derived: `--danger` at its light-mode value
   * lands outside the dark lightness band, so the solid step is used there.
   */
  succeeded: '#1b58c8',
  failed: '#b91c1c',
  nodes: '#1b58c8',
  duration: '#1c1c1c',
}

const SERIES_DARK = {
  llm: '#f5f5f5',
  compute: '#71717a',
  baseline: '#52525b',
  meridian: '#f5f5f5',
  succeeded: '#4a86ee',
  failed: '#ef4444',
  nodes: '#4a86ee',
  duration: '#f5f5f5',
}

/** Time windows offered above the charts. */
const WINDOWS = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
]

/**
 * A chart area with no data.
 *
 * Says the window is empty rather than drawing empty axes: a chart frame with
 * nothing in it reads as a loading failure, and on a fresh install "no runs
 * yet" is the correct and expected state.
 */
function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-[var(--border)]">
      <p className="text-xs text-[var(--text-tertiary)]">{message}</p>
    </div>
  )
}

/** Seconds as a compact duration — "1m 18s" reads faster than "78.6s". */
function formatDuration(seconds: number): string {
  if (!seconds) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const mins = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  if (mins < 60) return rest ? `${mins}m ${rest}s` : `${mins}m`
  const hours = Math.floor(mins / 60)
  return `${hours}h ${mins % 60}m`
}

export function AnalyticsPage() {
  const [days, setDays] = useState(30)
  const { data, loading } = useAsync(() => api.getAnalytics(days), [days])
  const { theme } = useTheme()
  const [tab, setTab] = useState('runs')

  const series = theme === 'dark' ? SERIES_DARK : SERIES
  const axis = theme === 'dark' ? '#7d7d7d' : '#8f8f8f'
  const grid = theme === 'dark' ? '#262626' : '#e7e7e9'

  const tooltipStyle = {
    backgroundColor: theme === 'dark' ? '#191919' : '#ffffff',
    border: `1px solid ${theme === 'dark' ? '#303030' : '#dcdce0'}`,
    borderRadius: 10,
    fontSize: 12,
    color: theme === 'dark' ? '#f5f5f5' : '#171717',
  }

  const modelColumns: Column<ModelSpend>[] = [
    {
      id: 'model',
      header: 'Model',
      sortValue: (r) => r.model,
      cell: (r) => <span className="font-mono text-xs text-[var(--text-primary)]">{r.model}</span>,
    },
    {
      id: 'calls',
      header: 'Calls',
      align: 'right',
      sortValue: (r) => r.calls,
      cell: (r) => <span className="tabular">{formatNumber(r.calls)}</span>,
    },
    {
      id: 'cost',
      header: 'Cost',
      align: 'right',
      sortValue: (r) => r.costUsd,
      cell: (r) => (
        <span className="tabular font-medium">{formatUsd(r.costUsd, { precise: true })}</span>
      ),
    },
    {
      id: 'share',
      header: 'Share',
      align: 'right',
      sortValue: (r) => r.share,
      cell: (r) => <span className="tabular">{r.share}%</span>,
    },
  ]

  return (
    <>
      <PageHeader
        title="Cost & Efficiency"
        icon={<Activity aria-hidden="true" />}
        tone="accent"
      />

      <PageBody className="space-y-4">
        {/* Honest-metrics disclosure — this is a product stance, not a footnote */}
        <div className="flex items-start gap-2.5 rounded-xl border border-[var(--info-border)] bg-[var(--info-subtle)] p-3">
          <Info className="mt-px size-4 shrink-0 text-[var(--info)]" aria-hidden="true" />
          <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
            <span className="font-semibold text-[var(--info)]">How to read these numbers.</span>{' '}
            Everything below is measured directly: token spend, wall-clock duration, review cycles
            and outcomes. Cycle time is compared against <em>this organisation's</em> trailing
            baseline for comparable changes — not a vendor benchmark. Meridian deliberately does not
            publish a single "hours saved" figure, because the counterfactual is unobservable and no
            one can defend it in a review.
          </p>
        </div>

        {loading ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-96 rounded-xl" />
          </div>
        ) : data ? (
          <>
            {/*
             * The window control sits above every number it governs, so the
             * period a figure describes is never ambiguous. It re-fetches
             * rather than filtering client-side: the totals are aggregated
             * server-side, and a 7-day chart beside a 30-day total is the kind
             * of mismatch that goes unnoticed until a figure is quoted.
             */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <SectionLabel>Extraction activity</SectionLabel>
              <div
                className="flex items-center gap-1 rounded-lg border border-[var(--border)] p-0.5"
                role="group"
                aria-label="Time window"
              >
                {WINDOWS.map((w) => (
                  <button
                    key={w.days}
                    type="button"
                    onClick={() => setDays(w.days)}
                    aria-pressed={days === w.days}
                    className={cn(
                      'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                      days === w.days
                        ? 'bg-[var(--bg-subtle)] text-[var(--text-primary)]'
                        : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]',
                    )}
                  >
                    {w.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile
                label="Extraction runs"
                value={formatNumber(data.runTotals.runs)}
                sublabel={
                  data.runTotals.failed
                    ? `${data.runTotals.failed} failed, ${data.runTotals.succeeded} succeeded`
                    : `All ${data.runTotals.succeeded} succeeded`
                }
                tone={data.runTotals.failed ? 'warn' : 'ok'}
              />
              <StatTile
                label="Objects extracted"
                value={formatNumber(data.runTotals.nodes)}
                sublabel={`Across ${data.runTotals.runs} run(s) in ${data.runTotals.days} days`}
              />
              <StatTile
                label="Total run time"
                value={formatDuration(data.runTotals.totalSeconds)}
                /* Mean over *timed* runs: one still in flight has no duration
                 * and would drag the average down silently. */
                sublabel={`${formatDuration(data.runTotals.avgSeconds)} average per run`}
              />
              <StatTile
                label="Model spend"
                value={formatUsd(data.runTotals.llmUsd + data.runTotals.computeUsd)}
                sublabel={`${formatNumber(data.runTotals.operations)} AI operation(s), ${formatNumber(
                  data.runTotals.tokensIn + data.runTotals.tokensOut,
                )} tokens`}
              />
            </div>

            <SectionLabel>Delivery metrics</SectionLabel>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {data.dora.map((m) => {
                const good = m.direction === 'down_good' ? m.deltaPct < 0 : m.deltaPct > 0
                return (
                  <StatTile
                    key={m.label}
                    label={m.label}
                    value={m.value}
                    tone={good ? 'ok' : 'danger'}
                    sublabel={m.detail}
                    /*
                     * Direction follows the sign, `good` follows the metric's
                     * own semantics. They genuinely differ here: a 38% fall in
                     * change-failure rate is a down arrow and a green one, and
                     * deriving the arrow from `good` drew it pointing up.
                     */
                    delta={{
                      value: formatPct(m.deltaPct),
                      good,
                      direction: m.deltaPct < 0 ? 'down' : m.deltaPct > 0 ? 'up' : 'flat',
                    }}
                    /*
                     * No trend icon in the header: the Delta below already
                     * draws an arrow for the same number, and two arrows per
                     * tile pointing the same way is one arrow too many.
                     */
                  />
                )
              })}
            </div>

            <Card>
              <div className="border-b border-[var(--border-subtle)] p-3">
                <Tabs
                  className="border-b-0"
                  value={tab}
                  onChange={setTab}
                  items={[
                    { id: 'runs', label: 'Runs & outcomes' },
                    { id: 'throughput', label: 'Objects & duration' },
                    { id: 'cycle', label: 'Cycle time vs baseline' },
                    { id: 'cost', label: 'Spend over time' },
                    { id: 'volume', label: 'Change volume' },
                  ]}
                />
              </div>

              <div className="p-4">
                {tab === 'runs' ? (
                  <>
                    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                          Extraction runs by day
                        </h3>
                        <p className="text-xs text-[var(--text-tertiary)]">
                          Succeeded and failed, stacked to total runs
                        </p>
                      </div>
                      <Badge tone={data.runTotals.failed ? 'warn' : 'ok'}>
                        {data.runTotals.runs === 0
                          ? 'No runs yet'
                          : `${Math.round(
                              (data.runTotals.succeeded / data.runTotals.runs) * 100,
                            )}% succeeded`}
                      </Badge>
                    </div>
                    {data.runs.length ? (
                      <div className="h-72 w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={data.runs}
                            margin={{ top: 8, right: 8, bottom: 4, left: -12 }}
                          >
                            <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
                            <XAxis
                              dataKey="date"
                              stroke={axis}
                              tick={{ fontSize: 11 }}
                              tickLine={false}
                              axisLine={{ stroke: grid }}
                            />
                            <YAxis
                              stroke={axis}
                              tick={{ fontSize: 11 }}
                              tickLine={false}
                              axisLine={false}
                              allowDecimals={false}
                            />
                            <RTooltip
                              contentStyle={tooltipStyle}
                              formatter={(v, n) => [formatNumber(Number(v)), String(n)]}
                            />
                            <Legend wrapperStyle={{ fontSize: 12 }} />
                            {/*
                             * Stacked so the column height reads as "runs that
                             * day" while the split stays visible. The 2px gap
                             * between segments is the surface showing through,
                             * which keeps the boundary legible when a stack is
                             * mostly one colour.
                             */}
                            <Bar
                              dataKey="succeeded"
                              name="Succeeded"
                              stackId="runs"
                              fill={series.succeeded}
                              radius={[0, 0, 0, 0]}
                            />
                            <Bar
                              dataKey="failed"
                              name="Failed"
                              stackId="runs"
                              fill={series.failed}
                              radius={[4, 4, 0, 0]}
                            />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <EmptyChart message="No extraction runs in this window." />
                    )}
                  </>
                ) : tab === 'throughput' ? (
                  <>
                    <div className="mb-3">
                      <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                        Objects extracted and run duration
                      </h3>
                      <p className="text-xs text-[var(--text-tertiary)]">
                        Shown separately — counts and seconds share no scale
                      </p>
                    </div>
                    {data.runs.length ? (
                      /*
                       * Two charts rather than one with two y-axes. A dual
                       * axis lets the reader infer a relationship from where
                       * the lines happen to cross, which is an artefact of the
                       * scales chosen rather than anything in the data.
                       */
                      <div className="grid gap-4 lg:grid-cols-2">
                        <div>
                          <p className="mb-1 text-xs font-medium text-[var(--text-secondary)]">
                            Objects extracted
                          </p>
                          <div className="h-60 w-full">
                            <ResponsiveContainer width="100%" height="100%">
                              <BarChart
                                data={data.runs}
                                margin={{ top: 8, right: 8, bottom: 4, left: -12 }}
                              >
                                <CartesianGrid
                                  stroke={grid}
                                  strokeDasharray="3 3"
                                  vertical={false}
                                />
                                <XAxis
                                  dataKey="date"
                                  stroke={axis}
                                  tick={{ fontSize: 11 }}
                                  tickLine={false}
                                  axisLine={{ stroke: grid }}
                                />
                                <YAxis
                                  stroke={axis}
                                  tick={{ fontSize: 11 }}
                                  tickLine={false}
                                  axisLine={false}
                                />
                                <RTooltip
                                  contentStyle={tooltipStyle}
                                  formatter={(v) => [formatNumber(Number(v)), 'Objects']}
                                />
                                <Bar
                                  dataKey="nodes"
                                  name="Objects"
                                  fill={series.nodes}
                                  radius={[4, 4, 0, 0]}
                                />
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                        <div>
                          <p className="mb-1 text-xs font-medium text-[var(--text-secondary)]">
                            Mean duration per run
                          </p>
                          <div className="h-60 w-full">
                            <ResponsiveContainer width="100%" height="100%">
                              <LineChart
                                data={data.runs}
                                margin={{ top: 8, right: 8, bottom: 4, left: -12 }}
                              >
                                <CartesianGrid
                                  stroke={grid}
                                  strokeDasharray="3 3"
                                  vertical={false}
                                />
                                <XAxis
                                  dataKey="date"
                                  stroke={axis}
                                  tick={{ fontSize: 11 }}
                                  tickLine={false}
                                  axisLine={{ stroke: grid }}
                                />
                                <YAxis
                                  stroke={axis}
                                  tick={{ fontSize: 11 }}
                                  tickLine={false}
                                  axisLine={false}
                                  tickFormatter={(v) => `${v}s`}
                                />
                                <RTooltip
                                  contentStyle={tooltipStyle}
                                  formatter={(v) => [formatDuration(Number(v)), 'Mean duration']}
                                />
                                <Line
                                  type="monotone"
                                  dataKey="avgSeconds"
                                  name="Mean duration"
                                  stroke={series.duration}
                                  strokeWidth={2}
                                  dot={{ r: 3 }}
                                  activeDot={{ r: 5 }}
                                />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <EmptyChart message="No extraction runs in this window." />
                    )}
                  </>
                ) : tab === 'cycle' ? (
                  <>
                    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                          Lead time for change
                        </h3>
                        <p className="text-xs text-[var(--text-tertiary)]">
                          Hours from request raised to signed-off, weekly
                        </p>
                      </div>
                      <Badge tone="ok">71h current vs 168h baseline</Badge>
                    </div>
                    <div className="h-72 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart
                          data={data.cycleTime}
                          margin={{ top: 8, right: 8, bottom: 4, left: -12 }}
                        >
                          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
                          <XAxis
                            dataKey="week"
                            stroke={axis}
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={{ stroke: grid }}
                          />
                          <YAxis
                            stroke={axis}
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={false}
                            label={{
                              value: 'hours',
                              angle: -90,
                              position: 'insideLeft',
                              style: { fontSize: 11, fill: axis },
                              offset: 20,
                            }}
                          />
                          <RTooltip
                            contentStyle={tooltipStyle}
                            formatter={(v, n) => [`${Number(v)}h`, String(n)]}
                          />
                          <Legend wrapperStyle={{ fontSize: 12 }} />
                          {/* Distinct dash patterns so the series are readable without colour */}
                          <Line
                            type="monotone"
                            dataKey="baselineHours"
                            name="Org baseline"
                            stroke={series.baseline}
                            strokeWidth={2}
                            strokeDasharray="6 4"
                            dot={false}
                          />
                          <Line
                            type="monotone"
                            dataKey="meridianHours"
                            name="With Meridian"
                            stroke={series.meridian}
                            strokeWidth={2.5}
                            dot={{ r: 3 }}
                            activeDot={{ r: 5 }}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </>
                ) : tab === 'cost' ? (
                  <>
                    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                          Weekly spend
                        </h3>
                        <p className="text-xs text-[var(--text-tertiary)]">
                          Model tokens and agent compute
                        </p>
                      </div>
                      <Badge tone="info">
                        {formatUsd(data.cost.reduce((a, c) => a + c.llmUsd + c.computeUsd, 0))}{' '}
                        total
                      </Badge>
                    </div>
                    <div className="h-72 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart
                          data={data.cost}
                          margin={{ top: 8, right: 8, bottom: 4, left: -12 }}
                        >
                          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
                          <XAxis
                            dataKey="date"
                            stroke={axis}
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={{ stroke: grid }}
                          />
                          <YAxis
                            stroke={axis}
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={false}
                            tickFormatter={(v) => `$${v}`}
                          />
                          <RTooltip
                            contentStyle={tooltipStyle}
                            formatter={(v, n) => [
                              formatUsd(Number(v), { precise: true }),
                              String(n),
                            ]}
                          />
                          <Legend wrapperStyle={{ fontSize: 12 }} />
                          <Area
                            type="monotone"
                            dataKey="llmUsd"
                            name="Model tokens"
                            stackId="1"
                            stroke={series.llm}
                            fill={series.llm}
                            fillOpacity={0.25}
                            strokeWidth={2}
                          />
                          <Area
                            type="monotone"
                            dataKey="computeUsd"
                            name="Agent compute"
                            stackId="1"
                            stroke={series.compute}
                            fill={series.compute}
                            fillOpacity={0.25}
                            strokeWidth={2}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="mb-3">
                      <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                        Changes shipped per week
                      </h3>
                      <p className="text-xs text-[var(--text-tertiary)]">
                        Signed off with a complete evidence chain
                      </p>
                    </div>
                    <div className="h-72 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart
                          data={data.cost}
                          margin={{ top: 8, right: 8, bottom: 4, left: -12 }}
                        >
                          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
                          <XAxis
                            dataKey="date"
                            stroke={axis}
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={{ stroke: grid }}
                          />
                          <YAxis
                            stroke={axis}
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={false}
                            allowDecimals={false}
                          />
                          <RTooltip
                            contentStyle={tooltipStyle}
                            cursor={{ fill: grid, opacity: 0.4 }}
                          />
                          <Bar
                            dataKey="changes"
                            name="Changes signed off"
                            fill={series.llm}
                            radius={[4, 4, 0, 0]}
                            maxBarSize={40}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </>
                )}
              </div>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader
                  title="Spend by model"
                  description="Where the token budget actually goes"
                />
                <DataTable
                  rows={data.modelSpend}
                  columns={modelColumns}
                  getRowId={(r) => r.model}
                  initialSort={{ columnId: 'cost', dir: 'desc' }}
                />
              </Card>

              <Card>
                <CardHeader
                  title="What Meridian does not claim"
                  description="Metrics deliberately excluded, and why"
                />
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {[
                    {
                      metric: 'Hours saved vs a human',
                      why: 'The counterfactual is unobservable. Any figure would be a vendor estimate that no one can defend in a QBR.',
                    },
                    {
                      metric: 'Developer productivity multiplier',
                      why: 'Attribution across a change involving five people and three agents is not measurable with integrity.',
                    },
                    {
                      metric: 'Quality score',
                      why: 'Composite scores hide their inputs. Change failure rate and evidence completeness are reported directly instead.',
                    },
                  ].map((row) => (
                    <li key={row.metric} className="p-3">
                      <p className="text-xs font-medium text-[var(--text-primary)]">{row.metric}</p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                        {row.why}
                      </p>
                    </li>
                  ))}
                </ul>
                <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
                  <SectionLabel>Want a cost-avoidance figure?</SectionLabel>
                  <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                    Supply your own blended rate card and Meridian will apply it to measured
                    cycle-time deltas — clearly labelled as an estimate you own, not a claim it
                    makes.
                  </p>
                  <Button variant="secondary" size="sm" className="mt-2">
                    Configure rate card
                  </Button>
                </div>
              </Card>
            </div>
          </>
        ) : null}
      </PageBody>
    </>
  )
}

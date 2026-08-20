import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  Download,
  FlaskConical,
  LogIn,
  LogOut,
  Send,
  ShieldAlert,
  Target,
  Wallet,
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
  Skeleton,
} from '@/components/ui/primitives'
import { Modal, useToast } from '@/components/ui/overlays'
import {
  CriterionIcon,
  NODE_KIND_META,
  TEST_LEVEL_LABEL,
  TEST_TYPE_LABEL,
} from '@/components/domain/status'
import { StlcRail } from '@/components/domain/StlcRail'
import {
  DocCriteria,
  DocFacts,
  DocList,
  DocSection,
  DocumentPreview,
} from '@/components/domain/DocumentPreview'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { criteriaUnmet, useStlc } from '@/lib/useStlc'
import { cn, formatUsd, relativeTime } from '@/lib/utils'
import type { Criterion, GraphNode, TestPlan } from '@/lib/types'

export function TestPlanPage() {
  const { plan: loaded, phases, subject, loading } = useStlc()
  const { items: graph } = useAsyncList(() => api.getGraph().then((g) => g.nodes), [])
  const [plan, setPlan] = useState<TestPlan | null>(null)
  const [approveOpen, setApproveOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const { push } = useToast()

  // Local state shadows the fetched plan so approving updates in place.
  const current = plan ?? loaded ?? null

  const nodeById = useMemo(() => new Map(graph.map((n: GraphNode) => [n.id, n])), [graph])

  const entryBlockers = current ? criteriaUnmet(current.entryCriteria) : 0
  const totalCriteriaUnmet = current
    ? criteriaUnmet(current.entryCriteria) + criteriaUnmet(current.exitCriteria)
    : 0

  async function approve() {
    if (!current) return
    setApproveOpen(false)
    const next = await api.setTestPlanState(current.id, 'approved')
    if (next) setPlan(next)
    push({
      tone: 'ok',
      title: 'Test plan approved',
      description: 'Recorded in the audit chain. Test case development can proceed.',
    })
  }

  if (loading && !current) {
    return (
      <>
        <PageHeader title="Test plan" icon={<FlaskConical aria-hidden="true" />} tone="accent" />
        <PageBody className="space-y-4">
          <Skeleton className="h-[76px] w-full rounded-xl" />
          <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
            <Skeleton className="h-[520px] w-full rounded-xl" />
            <Skeleton className="h-[520px] w-full rounded-xl" />
          </div>
        </PageBody>
      </>
    )
  }

  if (!current) {
    return (
      <>
        <PageHeader title="Test plan" icon={<FlaskConical aria-hidden="true" />} tone="accent" />
        <PageBody>
          <Card>
            <EmptyState
              icon={<ClipboardList className="size-5" aria-hidden="true" />}
              title="No test plan for this requirement yet"
              description="A plan is generated from the agreed impact analysis. Agree the analysis first, then generate the plan from it."
              action={
                <Link to="/impact">
                  <Button variant="primary">Go to impact analysis</Button>
                </Link>
              }
            />
          </Card>
        </PageBody>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Test plan"
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
              Export
            </Button>
            {current.state === 'approved' ? (
              <Link to="/test-cases">
                <Button
                  variant="primary"
                  icon={<ArrowRight className="size-4" aria-hidden="true" />}
                >
                  Go to test cases
                </Button>
              </Link>
            ) : (
              <Button
                variant="primary"
                icon={<CheckCircle2 className="size-4" aria-hidden="true" />}
                onClick={() => setApproveOpen(true)}
              >
                Approve plan
              </Button>
            )}
          </>
        }
      />

      <PageBody className="space-y-4">
        <PlanSummaryBar
          plan={current}
          entryBlockers={entryBlockers}
          uncoveredLabels={current.uncoveredNodeIds.map((id) => nodeById.get(id)?.label ?? id)}
        />

        <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
          <div className="min-w-0 space-y-4">
            {/*
             * Objective and scope answer the same question — what this cycle
             * covers — so they are one card. The objective reads as the lead
             * paragraph and the two scope lists sit under it as its detail.
             */}
            <Card>
              <CardHeader
                title="Objective and scope"
                description="What this cycle sets out to prove, and the boundaries it will not cross."
                icon={<Target aria-hidden="true" />}
              />
              <div className="p-4">
                <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">
                  {current.objective}
                </p>
                <div className="mt-4 grid gap-4 border-t border-[var(--border-subtle)] pt-4 sm:grid-cols-2">
                  <ScopeList label="In scope" tone="ok" items={current.scopeIn} />
                  <ScopeList label="Out of scope" tone="neutral" items={current.scopeOut} />
                </div>
              </div>
            </Card>

            {/*
             * Entry and exit criteria are one gate mechanism seen from both
             * ends, so they share a card and are split by a hairline. Two
             * cards implied they were unrelated checklists.
             */}
            <Card>
              <CardHeader
                title="Entry and exit criteria"
                description="Conditions that must hold before testing may begin, and the ones closure is evaluated against."
                icon={<LogIn aria-hidden="true" />}
                actions={
                  totalCriteriaUnmet > 0 ? (
                    <Badge tone="warn">{totalCriteriaUnmet} unmet</Badge>
                  ) : (
                    <Badge tone="ok">All met</Badge>
                  )
                }
              />
              <div className="grid sm:grid-cols-2 sm:divide-x sm:divide-[var(--border-subtle)]">
                <CriteriaColumn
                  title="Entry"
                  hint="Before testing may begin"
                  icon={<LogIn className="size-3.5" aria-hidden="true" />}
                  criteria={current.entryCriteria}
                />
                <CriteriaColumn
                  title="Exit"
                  hint="Evaluated at closure, never declared"
                  icon={<LogOut className="size-3.5" aria-hidden="true" />}
                  criteria={current.exitCriteria}
                />
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Risks accepted by this plan"
                description="Stated up front so nobody discovers them at sign-off."
                icon={<ShieldAlert aria-hidden="true" />}
              />
              <ul className="divide-y divide-[var(--border-subtle)]">
                {current.risks.map((r) => (
                  <li key={r.id} className="p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="min-w-0 flex-1 text-[13px] leading-relaxed font-medium text-[var(--text-primary)]">
                        {r.risk}
                      </p>
                      <Badge
                        tone={
                          r.likelihood === 'high'
                            ? 'danger'
                            : r.likelihood === 'medium'
                              ? 'warn'
                              : 'neutral'
                        }
                      >
                        {r.likelihood} likelihood
                      </Badge>
                    </div>
                    <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                      <span className="font-medium text-[var(--text-tertiary)]">Mitigation — </span>
                      {r.mitigation}
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          {/*
           * Right rail: one card, three sections.
           *
           * Strategy, coverage and provenance were three stacked boxes of
           * five to eight rows each — all reference detail about the same
           * plan, none of them a separate object. Hairline-separated
           * sections inside one card carry the same grouping without the
           * three borders, three headers and two gaps.
           */}
          <aside>
            <Card className="divide-y divide-[var(--border-subtle)]">
              <CardHeader title="Plan detail" icon={<FlaskConical aria-hidden="true" />} />

              <div className="space-y-4 p-4">
                <div>
                  <SectionLabel>Test levels</SectionLabel>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {current.levels.map((l) => (
                      <Badge key={l} tone="info">
                        {TEST_LEVEL_LABEL[l]}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div>
                  <SectionLabel>Test types</SectionLabel>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {current.types.map((t) => (
                      <Badge key={t} tone="neutral">
                        {TEST_TYPE_LABEL[t]}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between gap-2 px-4 pt-3.5 pb-1.5">
                  <SectionLabel>Impacted nodes</SectionLabel>
                  <span className="numeral text-[11px] text-[var(--text-tertiary)]">
                    {current.coveredNodeIds.length}/
                    {current.coveredNodeIds.length + current.uncoveredNodeIds.length} covered
                  </span>
                </div>
                <ul>
                  {current.coveredNodeIds.map((id) => (
                    <NodeRow key={id} id={id} node={nodeById.get(id)} covered />
                  ))}
                  {current.uncoveredNodeIds.map((id) => (
                    <NodeRow key={id} id={id} node={nodeById.get(id)} covered={false} />
                  ))}
                </ul>
              </div>

              <div className="p-4">
                <SectionLabel>Provenance</SectionLabel>
                <dl className="mt-2 space-y-2.5">
                  {[
                    ['Author', current.author],
                    ['Model', current.model],
                    ['Created', relativeTime(current.createdAt)],
                    ['Last updated', relativeTime(current.updatedAt)],
                    [
                      'Approved',
                      current.approvedBy
                        ? `${current.approvedBy} · ${relativeTime(current.approvedAt)}`
                        : 'Not yet approved',
                    ],
                  ].map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-3">
                      <dt className="text-xs text-[var(--text-tertiary)]">{k}</dt>
                      <dd className="text-right text-xs font-medium text-[var(--text-primary)]">
                        {v}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </Card>
          </aside>
        </div>
      </PageBody>

      <Modal
        open={approveOpen}
        onClose={() => setApproveOpen(false)}
        title="Approve this test plan?"
        description="Approving records you as accountable for the scope, the risks accepted, and the exit criteria this cycle will be judged against."
        footer={
          <>
            <Button variant="ghost" onClick={() => setApproveOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              icon={<Send className="size-4" aria-hidden="true" />}
              onClick={approve}
            >
              Approve plan
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {current.uncoveredNodeIds.length > 0 ? (
            <div className="flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
              <AlertTriangle
                className="mt-px size-4 shrink-0 text-[var(--warn)]"
                aria-hidden="true"
              />
              <div>
                <p className="text-xs font-semibold text-[var(--warn)]">
                  {current.uncoveredNodeIds.length} impacted node has no planned coverage
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                  {current.uncoveredNodeIds.map((id) => nodeById.get(id)?.label ?? id).join(', ')}{' '}
                  will not be exercised by this plan. Approving accepts that gap.
                </p>
              </div>
            </div>
          ) : null}
          <ul className="space-y-1.5 text-[13px] text-[var(--text-secondary)]">
            <li>
              · {current.estimatedCases} cases across {current.levels.length} levels
            </li>
            <li>· {current.risks.length} risks explicitly accepted</li>
            <li>· {current.exitCriteria.length} exit criteria will gate closure</li>
          </ul>
        </div>
      </Modal>

      <DocumentPreview
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title={current.title}
        subtitle={`${current.ref} · version ${current.version} · ${current.requirementRef}`}
        filename={`${current.ref}-v${current.version}-test-plan.pdf`}
      >
        <PlanDocument plan={current} nodeById={nodeById} />
      </DocumentPreview>
    </>
  )
}

/**
 * The plan rendered as a document.
 *
 * It states the same coverage gaps, risks and unmet criteria the screen does.
 * An export that quietly dropped them would turn a governance record into a
 * marketing summary.
 */
function PlanDocument({ plan, nodeById }: { plan: TestPlan; nodeById: Map<string, GraphNode> }) {
  const label = (id: string) => nodeById.get(id)?.label ?? id

  return (
    <>
      <DocSection title="Document control">
        <DocFacts
          facts={[
            ['Reference', plan.ref],
            ['Version', `v${plan.version}`],
            ['Status', plan.state === 'approved' ? 'Approved' : 'In review'],
            ['Author', plan.author],
            [
              'Approved by',
              plan.approvedBy ? `${plan.approvedBy} · ${relativeTime(plan.approvedAt)}` : '—',
            ],
            ['Generated', relativeTime(plan.createdAt)],
          ]}
        />
      </DocSection>

      <DocSection title="Objective">
        <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">{plan.objective}</p>
      </DocSection>

      <DocSection title="In scope">
        <DocList items={plan.scopeIn} />
      </DocSection>

      <DocSection title="Out of scope">
        <DocList items={plan.scopeOut} />
      </DocSection>

      <DocSection title="Strategy">
        <DocFacts
          facts={[
            ['Levels', plan.levels.map((l) => TEST_LEVEL_LABEL[l]).join(', ')],
            ['Types', plan.types.map((t) => TEST_TYPE_LABEL[t]).join(', ')],
            ['Planned cases', String(plan.estimatedCases)],
            ['Estimated execution', `${plan.estimatedDurationHours} hours`],
          ]}
        />
      </DocSection>

      <DocSection title="Coverage">
        <DocFacts
          facts={[
            ['Covered nodes', plan.coveredNodeIds.map(label).join(', ') || 'None'],
            [
              'Not covered',
              plan.uncoveredNodeIds.length > 0 ? (
                <span className="text-[var(--warn)]">
                  {plan.uncoveredNodeIds.map(label).join(', ')}
                </span>
              ) : (
                'None'
              ),
            ],
          ]}
        />
      </DocSection>

      <DocSection title="Entry criteria">
        <DocCriteria items={plan.entryCriteria} />
      </DocSection>

      <DocSection title="Exit criteria">
        <DocCriteria items={plan.exitCriteria} />
      </DocSection>

      <DocSection title="Accepted risks">
        <ul className="space-y-3">
          {plan.risks.map((r) => (
            <li key={r.id}>
              <p className="text-[13px] leading-snug font-medium text-[var(--text-primary)]">
                {r.risk}
              </p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                Likelihood: {r.likelihood} · Mitigation: {r.mitigation}
              </p>
            </li>
          ))}
        </ul>
      </DocSection>
    </>
  )
}

/**
 * Plan summary.
 *
 * Four equal KPI cards gave equal weight to four unequal facts. Coverage is
 * the one that decides whether the plan is adequate, so it leads with a meter
 * and states its own gap inline — which is what let the separate warning
 * banner below be removed rather than simply deleted.
 */
function PlanSummaryBar({
  plan,
  entryBlockers,
  uncoveredLabels,
}: {
  plan: TestPlan
  entryBlockers: number
  uncoveredLabels: string[]
}) {
  const total = plan.coveredNodeIds.length + plan.uncoveredNodeIds.length
  const covered = plan.coveredNodeIds.length
  const pct = total === 0 ? 100 : Math.round((covered / total) * 100)
  const entryMet = plan.entryCriteria.filter((c) => c.met).length

  return (
    <Card className="overflow-hidden">
      <div className="grid gap-px bg-[var(--border-subtle)] sm:grid-cols-2 lg:grid-cols-[1.6fr_1fr_1fr_1fr]">
        {/* Coverage — the load-bearing number, so it gets the meter */}
        <div className="bg-[var(--bg-surface)] p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--text-secondary)]">
              <Target className="size-3.5 text-[var(--text-tertiary)]" aria-hidden="true" />
              Impacted node coverage
            </p>
            <span className="numeral text-[22px] leading-none font-semibold text-[var(--text-primary)]">
              {covered}
              <span className="text-sm text-[var(--text-tertiary)]">/{total}</span>
            </span>
          </div>
          <div className="mt-3">
            <Meter
              value={pct}
              tone={uncoveredLabels.length > 0 ? 'warn' : 'ok'}
              label="Impacted node coverage"
            />
          </div>
          {uncoveredLabels.length > 0 ? (
            <p className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
              <AlertTriangle
                className="mt-px size-3.5 shrink-0 text-[var(--warn)]"
                aria-hidden="true"
              />
              <span>
                <span className="font-medium text-[var(--warn)]">{uncoveredLabels.join(', ')}</span>{' '}
                {uncoveredLabels.length === 1 ? 'has' : 'have'} no planned case. POL-004 blocks
                sign-off while a payroll-relevant node is uncovered.
              </span>
            </p>
          ) : (
            <p className="mt-2 text-xs text-[var(--text-tertiary)]">
              Every impacted node has at least one planned case.
            </p>
          )}
        </div>

        <SummaryCell
          icon={<FlaskConical className="size-3.5" aria-hidden="true" />}
          label="Planned cases"
          value={String(plan.estimatedCases)}
          detail={`≈ ${plan.estimatedDurationHours}h of execution`}
        />
        <SummaryCell
          icon={<LogIn className="size-3.5" aria-hidden="true" />}
          label="Entry criteria"
          value={`${entryMet}/${plan.entryCriteria.length}`}
          detail={entryBlockers > 0 ? 'Cycle cannot start' : 'All conditions hold'}
          tone={entryBlockers > 0 ? 'danger' : 'ok'}
        />
        <SummaryCell
          icon={<Wallet className="size-3.5" aria-hidden="true" />}
          label="Generation cost"
          value={formatUsd(plan.generationCostUsd)}
          detail={plan.model}
        />
      </div>
    </Card>
  )
}

function SummaryCell({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode
  label: string
  value: string
  detail: string
  tone?: 'ok' | 'danger'
}) {
  return (
    <div className="flex flex-col justify-between bg-[var(--bg-surface)] p-4">
      <p className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--text-secondary)]">
        <span className="text-[var(--text-tertiary)]">{icon}</span>
        {label}
      </p>
      <div className="mt-3">
        <p className="numeral text-[22px] leading-none font-semibold text-[var(--text-primary)]">
          {value}
        </p>
        <p
          className={cn(
            'mt-1.5 text-xs leading-snug',
            tone === 'danger' ? 'text-[var(--danger)]' : 'text-[var(--text-tertiary)]',
          )}
        >
          {detail}
        </p>
      </div>
    </div>
  )
}

function ScopeList({
  label,
  items,
  tone,
}: {
  label: string
  items: string[]
  tone: 'ok' | 'neutral'
}) {
  return (
    <div>
      <SectionLabel>{label}</SectionLabel>
      <ul className="mt-2 space-y-2">
        {items.map((s) => (
          <li key={s} className="flex items-start gap-2">
            <span
              className={
                tone === 'ok'
                  ? 'mt-[7px] size-1.5 shrink-0 rounded-full bg-[var(--ok-solid)]'
                  : 'mt-[7px] size-1.5 shrink-0 rounded-full bg-[var(--neutral-solid)]'
              }
              aria-hidden="true"
            />
            <span className="text-xs leading-relaxed text-[var(--text-secondary)]">{s}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * One side of the entry/exit gate.
 *
 * A column rather than a card: entry and exit are two ends of one mechanism,
 * and the shared card header already carries the combined unmet count.
 */
function CriteriaColumn({
  title,
  hint,
  icon,
  criteria,
}: {
  title: string
  hint: string
  icon: React.ReactNode
  criteria: Criterion[]
}) {
  const unmet = criteriaUnmet(criteria)
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 px-4 pt-3.5 pb-2">
        <p className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--text-primary)]">
          <span className="text-[var(--text-tertiary)]">{icon}</span>
          {title}
          {/* Always state the count. Showing "· 3 unmet" on one column and
              nothing on the other read as missing data rather than as "met". */}
          {unmet > 0 ? (
            <span className="font-medium text-[var(--warn)]">· {unmet} unmet</span>
          ) : (
            <span className="font-medium text-[var(--ok)]">· all met</span>
          )}
        </p>
      </div>
      <p className="px-4 pb-2 text-[11px] text-[var(--text-tertiary)]">{hint}</p>
      <ul className="divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">
        {criteria.map((c) => (
          <li key={c.id} className="flex items-start gap-2.5 p-3.5">
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
    </div>
  )
}

function NodeRow({
  id,
  node,
  covered,
}: {
  id: string
  node: GraphNode | undefined
  covered: boolean
}) {
  const meta = node ? NODE_KIND_META[node.kind] : null
  return (
    <li className="flex items-center gap-2.5 px-4 py-2.5">
      {meta ? (
        <span
          className="flex size-6 shrink-0 items-center justify-center rounded"
          style={{ color: meta.color }}
        >
          <meta.Icon className="size-3.5" aria-hidden="true" />
        </span>
      ) : null}
      <span className="min-w-0 flex-1 truncate text-xs text-[var(--text-primary)]">
        {node?.label ?? id}
      </span>
      {covered ? (
        <CheckCircle2 className="size-4 shrink-0 text-[var(--ok)]" aria-label="Covered" />
      ) : (
        <AlertTriangle
          className="size-4 shrink-0 text-[var(--warn)]"
          aria-label="Not covered by this plan"
        />
      )}
    </li>
  )
}

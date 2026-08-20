import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BadgeCheck,
  Ban,
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  Lock,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SectionLabel,
  Segmented,
  Skeleton,
} from '@/components/ui/primitives'
import { Drawer, Modal, useToast } from '@/components/ui/overlays'
import { Countdown, DecisionBadge, RiskBadge } from '@/components/domain/status'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { CURRENT_USER } from '@/lib/mock-data'
import { cn, formatDateTime, formatUsd, hoursUntil, relativeTime } from '@/lib/utils'
import type { ApprovalGate, ApprovalPackage } from '@/lib/types'

/** A gate paired with the package it belongs to — the unit of work in the queue. */
interface QueueItem {
  pkg: ApprovalPackage
  gate: ApprovalGate
  /** Position of this gate within its package, for the "step 3 of 4" line. */
  index: number
  total: number
}

type Lane = 'ready' | 'blocked' | 'settled'

function laneOf(gate: ApprovalGate): Lane {
  if (gate.decision !== 'pending') return 'settled'
  return gate.blockedBy.length > 0 ? 'blocked' : 'ready'
}

/**
 * Approvals as a decision queue.
 *
 * The previous screen was an inventory: every package expanded, every gate at
 * equal weight, six already-signed gates taking more room than the three
 * pending ones. Measured on a 900px viewport, all three Approve buttons were
 * disabled and one sat at y=1361 — the page's entire purpose was off-screen
 * and impossible, and it never said so.
 *
 * So the organising question is no longer "what packages exist" but "what can
 * I decide right now". Three lanes, in that order: what is actionable, what is
 * held up and why, and what is already settled (collapsed — a signed gate is a
 * record, not a task).
 */
export function ApprovalsPage() {
  const { items: packages, loading } = useAsyncList(() => api.getApprovals(), [])
  const [decision, setDecision] = useState<{ pkg: ApprovalPackage; gate: ApprovalGate } | null>(
    null,
  )
  const [lane, setLane] = useState<Lane>('ready')
  const [openPkg, setOpenPkg] = useState<ApprovalPackage | null>(null)

  const lanes = useMemo(() => {
    const all: QueueItem[] = packages.flatMap((pkg) =>
      pkg.gates.map((gate, index) => ({ pkg, gate, index, total: pkg.gates.length })),
    )
    return {
      ready: all.filter((i) => laneOf(i.gate) === 'ready'),
      blocked: all.filter((i) => laneOf(i.gate) === 'blocked'),
      settled: all.filter((i) => laneOf(i.gate) === 'settled'),
    }
  }, [packages])

  const items = lanes[lane]

  return (
    <>
      <PageHeader
        title="Approvals & Sign-off"
        icon={<BadgeCheck aria-hidden="true" />}
        tone="ok"
      />

      <PageBody className="space-y-4">
        {loading ? (
          <div className="space-y-4">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-40 rounded-xl" />
            ))}
          </div>
        ) : packages.length === 0 ? (
          <Card>
            <EmptyState
              icon={<BadgeCheck className="size-5" aria-hidden="true" />}
              title="Nothing awaiting approval"
              description="Approval packages appear here once a requirement has an impact analysis and an evidence run."
            />
          </Card>
        ) : (
          <>
            {/*
             * The queue's headline states the actual situation rather than four
             * neutral counts. When nothing is actionable, saying so plainly is
             * more useful than a "3 pending" tile that implies work is available.
             */}
            <QueueSummary
              ready={lanes.ready.length}
              blocked={lanes.blocked.length}
              settled={lanes.settled.length}
            />

            <Segmented
              label="Filter gates by state"
              value={lane}
              onChange={(v) => setLane(v)}
              options={[
                { id: 'ready' as const, label: `Ready for you ${lanes.ready.length}` },
                { id: 'blocked' as const, label: `Blocked ${lanes.blocked.length}` },
                { id: 'settled' as const, label: `Settled ${lanes.settled.length}` },
              ]}
            />

            {items.length === 0 ? (
              <Card>
                <EmptyState
                  icon={
                    lane === 'ready' ? (
                      <CheckCircle2 className="size-5" aria-hidden="true" />
                    ) : (
                      <BadgeCheck className="size-5" aria-hidden="true" />
                    )
                  }
                  title={
                    lane === 'ready'
                      ? 'Nothing is waiting on your decision'
                      : lane === 'blocked'
                        ? 'No gate is currently blocked'
                        : 'No decisions recorded yet'
                  }
                  description={
                    lane === 'ready' && lanes.blocked.length > 0
                      ? `${lanes.blocked.length} gate${lanes.blocked.length === 1 ? ' is' : 's are'} held up by a policy. Resolving those is what will unblock this queue.`
                      : 'Gates appear here as packages move through the lifecycle.'
                  }
                  action={
                    lane === 'ready' && lanes.blocked.length > 0 ? (
                      <Button variant="secondary" onClick={() => setLane('blocked')}>
                        See what is blocked
                      </Button>
                    ) : undefined
                  }
                />
              </Card>
            ) : (
              <ul className="space-y-3">
                {items.map((item) => (
                  <GateCard
                    key={item.gate.id}
                    item={item}
                    lane={lane}
                    onDecide={() => setDecision({ pkg: item.pkg, gate: item.gate })}
                    onContext={() => setOpenPkg(item.pkg)}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </PageBody>

      <DecisionModal state={decision} onClose={() => setDecision(null)} />
      <PackageDrawer pkg={openPkg} onClose={() => setOpenPkg(null)} />
    </>
  )
}

/**
 * One line that says what the queue actually is.
 *
 * Four equal KPI tiles gave "3 pending" the same weight as "3 blocked", which
 * hid the only fact that mattered: none of the three could be actioned.
 */
function QueueSummary({
  ready,
  blocked,
  settled,
}: {
  ready: number
  blocked: number
  settled: number
}) {
  const tone = ready > 0 ? 'accent' : blocked > 0 ? 'danger' : ('ok' as 'accent' | 'danger' | 'ok')

  const headline =
    ready > 0
      ? `${ready} gate${ready === 1 ? '' : 's'} ready for your decision`
      : blocked > 0
        ? `Nothing is actionable — ${blocked} gate${blocked === 1 ? ' is' : 's are'} policy-blocked`
        : 'All gates are settled'

  const detail =
    ready > 0
      ? blocked > 0
        ? `${blocked} other gate${blocked === 1 ? ' is' : 's are'} blocked by policy, and ${settled} ${settled === 1 ? 'is' : 'are'} already signed.`
        : `${settled} already signed.`
      : blocked > 0
        ? 'Each blocked gate names the policy holding it. Those must be resolved before any signature can be given.'
        : 'Nothing is waiting on a human right now.'

  return (
    <Card
      className={cn(
        'p-4',
        tone === 'danger' && 'border-[var(--danger-border)]',
        tone === 'ok' && 'border-[var(--ok-border)]',
      )}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            'mt-px flex size-8 shrink-0 items-center justify-center rounded-lg',
            tone === 'accent' && 'bg-[var(--accent-subtle)] text-[var(--accent-text)]',
            tone === 'danger' && 'bg-[var(--danger-subtle)] text-[var(--danger)]',
            tone === 'ok' && 'bg-[var(--ok-subtle)] text-[var(--ok)]',
          )}
          aria-hidden="true"
        >
          {tone === 'danger' ? (
            <Lock className="size-4" />
          ) : tone === 'ok' ? (
            <CheckCircle2 className="size-4" />
          ) : (
            <UserCheck className="size-4" />
          )}
        </span>
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-[var(--text-primary)]">{headline}</p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--text-secondary)]">
            {detail}
          </p>
        </div>
      </div>
    </Card>
  )
}

/**
 * One gate, as a unit of work.
 *
 * A gate is what a person acts on, so it — not its package — is the card. The
 * package is named as context on the way in, and its full evidence is one
 * click away rather than reprinted above every gate it contains.
 */
function GateCard({
  item,
  lane,
  onDecide,
  onContext,
}: {
  item: QueueItem
  lane: Lane
  onDecide: () => void
  onContext: () => void
}) {
  const { pkg, gate, index, total } = item
  const blocked = gate.blockedBy.length > 0
  const summary = pkg.evidenceSummary

  return (
    <li>
      <Card className={cn(blocked && 'border-[var(--danger-border)]')}>
        {/* Context: which change, and where in its chain this gate sits */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-4 py-2.5">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="numeral shrink-0 text-[11px] font-semibold whitespace-nowrap text-[var(--text-tertiary)]">
              {pkg.requirementRef}
            </span>
            <span className="min-w-0 truncate text-[13px] text-[var(--text-secondary)]">
              {pkg.title}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <RiskBadge risk={pkg.riskLevel} />
            <span className="text-[11px] text-[var(--text-tertiary)]">
              Gate {index + 1} of {total}
            </span>
          </div>
        </div>

        <div className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">
                  {gate.name}
                </h3>
                <DecisionBadge decision={gate.decision} />
                {gate.requiresEvidenceGrade === 'verified' ? (
                  <Badge
                    tone="verified"
                    icon={<ShieldCheck className="size-3" aria-hidden="true" />}
                  >
                    Requires verified evidence
                  </Badge>
                ) : null}
              </div>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-[var(--text-tertiary)]">
                <span>{gate.role}</span>
                {/*
                 * Time remaining on a pending decision, in green while there is
                 * headroom and red once the deadline has passed. A queue whose
                 * whole purpose is "what needs deciding" should say which items
                 * are already late without the reader doing date arithmetic.
                 */}
                {gate.decision === 'pending' && gate.dueAt ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <Countdown hours={hoursUntil(gate.dueAt)} prefix="breached ·" />
                  </>
                ) : null}
              </p>
            </div>

            {gate.decision === 'pending' ? (
              <div className="flex shrink-0 items-center gap-2">
                <Button variant="secondary" size="sm" onClick={onDecide}>
                  Reject
                </Button>
                <Button variant="primary" size="sm" disabled={blocked} onClick={onDecide}>
                  Approve
                </Button>
              </div>
            ) : null}
          </div>

          {/*
           * Evidence stated as a sentence, not four tiles. A signer needs to
           * know whether the evidence supports a signature — "4 verified, 1
           * asserted, 1 failed" answers that; four separate numbers make them
           * assemble it themselves.
           */}
          {lane !== 'settled' ? (
            <p className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-[var(--text-secondary)]">
              <ShieldCheck className="size-3.5 text-[var(--verified)]" aria-hidden="true" />
              <span>
                <span className="font-medium text-[var(--text-primary)]">{summary.verified}</span>{' '}
                verified
              </span>
              {summary.asserted > 0 ? (
                <span className="text-[var(--asserted)]">· {summary.asserted} asserted only</span>
              ) : null}
              {summary.failed > 0 ? (
                <span className="text-[var(--danger)]">· {summary.failed} failed</span>
              ) : null}
              {summary.coverageGaps > 0 ? (
                <span className="text-[var(--danger)]">
                  · {summary.coverageGaps} coverage gap{summary.coverageGaps === 1 ? '' : 's'}
                </span>
              ) : null}
              <button
                onClick={onContext}
                className="cursor-pointer text-[var(--text-tertiary)] underline underline-offset-2 hover:text-[var(--text-primary)]"
              >
                See the package
              </button>
            </p>
          ) : null}

          {/* Why this cannot be signed, stated where the disabled button is */}
          {blocked ? (
            <div className="mt-3 rounded-xl border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-[var(--danger)]">
                <Lock className="size-3.5 shrink-0" aria-hidden="true" />
                Cannot be approved until these are resolved
              </p>
              <ul className="mt-1.5 space-y-1">
                {gate.blockedBy.map((b) => (
                  <li
                    key={b}
                    className="flex gap-1.5 text-xs leading-relaxed text-[var(--text-secondary)]"
                  >
                    <span aria-hidden="true">·</span>
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2.5 flex flex-wrap gap-2">
                <Link to={`/impact/${pkg.requirementId}`}>
                  <Button variant="secondary" size="sm">
                    Review impact
                  </Button>
                </Link>
                <Link to="/evidence">
                  <Button variant="ghost" size="sm">
                    Open evidence
                  </Button>
                </Link>
              </div>
            </div>
          ) : null}

          {/* A settled gate is a record: who signed, when, and on what basis */}
          {gate.approver ? (
            <div className="mt-3 rounded-xl border border-[var(--ok-border)] bg-[var(--ok-subtle)] p-3">
              <p className="flex flex-wrap items-center gap-1.5 text-xs">
                <UserCheck className="size-3.5 shrink-0 text-[var(--ok)]" aria-hidden="true" />
                <span className="font-medium text-[var(--text-primary)]">{gate.approver}</span>
                <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                  {gate.approverEmail}
                </span>
                <span className="text-[var(--text-tertiary)]">
                  · {formatDateTime(gate.decidedAt)}
                </span>
              </p>
              {gate.comment ? (
                <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                  “{gate.comment}”
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </Card>
    </li>
  )
}

/**
 * The package behind a gate: its evidence, its cost, and every other gate in
 * its chain. Pulled into a drawer so the queue stays a list of decisions
 * rather than a wall of context repeated per gate.
 */
function PackageDrawer({ pkg, onClose }: { pkg: ApprovalPackage | null; onClose: () => void }) {
  if (!pkg) return null
  const approved = pkg.gates.filter((g) => g.decision === 'approved').length

  return (
    <Drawer
      open={Boolean(pkg)}
      onClose={onClose}
      width="lg"
      title={pkg.title}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="numeral">{pkg.requirementRef}</span>
          <RiskBadge risk={pkg.riskLevel} />
          <span>
            {approved} of {pkg.gates.length} gates signed
          </span>
        </div>
      }
      footer={
        <div className="flex gap-2">
          <Link to={`/impact/${pkg.requirementId}`}>
            <Button variant="secondary">Review impact</Button>
          </Link>
          <Link to="/evidence">
            <Button variant="ghost">Open evidence</Button>
          </Link>
        </div>
      }
    >
      <div className="space-y-5 p-5">
        <div>
          <SectionLabel>Evidence supporting this package</SectionLabel>
          <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <EvidenceStat
              icon={<ShieldCheck className="size-3.5" aria-hidden="true" />}
              label="Verified"
              value={pkg.evidenceSummary.verified}
              tone="verified"
            />
            <EvidenceStat
              icon={<Cpu className="size-3.5" aria-hidden="true" />}
              label="Asserted"
              value={pkg.evidenceSummary.asserted}
              tone="asserted"
            />
            <EvidenceStat
              icon={<Ban className="size-3.5" aria-hidden="true" />}
              label="Failed"
              value={pkg.evidenceSummary.failed}
              tone={pkg.evidenceSummary.failed > 0 ? 'danger' : 'neutral'}
            />
            <EvidenceStat
              icon={<Ban className="size-3.5" aria-hidden="true" />}
              label="Coverage gaps"
              value={pkg.evidenceSummary.coverageGaps}
              tone={pkg.evidenceSummary.coverageGaps > 0 ? 'danger' : 'neutral'}
            />
          </div>
        </div>

        <div>
          <SectionLabel>Approval chain</SectionLabel>
          <ul className="mt-2 space-y-2">
            {pkg.gates.map((g, i) => (
              <li
                key={g.id}
                className="flex items-start gap-2.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3"
              >
                <span
                  className={cn(
                    'flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                    g.decision === 'approved'
                      ? 'bg-[var(--ok-subtle)] text-[var(--ok)]'
                      : g.blockedBy.length > 0
                        ? 'bg-[var(--danger-subtle)] text-[var(--danger)]'
                        : 'bg-[var(--bg-surface-3)] text-[var(--text-tertiary)]',
                  )}
                  aria-hidden="true"
                >
                  {g.decision === 'approved' ? <CheckCircle2 className="size-3.5" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <p className="text-[13px] font-medium text-[var(--text-primary)]">{g.name}</p>
                    <DecisionBadge decision={g.decision} />
                  </div>
                  <p className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">{g.role}</p>
                  {g.approver ? (
                    <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
                      {g.approver} · {formatDateTime(g.decidedAt)}
                    </p>
                  ) : null}
                  {g.blockedBy.length > 0 ? (
                    <p className="mt-1 text-[11px] leading-relaxed text-[var(--danger)]">
                      {g.blockedBy.join(' · ')}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <SectionLabel>Submission</SectionLabel>
          <dl className="mt-2 space-y-2">
            {[
              ['Submitted by', pkg.submittedBy],
              ['Submitted', relativeTime(pkg.submittedAt)],
              ['Estimated cost', formatUsd(pkg.estimatedCostUsd, { precise: true })],
            ].map(([k, v]) => (
              <div key={k} className="flex items-baseline justify-between gap-3">
                <dt className="text-xs text-[var(--text-tertiary)]">{k}</dt>
                <dd className="text-right text-xs font-medium text-[var(--text-primary)]">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </Drawer>
  )
}

function EvidenceStat({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode
  label: string
  value: number
  tone: 'verified' | 'asserted' | 'danger' | 'neutral'
}) {
  const colors = {
    verified: 'text-[var(--verified)]',
    asserted: 'text-[var(--asserted)]',
    danger: 'text-[var(--danger)]',
    neutral: 'text-[var(--text-tertiary)]',
  }
  return (
    <div>
      <p
        className={cn(
          'flex items-center gap-1.5 text-[10px] font-medium tracking-wide uppercase',
          colors[tone],
        )}
      >
        {icon}
        {label}
      </p>
      <p className="tabular mt-0.5 text-lg font-semibold text-[var(--text-primary)]">{value}</p>
    </div>
  )
}

/**
 * Sign-off, with the evidence that the oversight was real.
 *
 * EU AI Act Art. 14 requires *effective* human oversight of a high-risk
 * system. A signature proves someone clicked; it does not prove they looked.
 * This modal records how long the reviewer spent, which evidence artifacts
 * they actually opened, and — the metric supervisory authorities ask for first
 * — whether they went along with the AI's recommendation or overrode it.
 *
 * None of this blocks the decision. Refusing to let someone sign because they
 * read too quickly would replace their judgement with a timer, which is the
 * same mistake as auto-rejecting on a missed SLA. It is reported, not enforced.
 */
function DecisionModal({
  state,
  onClose,
}: {
  state: { pkg: ApprovalPackage; gate: ApprovalGate } | null
  onClose: () => void
}) {
  const [comment, setComment] = useState('')
  const [touched, setTouched] = useState(false)
  const [opened, setOpened] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const openedAt = useRef<number>(Date.now())
  const { push } = useToast()

  /* Restart the clock each time the modal is opened for a new gate. */
  useEffect(() => {
    if (state) {
      openedAt.current = Date.now()
      setOpened([])
    }
  }, [state])

  if (!state) return null
  const { pkg, gate } = state

  const commentError =
    touched && comment.trim().length < 10
      ? 'A decision comment of at least 10 characters is required — it becomes part of the permanent record.'
      : null

  /*
   * The system recommends approval only when nothing blocks the gate and the
   * evidence it requires is actually present. Anything else is "none" — an
   * abstention is more honest than a recommendation the evidence cannot carry.
   */
  const aiRecommendation: 'approve' | 'reject' | 'none' =
    gate.blockedBy.length > 0
      ? 'reject'
      : gate.requiresEvidenceGrade === 'verified' && pkg.evidenceSummary.verified === 0
        ? 'reject'
        : pkg.evidenceSummary.failed > 0 || pkg.evidenceSummary.coverageGaps > 0
          ? 'none'
          : 'approve'

  const artifactsAvailable =
    pkg.evidenceSummary.verified + pkg.evidenceSummary.asserted + pkg.evidenceSummary.failed
  const overriding = aiRecommendation === 'reject'

  async function submit() {
    setTouched(true)
    if (comment.trim().length < 10) return
    setBusy(true)
    const reviewSeconds = Math.round((Date.now() - openedAt.current) / 1000)
    try {
      await api.decideGate({
        packageId: pkg.id,
        gateId: gate.id,
        decision: 'approved',
        comment: comment.trim(),
        oversight: {
          reviewDurationSeconds: reviewSeconds,
          artifactsOpened: opened,
          artifactsAvailable,
          aiRecommendation,
          humanDecision: 'approve',
          overridden: overriding,
          overrideRationale: overriding ? comment.trim() : null,
        },
      })
      onClose()
      setComment('')
      setTouched(false)
      push({
        tone: overriding ? 'warn' : 'ok',
        title: overriding ? 'Decision recorded as an override' : 'Decision recorded',
        description: `${gate.name} signed by ${CURRENT_USER.name}. Review time, artifacts opened${
          overriding ? ' and the override' : ''
        } are committed to the audit chain.`,
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Approve: ${gate.name}`}
      description={`${pkg.requirementRef} — ${pkg.title}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            icon={<BadgeCheck className="size-4" aria-hidden="true" />}
            onClick={() => void submit()}
          >
            {busy ? 'Recording…' : overriding ? 'Override and sign' : 'Sign and approve'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <SectionLabel>You are signing as</SectionLabel>
          <p className="mt-1.5 text-sm font-medium text-[var(--text-primary)]">
            {CURRENT_USER.name}
          </p>
          <p className="font-mono text-xs text-[var(--text-tertiary)]">{CURRENT_USER.email}</p>
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
            This signature is non-repudiable. It binds your identity to this decision, the exact
            evidence artifacts listed below, and the hash of the previous audit entry.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-[var(--verified-border)] bg-[var(--verified-subtle)] p-3">
            <p className="text-[10px] font-medium tracking-wide text-[var(--verified)] uppercase">
              Verified evidence
            </p>
            <p className="tabular mt-0.5 text-xl font-semibold text-[var(--text-primary)]">
              {pkg.evidenceSummary.verified}
            </p>
          </div>
          <div className="rounded-xl border border-[var(--asserted-border)] bg-[var(--asserted-subtle)] p-3">
            <p className="text-[10px] font-medium tracking-wide text-[var(--asserted)] uppercase">
              Asserted only
            </p>
            <p className="tabular mt-0.5 text-xl font-semibold text-[var(--text-primary)]">
              {pkg.evidenceSummary.asserted}
            </p>
          </div>
        </div>

        {/*
          Art. 14 evidence. Opening an artifact is recorded because "3 of 8
          artifacts were opened before signing" is a finding, and one that
          cannot be reconstructed after the fact.
        */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <SectionLabel>Evidence reviewed</SectionLabel>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
            Which artifacts you open is recorded alongside your signature. Reviewing is not
            enforced — it is reported.
          </p>
          <ul className="mt-2 space-y-1">
            {Array.from({ length: Math.min(artifactsAvailable, 6) }).map((_, i) => {
              const id = `art-${pkg.id}-${i}`
              const isOpen = opened.includes(id)
              return (
                <li key={id}>
                  <button
                    type="button"
                    onClick={() => setOpened((s) => (s.includes(id) ? s : [...s, id]))}
                    className={cn(
                      'flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-xs transition-colors duration-150',
                      isOpen
                        ? 'border-[var(--ok-border)] bg-[var(--ok-subtle)] text-[var(--text-primary)]'
                        : 'border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]',
                    )}
                  >
                    {isOpen ? (
                      <Eye className="size-3 shrink-0 text-[var(--ok)]" aria-hidden="true" />
                    ) : (
                      <EyeOff className="size-3 shrink-0" aria-hidden="true" />
                    )}
                    <span className="font-mono">Artifact {i + 1}</span>
                    <span className="ml-auto text-[10px] text-[var(--text-tertiary)]">
                      {isOpen ? 'opened' : 'not opened'}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          <p className="mt-2 text-[11px] text-[var(--text-tertiary)]">
            {opened.length} of {artifactsAvailable} opened
          </p>
        </div>

        {/* The override, named as such before it is signed. */}
        {overriding ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
            <ShieldAlert className="mt-px size-4 shrink-0 text-[var(--warn)]" aria-hidden="true" />
            <div>
              <p className="text-xs font-semibold text-[var(--warn)]">
                This approval overrides the system’s assessment
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                {gate.blockedBy.length > 0
                  ? `The gate is blocked by ${gate.blockedBy.join(', ')}.`
                  : 'This gate requires verified evidence and none is present.'}{' '}
                Signing anyway is recorded as an override against your name, with your rationale
                as the stated justification.
              </p>
            </div>
          </div>
        ) : null}

        <div>
          <label
            htmlFor="decision-comment"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            Decision rationale{' '}
            <span className="text-[var(--danger)]" aria-hidden="true">
              *
            </span>
          </label>
          <textarea
            id="decision-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onBlur={() => setTouched(true)}
            rows={3}
            aria-invalid={Boolean(commentError)}
            aria-describedby={commentError ? 'comment-error' : 'comment-help'}
            placeholder="What did you check, and why are you satisfied?"
            className="w-full resize-y rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 py-2 text-sm outline-none transition-colors duration-200 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
          />
          {commentError ? (
            <p id="comment-error" role="alert" className="mt-1.5 text-xs text-[var(--danger)]">
              {commentError}
            </p>
          ) : (
            <p id="comment-help" className="mt-1.5 text-xs text-[var(--text-tertiary)]">
              Auditors read this. Be specific about what you verified.
            </p>
          )}
        </div>
      </div>
    </Modal>
  )
}

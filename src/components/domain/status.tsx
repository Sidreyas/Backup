import {
  AlertTriangle,
  Boxes,
  Braces,
  CheckCircle2,
  CircleDashed,
  Clock,
  Cpu,
  Database,
  Eye,
  FileText,
  GitBranch,
  Layers,
  Loader2,
  MonitorSmartphone,
  PencilLine,
  Plug,
  Scale,
  ShieldCheck,
  Sparkles,
  Table2,
  UserRound,
  Workflow,
  XCircle,
} from 'lucide-react'
import { Badge, type BadgeTone } from '@/components/ui/primitives'
import { cn, formatCountdown, humanize } from '@/lib/utils'
import type {
  ApprovalDecision,
  ArtifactOrigin,
  EnvironmentStatus,
  EvidenceGrade,
  ExecutionStatus,
  ImpactSeverity,
  IngestStatus,
  LinkConfidence,
  NodeKind,
  RequirementStage,
  ReviewState,
  RunStatus,
  DefectSeverity,
  DefectStatus,
  TestLevel,
  TestPriority,
  TestType,
} from '@/lib/types'

/**
 * Evidence grade is the most important distinction in the product, so it gets
 * an icon and a word — never colour alone.
 */
export function EvidenceGradeBadge({ grade }: { grade: EvidenceGrade }) {
  return grade === 'verified' ? (
    <Badge tone="verified" icon={<ShieldCheck className="size-3" aria-hidden="true" />}>
      Verified
    </Badge>
  ) : (
    <Badge tone="asserted" icon={<Cpu className="size-3" aria-hidden="true" />}>
      Asserted
    </Badge>
  )
}

const RUN_STATUS: Record<RunStatus, { tone: BadgeTone; label: string; Icon: typeof CheckCircle2 }> =
  {
    passed: { tone: 'ok', label: 'Passed', Icon: CheckCircle2 },
    failed: { tone: 'danger', label: 'Failed', Icon: XCircle },
    flaky: { tone: 'warn', label: 'Flaky', Icon: AlertTriangle },
    running: { tone: 'info', label: 'Running', Icon: Loader2 },
    queued: { tone: 'neutral', label: 'Queued', Icon: Clock },
    skipped: { tone: 'neutral', label: 'Skipped', Icon: CircleDashed },
  }

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const { tone, label, Icon } = RUN_STATUS[status]
  return (
    <Badge
      tone={tone}
      icon={
        <Icon
          className={`size-3 ${status === 'running' ? 'animate-spin' : ''}`}
          aria-hidden="true"
        />
      }
    >
      {label}
    </Badge>
  )
}

const INGEST_STATUS: Record<IngestStatus, { tone: BadgeTone; label: string }> = {
  connected: { tone: 'ok', label: 'Connected' },
  syncing: { tone: 'info', label: 'Syncing' },
  indexing: { tone: 'info', label: 'Indexing' },
  error: { tone: 'danger', label: 'Error' },
  stale: { tone: 'warn', label: 'Stale' },
  disconnected: { tone: 'neutral', label: 'Disconnected' },
}

export function IngestStatusBadge({ status }: { status: IngestStatus }) {
  const { tone, label } = INGEST_STATUS[status]
  const spinning = status === 'syncing' || status === 'indexing'
  return (
    <Badge
      tone={tone}
      icon={
        spinning ? (
          <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        ) : status === 'error' ? (
          <XCircle className="size-3" aria-hidden="true" />
        ) : status === 'stale' ? (
          <AlertTriangle className="size-3" aria-hidden="true" />
        ) : status === 'connected' ? (
          <CheckCircle2 className="size-3" aria-hidden="true" />
        ) : (
          <CircleDashed className="size-3" aria-hidden="true" />
        )
      }
    >
      {label}
    </Badge>
  )
}

const CONFIDENCE: Record<LinkConfidence, { tone: BadgeTone; label: string }> = {
  confirmed: { tone: 'ok', label: 'Confirmed' },
  high: { tone: 'info', label: 'High' },
  medium: { tone: 'warn', label: 'Medium' },
  low: { tone: 'danger', label: 'Low' },
}

/** A link is a hypothesis until confirmed — the UI must always say which. */
export function ConfidenceBadge({ confidence }: { confidence: LinkConfidence }) {
  const { tone, label } = CONFIDENCE[confidence]
  return (
    <Badge
      tone={tone}
      icon={
        confidence === 'confirmed' ? (
          <CheckCircle2 className="size-3" aria-hidden="true" />
        ) : undefined
      }
    >
      {confidence === 'confirmed' ? label : `${label} confidence`}
    </Badge>
  )
}

const SEVERITY: Record<ImpactSeverity, { tone: BadgeTone; label: string }> = {
  breaking: { tone: 'danger', label: 'Breaking' },
  major: { tone: 'warn', label: 'Major' },
  minor: { tone: 'info', label: 'Minor' },
  none: { tone: 'neutral', label: 'No impact' },
}

export function SeverityBadge({ severity }: { severity: ImpactSeverity }) {
  const { tone, label } = SEVERITY[severity]
  return <Badge tone={tone}>{label}</Badge>
}

const STAGE: Record<RequirementStage, { tone: BadgeTone; label: string }> = {
  draft: { tone: 'neutral', label: 'Draft' },
  discussing: { tone: 'info', label: 'Discussing' },
  impact_review: { tone: 'info', label: 'Impact review' },
  test_planning: { tone: 'info', label: 'Test planning' },
  test_design: { tone: 'info', label: 'Test design' },
  test_execution: { tone: 'info', label: 'Test execution' },
  awaiting_approval: { tone: 'warn', label: 'Awaiting approval' },
  building: { tone: 'info', label: 'Building' },
  evidence: { tone: 'info', label: 'Evidence' },
  signed_off: { tone: 'ok', label: 'Signed off' },
  rejected: { tone: 'danger', label: 'Rejected' },
}

export function StageBadge({ stage }: { stage: RequirementStage }) {
  const { tone, label } = STAGE[stage]
  return <Badge tone={tone}>{label}</Badge>
}

const DECISION: Record<ApprovalDecision, { tone: BadgeTone; label: string }> = {
  approved: { tone: 'ok', label: 'Approved' },
  rejected: { tone: 'danger', label: 'Rejected' },
  pending: { tone: 'warn', label: 'Pending' },
  delegated: { tone: 'info', label: 'Delegated' },
}

export function DecisionBadge({ decision }: { decision: ApprovalDecision }) {
  const { tone, label } = DECISION[decision]
  return (
    <Badge
      tone={tone}
      icon={
        decision === 'approved' ? (
          <CheckCircle2 className="size-3" aria-hidden="true" />
        ) : decision === 'rejected' ? (
          <XCircle className="size-3" aria-hidden="true" />
        ) : (
          <Clock className="size-3" aria-hidden="true" />
        )
      }
    >
      {label}
    </Badge>
  )
}

export function RiskBadge({ risk }: { risk: 'critical' | 'high' | 'medium' | 'low' }) {
  const tones: Record<string, BadgeTone> = {
    critical: 'danger',
    high: 'warn',
    medium: 'info',
    low: 'neutral',
  }
  return <Badge tone={tones[risk]}>{humanize(risk)} risk</Badge>
}

/* -------------------------------------------------------------------- STLC */

const REVIEW_STATE: Record<ReviewState, { tone: BadgeTone; label: string; Icon: typeof FileText }> =
  {
    draft: { tone: 'neutral', label: 'Draft', Icon: PencilLine },
    in_review: { tone: 'warn', label: 'In review', Icon: Eye },
    approved: { tone: 'ok', label: 'Approved', Icon: CheckCircle2 },
    rejected: { tone: 'danger', label: 'Rejected', Icon: XCircle },
  }

export function ReviewStateBadge({ state }: { state: ReviewState }) {
  const { tone, label, Icon } = REVIEW_STATE[state]
  return (
    <Badge tone={tone} icon={<Icon className="size-3" aria-hidden="true" />}>
      {label}
    </Badge>
  )
}

/**
 * Where an artefact came from. An AI-generated plan or case is a proposal, not
 * an approved document — the same rule the graph applies to unconfirmed links.
 */
const ORIGIN: Record<ArtifactOrigin, { tone: BadgeTone; label: string; Icon: typeof Cpu }> = {
  ai_generated: { tone: 'asserted', label: 'AI generated', Icon: Sparkles },
  ai_edited_by_human: { tone: 'info', label: 'AI + human edits', Icon: PencilLine },
  human_authored: { tone: 'verified', label: 'Human authored', Icon: UserRound },
}

export function OriginBadge({ origin }: { origin: ArtifactOrigin }) {
  const { tone, label, Icon } = ORIGIN[origin]
  return (
    <Badge tone={tone} icon={<Icon className="size-3" aria-hidden="true" />}>
      {label}
    </Badge>
  )
}

const ENV_STATUS: Record<EnvironmentStatus, { tone: BadgeTone; label: string }> = {
  ready: { tone: 'ok', label: 'Ready' },
  provisioning: { tone: 'info', label: 'Provisioning' },
  refreshing: { tone: 'info', label: 'Refreshing' },
  degraded: { tone: 'warn', label: 'Degraded' },
  offline: { tone: 'danger', label: 'Offline' },
}

export function EnvironmentStatusBadge({ status }: { status: EnvironmentStatus }) {
  const { tone, label } = ENV_STATUS[status]
  const busy = status === 'provisioning' || status === 'refreshing'
  return (
    <Badge
      tone={tone}
      icon={
        busy ? (
          <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        ) : status === 'ready' ? (
          <CheckCircle2 className="size-3" aria-hidden="true" />
        ) : status === 'offline' ? (
          <XCircle className="size-3" aria-hidden="true" />
        ) : (
          <AlertTriangle className="size-3" aria-hidden="true" />
        )
      }
    >
      {label}
    </Badge>
  )
}

const EXECUTION_STATUS: Record<ExecutionStatus, { tone: BadgeTone; label: string }> = {
  queued: { tone: 'neutral', label: 'Queued' },
  running: { tone: 'info', label: 'Running' },
  passed: { tone: 'ok', label: 'Passed' },
  failed: { tone: 'danger', label: 'Failed' },
  aborted: { tone: 'neutral', label: 'Aborted' },
  blocked: { tone: 'warn', label: 'Blocked' },
}

export function ExecutionStatusBadge({ status }: { status: ExecutionStatus }) {
  const { tone, label } = EXECUTION_STATUS[status]
  return (
    <Badge
      tone={tone}
      icon={
        status === 'running' ? (
          <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        ) : status === 'passed' ? (
          <CheckCircle2 className="size-3" aria-hidden="true" />
        ) : status === 'failed' ? (
          <XCircle className="size-3" aria-hidden="true" />
        ) : status === 'blocked' ? (
          <AlertTriangle className="size-3" aria-hidden="true" />
        ) : (
          <Clock className="size-3" aria-hidden="true" />
        )
      }
    >
      {label}
    </Badge>
  )
}

export function PriorityBadge({ priority }: { priority: TestPriority }) {
  const tones: Record<TestPriority, BadgeTone> = {
    critical: 'danger',
    high: 'warn',
    medium: 'info',
    low: 'neutral',
  }
  return <Badge tone={tones[priority]}>{humanize(priority)}</Badge>
}

export const TEST_LEVEL_LABEL: Record<TestLevel, string> = {
  unit: 'Unit',
  integration: 'Integration',
  system: 'System',
  uat: 'UAT',
  regression: 'Regression',
}

export const TEST_TYPE_LABEL: Record<TestType, string> = {
  functional: 'Functional',
  security: 'Security',
  performance: 'Performance',
  accessibility: 'Accessibility',
  data_integrity: 'Data integrity',
  compliance: 'Compliance',
}

/**
 * A criterion is tri-state: met, unmet, or not yet evaluated. Rendering "not
 * evaluated" as a neutral dash rather than a red cross matters — an unchecked
 * gate is not the same as a failed one.
 */
export function CriterionIcon({ met }: { met: boolean | null }) {
  if (met === null)
    return (
      <CircleDashed
        className="size-4 shrink-0 text-[var(--text-tertiary)]"
        aria-label="Not yet evaluated"
      />
    )
  return met ? (
    <CheckCircle2 className="size-4 shrink-0 text-[var(--ok)]" aria-label="Met" />
  ) : (
    <XCircle className="size-4 shrink-0 text-[var(--danger)]" aria-label="Not met" />
  )
}

/* ------------------------------------------------------------- node kinds */

export const NODE_KIND_META: Record<
  NodeKind,
  { label: string; Icon: typeof Boxes; color: string }
> = {
  requirement: { label: 'Requirement', Icon: FileText, color: 'var(--info-solid)' },
  business_process: { label: 'Business process', Icon: Workflow, color: 'var(--accent)' },
  config_object: { label: 'Config object', Icon: Layers, color: 'var(--warn-solid)' },
  code_module: { label: 'Code module', Icon: Braces, color: 'var(--ok-solid)' },
  integration: { label: 'Integration', Icon: Plug, color: '#a855f7' },
  report: { label: 'Report', Icon: Table2, color: '#06b6d4' },
  data_entity: { label: 'Data entity', Icon: Database, color: '#ec4899' },
  screen: { label: 'Screen', Icon: MonitorSmartphone, color: '#f43f5e' },
  policy: { label: 'Policy', Icon: Scale, color: 'var(--danger-solid)' },
}

export function NodeKindBadge({ kind }: { kind: NodeKind }) {
  const { label, Icon } = NODE_KIND_META[kind]
  return (
    <Badge tone="neutral" icon={<Icon className="size-3" aria-hidden="true" />}>
      {label}
    </Badge>
  )
}

export const SOURCE_KIND_ICON = {
  repository: GitBranch,
  document: FileText,
  design: Boxes,
  platform: Layers,
  ticketing: Table2,
  wiki: FileText,
} as const

/* -------------------------------------------------------------- defects */

/**
 * Defect status.
 *
 * `fixed` is deliberately warn-toned, not ok: a fix that has not been
 * re-tested is a claim, and colouring it green would let it read as settled
 * on every screen that shows it.
 */
const DEFECT_STATUS: Record<DefectStatus, { tone: BadgeTone; label: string }> = {
  open: { tone: 'danger', label: 'Open' },
  in_progress: { tone: 'info', label: 'In progress' },
  fixed: { tone: 'warn', label: 'Fixed — needs re-test' },
  closed: { tone: 'ok', label: 'Closed' },
  wont_fix: { tone: 'neutral', label: "Won't fix" },
  rejected: { tone: 'neutral', label: 'Rejected' },
}

export function DefectStatusBadge({ status }: { status: DefectStatus }) {
  const { tone, label } = DEFECT_STATUS[status]
  return <Badge tone={tone}>{label}</Badge>
}

export const DEFECT_SEVERITY_LABEL: Record<DefectSeverity, string> = {
  breaking: 'Breaking',
  major: 'Major',
  minor: 'Minor',
  none: 'Trivial',
}

export function DefectSeverityBadge({ severity }: { severity: DefectSeverity }) {
  const tone: BadgeTone =
    severity === 'breaking'
      ? 'danger'
      : severity === 'major'
        ? 'warn'
        : severity === 'minor'
          ? 'info'
          : 'neutral'
  return <Badge tone={tone}>{DEFECT_SEVERITY_LABEL[severity]}</Badge>
}

/* ------------------------------------------------------------- deadlines */

/**
 * Time remaining against a deadline, coloured by whether it has been met.
 *
 * Green means there is headroom, red means the deadline has passed and by how
 * much. Colour is the point: a countdown rendered in body grey makes the
 * reader compute whether they are late, which is the one thing the number
 * exists to tell them at a glance.
 *
 * The breach is stated as elapsed time rather than a bare "overdue" — "6h 40m
 * over" says how bad it is, "overdue" only says that it is.
 *
 * Colour is never the sole signal: the words "left" and "over" carry the same
 * meaning for anyone who cannot distinguish the two hues.
 */
export function Countdown({
  hours,
  prefix,
  className,
}: {
  /** Hours remaining; negative once the deadline has passed. */
  hours: number
  /** Optional lead-in, e.g. "breached ·" */
  prefix?: string
  className?: string
}) {
  const breached = hours < 0
  if (!Number.isFinite(hours)) {
    return <span className={cn('text-[var(--text-tertiary)]', className)}>—</span>
  }
  return (
    <span
      className={cn(
        'tabular font-medium whitespace-nowrap',
        breached ? 'text-[var(--danger)]' : 'text-[var(--ok)]',
        className,
      )}
    >
      {breached && prefix ? `${prefix} ` : ''}
      {formatCountdown(hours)}
    </span>
  )
}

/**
 * The same idea for a threshold measured in whole days, where an hour-level
 * countdown would imply a precision the data does not have.
 */
export function DaysRemaining({
  days,
  className,
}: {
  /** Days remaining; negative once the threshold has been crossed. */
  days: number
  className?: string
}) {
  if (!Number.isFinite(days)) {
    return <span className={cn('text-[var(--text-tertiary)]', className)}>—</span>
  }
  const breached = days < 0
  const n = Math.abs(Math.round(days))
  return (
    <span
      className={cn(
        'tabular font-medium whitespace-nowrap',
        breached ? 'text-[var(--danger)]' : 'text-[var(--ok)]',
        className,
      )}
    >
      {breached ? `${n} ${n === 1 ? 'day' : 'days'} over` : `${n} ${n === 1 ? 'day' : 'days'} left`}
    </span>
  )
}

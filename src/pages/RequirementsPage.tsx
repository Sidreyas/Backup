import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MessagesSquare, Plus, Search } from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SearchInput,
  TableSkeleton,
} from '@/components/ui/primitives'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Modal, Tabs, useToast } from '@/components/ui/overlays'
import { PriorityBadge } from '@/components/domain/status'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { formatDate, formatUsd } from '@/lib/utils'
import type { Requirement, RequirementStage, SystemKind, TestPriority } from '@/lib/types'

const OPEN_STAGES = new Set([
  'draft',
  'discussing',
  'impact_review',
  'awaiting_approval',
  'building',
  'evidence',
])

/**
 * The three stages this table reports.
 *
 * The underlying model has eleven — draft, impact review, test planning, and so
 * on — which is the right granularity for the lifecycle screens but too much
 * detail for a list whose job is "where has this got to". Everything before a
 * decision reads as Discussing, everything waiting on one as Awaiting approval,
 * and everything past one as Approved.
 *
 * Rejected is kept separate rather than folded into Approved: reporting a
 * refused change as approved would be a lie, not a simplification.
 */
type CoarseStage = 'discussing' | 'awaiting_approval' | 'approved' | 'rejected'

const STAGE_ORDER: CoarseStage[] = ['discussing', 'awaiting_approval', 'approved', 'rejected']

const COARSE_STAGE_LABEL: Record<CoarseStage, string> = {
  discussing: 'Discussing',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  rejected: 'Rejected',
}

const COARSE_STAGE_TONE: Record<CoarseStage, 'info' | 'warn' | 'ok' | 'danger'> = {
  discussing: 'info',
  awaiting_approval: 'warn',
  approved: 'ok',
  rejected: 'danger',
}

function coarseStage(stage: RequirementStage): CoarseStage {
  if (stage === 'rejected') return 'rejected'
  if (stage === 'signed_off') return 'approved'
  if (stage === 'awaiting_approval') return 'awaiting_approval'
  return 'discussing'
}

function CoarseStageBadge({ stage }: { stage: RequirementStage }) {
  const c = coarseStage(stage)
  return <Badge tone={COARSE_STAGE_TONE[c]}>{COARSE_STAGE_LABEL[c]}</Badge>
}

const PRIORITY_ORDER: TestPriority[] = ['critical', 'high', 'medium', 'low']

const SYSTEM_KIND_LABEL: Record<SystemKind, string> = {
  vendor_platform: 'Vendor platform',
  internal_project: 'Internal project',
  mixed: 'Multiple systems',
}

export function RequirementsPage() {
  const { items: fetched, loading } = useAsyncList(() => api.getRequirements(), [])
  const navigate = useNavigate()
  const [tab, setTab] = useState('open')
  const [query, setQuery] = useState('')
  const [newOpen, setNewOpen] = useState(false)
  /**
   * Locally created requirements, held so a new one appears in the table
   * immediately rather than only after a refetch that may never happen.
   */
  const [created, setCreated] = useState<Requirement[]>([])

  const requirements = useMemo(() => {
    const ids = new Set(fetched.map((r) => r.id))
    return [...created.filter((r) => !ids.has(r.id)), ...fetched]
  }, [fetched, created])

  const counts = useMemo(
    () => ({
      open: requirements.filter((r) => OPEN_STAGES.has(r.stage)).length,
      closed: requirements.filter((r) => !OPEN_STAGES.has(r.stage)).length,
      all: requirements.length,
    }),
    [requirements],
  )

  const filtered = useMemo(() => {
    let list = requirements
    if (tab === 'open') list = list.filter((r) => OPEN_STAGES.has(r.stage))
    if (tab === 'closed') list = list.filter((r) => !OPEN_STAGES.has(r.stage))
    const q = query.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (r) =>
          r.title.toLowerCase().includes(q) ||
          r.ref.toLowerCase().includes(q) ||
          r.requestedBy.toLowerCase().includes(q),
      )
    }
    return list
  }, [requirements, tab, query])

  const columns: Column<Requirement>[] = [
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
      primary: true,
      sortValue: (r) => r.title,
      className: 'min-w-[280px]',
      cell: (r) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--text-primary)]">{r.title}</p>
          <p className="truncate text-xs text-[var(--text-tertiary)]">
            {r.requestedBy} · {r.requestedByRole}
          </p>
        </div>
      ),
    },
    {
      id: 'stage',
      header: 'Stage',
      /* Sort by lifecycle position, not alphabetically — "Approved" before
         "Discussing" would tell you nothing about progress. */
      sortValue: (r) => STAGE_ORDER.indexOf(coarseStage(r.stage)),
      cell: (r) => <CoarseStageBadge stage={r.stage} />,
    },
    {
      id: 'priority',
      header: 'Priority',
      sortValue: (r) => PRIORITY_ORDER.indexOf(r.priority),
      cell: (r) => <PriorityBadge priority={r.priority} />,
    },
    {
      id: 'platform',
      header: 'System',
      secondary: true,
      sortValue: (r) => r.platform,
      cell: (r) => (
        <div className="min-w-0">
          <p className="truncate text-xs">{r.platform}</p>
          <p className="truncate text-[11px] text-[var(--text-tertiary)]">
            {SYSTEM_KIND_LABEL[r.systemKind]}
          </p>
        </div>
      ),
    },
    {
      id: 'cost',
      header: 'Spend',
      align: 'right',
      secondary: true,
      sortValue: (r) => r.actualCostUsd,
      cell: (r) => <span className="tabular">{formatUsd(r.actualCostUsd, { precise: true })}</span>,
    },
    {
      id: 'date',
      header: 'Date',
      sortValue: (r) => r.createdAt,
      cell: (r) => (
        <span className="tabular whitespace-nowrap text-xs">{formatDate(r.createdAt)}</span>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Requirements"
        icon={<MessagesSquare aria-hidden="true" />}
        tone="accent"
        actions={
          <Button
            variant="primary"
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={() => setNewOpen(true)}
          >
            New requirement
          </Button>
        }
      />

      <PageBody className="space-y-4">
        <Card>
          <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] p-3 sm:flex-row sm:items-center sm:justify-between">
            <Tabs
              className="border-b-0"
              value={tab}
              onChange={setTab}
              items={[
                { id: 'open', label: 'Open', count: counts.open },
                { id: 'closed', label: 'Closed', count: counts.closed },
                { id: 'all', label: 'All', count: counts.all },
              ]}
            />
            <SearchInput
              className="sm:w-64"
              value={query}
              onChange={setQuery}
              placeholder="Filter requirements…"
              label="Filter requirements"
              icon={<Search className="size-3.5" aria-hidden="true" />}
            />
          </div>

          {loading ? (
            <TableSkeleton rows={6} cols={columns.length} />
          ) : (
            <DataTable
              rows={filtered}
              columns={columns}
              getRowId={(r) => r.id}
              onRowClick={(r) => navigate(`/requirements/${r.id}`)}
              initialSort={{ columnId: 'date', dir: 'desc' }}
              emptyState={
                <EmptyState
                  icon={<MessagesSquare className="size-5" aria-hidden="true" />}
                  title="No requirements here yet"
                  description="Start by describing a change in business language. Meridian will ground it against your connected systems before anyone writes code."
                  action={
                    <Button variant="primary" onClick={() => setNewOpen(true)}>
                      New requirement
                    </Button>
                  }
                />
              }
            />
          )}
        </Card>
      </PageBody>

      <NewRequirementModal
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(r) => setCreated((list) => [r, ...list])}
      />
    </>
  )
}

/**
 * Systems a requirement can target.
 *
 * Split into vendor platforms and in-house work: a team's own applications are
 * governed the same way, and offering only vendor products forced internal
 * changes to be filed under something they are not.
 */
const SYSTEM_OPTIONS: { group: string; kind: SystemKind; options: string[] }[] = [
  {
    group: 'Vendor platforms',
    kind: 'vendor_platform',
    options: [
      'Workday HCM',
      'SAP S/4HANA',
      'Dynamics 365',
      'Salesforce',
      'ServiceNow',
      'Oracle Fusion',
    ],
  },
  {
    group: 'Internal projects',
    kind: 'internal_project',
    options: [
      'Internal web application',
      'Internal mobile app',
      'Internal API / service',
      'Data pipeline / warehouse',
      'Legacy in-house system',
    ],
  },
  {
    group: 'Other',
    kind: 'mixed',
    options: ['Spans several systems', 'Not sure yet'],
  },
]

/** Which kind a chosen system belongs to — drives the badge in the table. */
function kindOf(platform: string): SystemKind {
  for (const g of SYSTEM_OPTIONS) if (g.options.includes(platform)) return g.kind
  return 'vendor_platform'
}

function NewRequirementModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (r: Requirement) => void
}) {
  const [title, setTitle] = useState('')
  const [detail, setDetail] = useState('')
  const [platform, setPlatform] = useState('Workday HCM')
  const [priority, setPriority] = useState<TestPriority>('medium')
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const { push } = useToast()
  const navigate = useNavigate()

  const titleError =
    touched && title.trim().length < 8 ? 'Give the change a title of at least 8 characters.' : null

  /** Reset between openings so a cancelled draft never leaks into the next one. */
  useEffect(() => {
    if (open) {
      setTitle('')
      setDetail('')
      setPlatform('Workday HCM')
      setPriority('medium')
      setTouched(false)
      setSaving(false)
    }
  }, [open])

  async function submit() {
    setTouched(true)
    if (title.trim().length < 8 || saving) return
    setSaving(true)

    /*
     * Actually create the record. This used to navigate to req-1 regardless of
     * input, so every new requirement opened someone else's discussion.
     */
    const created = await api.createRequirement({
      title: title.trim(),
      summary: detail.trim(),
      platform,
      systemKind: kindOf(platform),
      priority,
    })

    onCreated(created)
    onClose()
    push({
      tone: 'ok',
      title: `${created.ref} created`,
      description: 'Opening the discussion for this requirement.',
    })
    navigate(`/requirements/${created.id}`)
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Describe the change you want"
      description="Write it in business language. You do not need to know the codebase or the configuration — that is what the graph is for."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} loading={saving}>
            Start discussion
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label
            htmlFor="req-title"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            Title{' '}
            <span className="text-[var(--danger)]" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="req-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => setTouched(true)}
            aria-invalid={Boolean(titleError)}
            aria-describedby={titleError ? 'req-title-error' : 'req-title-help'}
            placeholder="e.g. Auto-approve overtime under 4 hours per week"
            className="h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 text-sm outline-none transition-colors duration-200 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
          />
          {titleError ? (
            <p id="req-title-error" role="alert" className="mt-1.5 text-xs text-[var(--danger)]">
              {titleError}
            </p>
          ) : (
            <p id="req-title-help" className="mt-1.5 text-xs text-[var(--text-tertiary)]">
              A short sentence describing the outcome you want.
            </p>
          )}
        </div>

        <div>
          <label
            htmlFor="req-detail"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            What problem are you solving?
          </label>
          <textarea
            id="req-detail"
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            rows={4}
            placeholder="Who is affected, what happens today, and what should happen instead."
            className="w-full resize-y rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 py-2 text-sm outline-none transition-colors duration-200 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
          />
          <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
            Optional — the assistant will ask follow-up questions if this is thin.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="req-platform"
              className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
            >
              Primary system
            </label>
            <select
              id="req-platform"
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="h-10 w-full cursor-pointer rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 text-sm outline-none transition-colors duration-200 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
            >
              {SYSTEM_OPTIONS.map((g) => (
                <optgroup key={g.group} label={g.group}>
                  {g.options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
              Vendor platform or one of your own applications — both are governed the same way.
            </p>
          </div>

          <div>
            <label
              htmlFor="req-priority"
              className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
            >
              Priority
            </label>
            <select
              id="req-priority"
              value={priority}
              onChange={(e) => setPriority(e.target.value as TestPriority)}
              className="h-10 w-full cursor-pointer rounded-md border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 text-sm outline-none transition-colors duration-200 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
            >
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
            <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
              How urgently this is wanted — separate from how risky it turns out to be.
            </p>
          </div>
        </div>
      </div>
    </Modal>
  )
}

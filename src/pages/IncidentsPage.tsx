/**
 * The AI incident register.
 *
 * Defects record what the software under test got wrong. This records what
 * *Meridian* got wrong — a fabricated citation, a missed impact, an agent that
 * acted outside advisory mode. NIST AI RMF asks for incident disclosure and EU
 * AI Act Art. 73 obliges providers to report serious incidents on a deadline,
 * so this is a control surface rather than a support queue.
 *
 * The page is deliberately unflattering. A register showing only resolved
 * incidents, all caught automatically, would be evidence that nothing is being
 * recorded rather than evidence that nothing goes wrong.
 */
import { useMemo, useState } from 'react'
import {
  AlertOctagon,
  Bot,
  CheckCircle2,
  Eye,
  Megaphone,
  Search,
  ShieldAlert,
  Siren,
  Wrench,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SectionLabel,
  Skeleton,
  StatTile,
  SearchInput,
} from '@/components/ui/primitives'
import { Tabs } from '@/components/ui/overlays'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { cn, formatDateTime, humanize } from '@/lib/utils'
import type { AiIncident, IncidentSeverity, IncidentStatus } from '@/lib/types'

const SEVERITY_TONE: Record<IncidentSeverity, 'danger' | 'warn' | 'neutral'> = {
  critical: 'danger',
  major: 'warn',
  minor: 'neutral',
}

const STATUS_TONE: Record<IncidentStatus, 'danger' | 'warn' | 'info' | 'ok' | 'neutral'> = {
  open: 'danger',
  investigating: 'warn',
  contained: 'info',
  resolved: 'ok',
  disclosed: 'neutral',
}

const DETECTION_LABEL = {
  human_review: { label: 'Human review', icon: Eye },
  automated_probe: { label: 'Automated probe', icon: Bot },
  policy_engine: { label: 'Policy engine', icon: ShieldAlert },
  external_report: { label: 'External report', icon: Megaphone },
} as const

export function IncidentsPage() {
  const { items: incidents, loading } = useAsyncList(() => api.getIncidents(), [])
  const [tab, setTab] = useState('all')
  const [query, setQuery] = useState('')

  const counts = useMemo(
    () => ({
      all: incidents.length,
      open: incidents.filter((i) => i.status !== 'resolved' && i.status !== 'disclosed').length,
      reportable: incidents.filter((i) => i.reportable).length,
      /* The metric that matters most: did a person or a control catch it? */
      humanCaught: incidents.filter((i) => i.detectionMethod === 'human_review').length,
    }),
    [incidents],
  )

  const filtered = useMemo(() => {
    let list = incidents
    if (tab === 'open') list = list.filter((i) => i.status !== 'resolved' && i.status !== 'disclosed')
    if (tab === 'reportable') list = list.filter((i) => i.reportable)
    if (tab === 'resolved')
      list = list.filter((i) => i.status === 'resolved' || i.status === 'disclosed')
    const q = query.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (i) =>
          i.title.toLowerCase().includes(q) ||
          i.description.toLowerCase().includes(q) ||
          i.ref.toLowerCase().includes(q) ||
          i.affectedRequirementRefs.some((r) => r.toLowerCase().includes(q)),
      )
    }
    return list
  }, [incidents, tab, query])

  return (
    <>
      <PageHeader
        title="AI Incident Register"
        icon={<AlertOctagon aria-hidden="true" />}
        tone="danger"
      />

      <PageBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Total incidents"
            value={counts.all}
            tone="accent"
            sublabel="Since the register opened"
          />
          <StatTile
            label="Open"
            value={counts.open}
            tone={counts.open > 0 ? 'danger' : 'ok'}
            sublabel="Not yet resolved or disclosed"
          />
          <StatTile
            label="Art. 73 reportable"
            value={counts.reportable}
            tone="warn"
            sublabel="Judged against the serious-incident test"
          />
          <StatTile
            label="Caught by a person"
            value={`${counts.humanCaught}/${counts.all}`}
            tone="asserted"
            sublabel="A human catching it means a control did not"
          />
        </div>

        {/* The uncomfortable number, stated rather than buried. */}
        {counts.humanCaught > 0 ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
            <Siren className="mt-px size-4 shrink-0 text-[var(--warn)]" aria-hidden="true" />
            <div>
              <p className="text-xs font-semibold text-[var(--warn)]">
                {counts.humanCaught} of {counts.all} incidents were found by a person, not a control
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                Human review is the last line, not the first. Each of these represents a detection
                path that should have fired earlier and did not — which is the finding, regardless
                of whether the incident itself was contained.
              </p>
            </div>
          </div>
        ) : null}

        <Card>
          <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] p-3 sm:flex-row sm:items-center sm:justify-between">
            <Tabs
              className="border-b-0"
              value={tab}
              onChange={setTab}
              items={[
                { id: 'all', label: 'All', count: counts.all },
                { id: 'open', label: 'Open', count: counts.open },
                { id: 'reportable', label: 'Reportable', count: counts.reportable },
                {
                  id: 'resolved',
                  label: 'Closed',
                  count: incidents.filter(
                    (i) => i.status === 'resolved' || i.status === 'disclosed',
                  ).length,
                },
              ]}
            />
            <SearchInput
              className="sm:w-64"
              value={query}
              onChange={setQuery}
              placeholder="Filter incidents…"
              label="Filter incidents"
              icon={<Search className="size-3.5" aria-hidden="true" />}
            />
          </div>

          {loading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full rounded-lg" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<CheckCircle2 className="size-5" aria-hidden="true" />}
              title="No incidents match this filter"
              description="An empty register is only good news if the detection controls behind it are firing."
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
          ) : (
            <ul className="divide-y divide-[var(--border-subtle)]">
              {filtered.map((incident) => (
                <IncidentRow key={incident.id} incident={incident} />
              ))}
            </ul>
          )}
        </Card>
      </PageBody>
    </>
  )
}

function IncidentRow({ incident }: { incident: AiIncident }) {
  const [expanded, setExpanded] = useState(false)
  const detection = DETECTION_LABEL[incident.detectionMethod]
  const DetectionIcon = detection.icon

  return (
    <li>
      <button
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className="flex w-full cursor-pointer items-start gap-3 p-4 text-left transition-colors duration-150 hover:bg-[var(--bg-hover)]"
      >
        <span
          className={cn(
            'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border',
            incident.severity === 'critical'
              ? 'border-[var(--danger-border)] bg-[var(--danger-subtle)] text-[var(--danger)]'
              : incident.severity === 'major'
                ? 'border-[var(--warn-border)] bg-[var(--warn-subtle)] text-[var(--warn)]'
                : 'border-[var(--border-default)] bg-[var(--bg-surface-2)] text-[var(--text-tertiary)]',
          )}
        >
          <AlertOctagon className="size-4" aria-hidden="true" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
              {incident.ref}
            </span>
            <Badge tone={SEVERITY_TONE[incident.severity]}>{humanize(incident.severity)}</Badge>
            <Badge tone={STATUS_TONE[incident.status]}>{humanize(incident.status)}</Badge>
            <Badge tone="neutral">{humanize(incident.kind)}</Badge>
            {incident.reportable ? <Badge tone="danger">Art. 73 reportable</Badge> : null}
          </div>
          <p className="mt-1 text-sm leading-snug font-medium text-[var(--text-primary)]">
            {incident.title}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-[var(--text-tertiary)]">
            <DetectionIcon className="size-3" aria-hidden="true" />
            {detection.label} · {incident.detectedBy} · {formatDateTime(incident.detectedAt)}
            {incident.affectedRequirementRefs.length
              ? ` · affects ${incident.affectedRequirementRefs.join(', ')}`
              : ''}
          </p>

          {expanded ? (
            <div className="mt-3 space-y-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
              <div>
                <SectionLabel>What happened</SectionLabel>
                <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                  {incident.description}
                </p>
              </div>

              <div>
                <SectionLabel>
                  {incident.reportable ? 'Why this is reportable' : 'Why this is not reportable'}
                </SectionLabel>
                <p
                  className={cn(
                    'mt-1 rounded border px-2 py-1.5 text-xs leading-relaxed',
                    incident.reportable
                      ? 'border-[var(--danger-border)] bg-[var(--danger-subtle)] text-[var(--text-primary)]'
                      : 'border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--text-secondary)]',
                  )}
                >
                  {incident.reportableRationale}
                </p>
              </div>

              {incident.model ? (
                <div>
                  <SectionLabel>Model implicated</SectionLabel>
                  <p className="mt-1 font-mono text-[11px] text-[var(--text-primary)]">
                    {incident.model} @ {incident.modelVersion}
                  </p>
                </div>
              ) : null}

              {incident.disclosedAt ? (
                <div>
                  <SectionLabel>Disclosure</SectionLabel>
                  <p className="mt-1 text-xs text-[var(--text-primary)]">
                    {formatDateTime(incident.disclosedAt)} — {incident.disclosedTo}
                  </p>
                </div>
              ) : null}

              {incident.correctiveAction ? (
                <div>
                  <SectionLabel>Corrective action</SectionLabel>
                  <p className="mt-1 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                    <Wrench
                      className="mt-0.5 size-3 shrink-0 text-[var(--text-tertiary)]"
                      aria-hidden="true"
                    />
                    {incident.correctiveAction}
                  </p>
                </div>
              ) : null}

              {incident.notes.length ? (
                <div>
                  <SectionLabel>Working record</SectionLabel>
                  <ul className="mt-1.5 space-y-1.5">
                    {incident.notes.map((n, i) => (
                      <li key={i} className="text-xs leading-relaxed">
                        <span className="text-[var(--text-tertiary)]">
                          {formatDateTime(n.at)} · {n.by}
                        </span>
                        <p className="text-[var(--text-secondary)]">{n.text}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </button>
    </li>
  )
}

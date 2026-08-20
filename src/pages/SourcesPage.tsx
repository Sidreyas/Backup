import { useCallback, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  Database,
  ExternalLink,
  Plus,
  Maximize2,
  RefreshCw,
  Search,
} from 'lucide-react'
import { PageBody, PageFilters, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Meter,
  SearchInput,
  Segmented,
  TableSkeleton,
} from '@/components/ui/primitives'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Drawer, Modal, Tabs, useToast } from '@/components/ui/overlays'
import { DaysRemaining, IngestStatusBadge, SOURCE_KIND_ICON } from '@/components/domain/status'
import { DropZone } from '@/components/domain/DropZone'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { cn, daysSince, formatNumber, humanize, relativeTime } from '@/lib/utils'
import { GraphView } from './GraphPage'
import type { KnowledgeSource } from '@/lib/types'

type View = 'sources' | 'graph'

export function SourcesPage() {
  // View lives in the URL so a graph link is shareable and survives reload.
  const [params, setParams] = useSearchParams()
  const view: View = params.get('view') === 'graph' ? 'graph' : 'sources'
  const setView = useCallback(
    (v: View) => setParams(v === 'graph' ? { view: 'graph' } : {}, { replace: true }),
    [setParams],
  )

  // GraphView hands its fullscreen trigger up so the page header can call it.
  const graphFullscreen = useRef<(() => void) | null>(null)
  const registerFullscreen = useCallback((fn: () => void) => {
    graphFullscreen.current = fn
  }, [])

  const { items: sources, loading } = useAsyncList(() => api.getSources(), [])
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState('all')
  const [selected, setSelected] = useState<KnowledgeSource | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const { push } = useToast()

  /*
   * Ingest a dropped file and report what came of it.
   *
   * Simpler than the ingestion page's version, which threaded each file into a
   * live job list. There is no job list here — a source appears in the table
   * once it is indexed, and until then the toast is the honest amount of
   * feedback: this page is about what is connected, not about queue mechanics.
   */
  const handleFiles = useCallback(
    (files: { name: string; sizeLabel: string }[]) => {
      files.forEach((f) => {
        void api
          .uploadArtifact(f)
          .then((done) => {
            push({
              tone: 'ok',
              title: `${done.name} ingested`,
              description: `${done.entitiesExtracted} entities extracted · ${done.linksProposed} links proposed`,
            })
          })
          .catch(() => {
            push({
              tone: 'danger',
              title: `${f.name} could not be ingested`,
              description: 'Nothing was added. Try again, or check the file is readable.',
            })
          })
      })
    },
    [push],
  )

  const counts = useMemo(
    () => ({
      all: sources.length,
      /*
       * Still being read. `syncing` is fetching and `indexing` is parsing —
       * two stages of the same answer to "is this source ready to reason
       * over yet", so they share one tab rather than splitting a short list.
       */
      processing: sources.filter((s) => s.status === 'syncing' || s.status === 'indexing').length,
      attention: sources.filter((s) => s.status === 'error' || s.status === 'stale').length,
      platform: sources.filter((s) => s.kind === 'platform').length,
    }),
    [sources],
  )

  const filtered = useMemo(() => {
    let list = sources
    if (tab === 'processing')
      list = list.filter((s) => s.status === 'syncing' || s.status === 'indexing')
    if (tab === 'attention') list = list.filter((s) => s.status === 'error' || s.status === 'stale')
    if (tab === 'platform') list = list.filter((s) => s.kind === 'platform')
    const q = query.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.provider.toLowerCase().includes(q) ||
          s.owner.toLowerCase().includes(q),
      )
    }
    return list
  }, [sources, tab, query])

  const columns: Column<KnowledgeSource>[] = [
    {
      id: 'name',
      primary: true,
      header: 'Source',
      sortValue: (r) => r.name,
      className: 'min-w-[260px]',
      cell: (r) => {
        const Icon = SOURCE_KIND_ICON[r.kind]
        return (
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded bg-[var(--bg-surface-2)] text-[var(--text-tertiary)]">
              <Icon className="size-3.5" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="truncate font-medium text-[var(--text-primary)]">{r.name}</p>
              <p className="truncate text-xs text-[var(--text-tertiary)]">
                {r.provider} · {humanize(r.kind)} · {r.owner}
              </p>
            </div>
          </div>
        )
      },
    },
    {
      id: 'status',
      header: 'Status',
      sortValue: (r) => r.status,
      cell: (r) => <IngestStatusBadge status={r.status} />,
    },
    {
      id: 'sync',
      header: 'Last sync',
      sortValue: (r) => r.lastSyncedAt ?? '',
      cell: (r) => {
        const days = daysSince(r.lastSyncedAt)
        const isStale = days > r.stalenessThresholdDays
        return (
          <div className="min-w-0 whitespace-nowrap">
            <span className={cn('tabular block', isStale && 'text-[var(--text-secondary)]')}>
              {relativeTime(r.lastSyncedAt)}
            </span>
            {/*
             * Headroom against the source's own freshness threshold. The row
             * previously showed only "1mo ago" in body grey, which left the
             * reader to work out whether that was acceptable — the threshold
             * varies per source, so it was not something they could know.
             */}
            <DaysRemaining className="block text-[11px]" days={r.stalenessThresholdDays - days} />
          </div>
        )
      },
    },
    {
      id: 'entities',
      secondary: true,
      header: 'Entities',
      align: 'right',
      sortValue: (r) => r.entities,
      cell: (r) => <span className="tabular">{formatNumber(r.entities)}</span>,
    },
    {
      id: 'coverage',
      secondary: true,
      header: 'Parse coverage',
      sortValue: (r) => r.coverage,
      className: 'w-[140px]',
      cell: (r) => (
        <div className="flex items-center gap-2">
          <Meter
            value={r.coverage}
            tone={r.coverage >= 80 ? 'ok' : r.coverage >= 50 ? 'warn' : 'danger'}
            label={`${r.name} parse coverage`}
          />
          <span className="tabular w-8 shrink-0 text-right text-xs">{r.coverage}%</span>
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Knowledge Sources"
        icon={<Database aria-hidden="true" />}
        tone="accent"
        // The sources view speaks for itself; only the graph view needs saying
        // what it is, since "a graph of what" is not obvious from the picture.
        actions={
          <>
            {view === 'graph' ? (
              <Button
                variant="secondary"
                icon={<Maximize2 className="size-4" aria-hidden="true" />}
                onClick={() => graphFullscreen.current?.()}
              >
                Expand
              </Button>
            ) : (
              <Button
                variant="secondary"
                icon={<RefreshCw className="size-4" aria-hidden="true" />}
                onClick={() =>
                  push({
                    tone: 'info',
                    title: 'Re-sync queued',
                    description: 'All connected sources will re-index.',
                  })
                }
              >
                Re-sync all
              </Button>
            )}
            {/* Opens the connect-a-source modal. It used to link to the
                ingestion page, which no longer exists — dropping files is now
                the drop zone below, and this button is for connecting a
                system, which is the other half of "add data". */}
            <Button
              variant="primary"
              icon={<Plus className="size-4" aria-hidden="true" />}
              onClick={() => setAddOpen(true)}
            >
              Add data
            </Button>
          </>
        }
      />

      <PageFilters>
        <Segmented
          label="Choose a view"
          value={view}
          onChange={setView}
          options={[
            { id: 'sources', label: 'Sources' },
            { id: 'graph', label: 'Knowledge graph' },
          ]}
        />
      </PageFilters>

      <PageBody className="space-y-4">
        {view === 'graph' ? (
          <GraphView onRegisterFullscreen={registerFullscreen} />
        ) : (
          <>
            <DropZone onFiles={handleFiles} />

            <Card>
              <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] p-3 sm:flex-row sm:items-center sm:justify-between">
                <Tabs
                  className="border-b-0"
                  value={tab}
                  onChange={setTab}
                  items={[
                    { id: 'all', label: 'All sources', count: counts.all },
                    { id: 'processing', label: 'Processing', count: counts.processing },
                    { id: 'attention', label: 'Needs attention', count: counts.attention },
                    { id: 'platform', label: 'Packaged platforms', count: counts.platform },
                  ]}
                />
                <SearchInput
                  className="sm:w-64"
                  value={query}
                  onChange={setQuery}
                  placeholder="Filter sources…"
                  label="Filter sources"
                  icon={<Search className="size-3.5" aria-hidden="true" />}
                />
              </div>

              {loading ? (
                <TableSkeleton rows={6} cols={5} />
              ) : (
                <DataTable
                  rows={filtered}
                  columns={columns}
                  getRowId={(r) => r.id}
                  onRowClick={setSelected}
                  selectedId={selected?.id ?? null}
                  initialSort={{ columnId: 'name', dir: 'asc' }}
                  emptyState={
                    <EmptyState
                      icon={<Database className="size-5" aria-hidden="true" />}
                      title="No sources match this filter"
                      description="Try a different search term, or connect a new source to widen what Meridian can reason about."
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
          </>
        )}
      </PageBody>

      <SourceDrawer source={selected} onClose={() => setSelected(null)} />
      <AddSourceModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onConnect={(name) => {
          setAddOpen(false)
          push({
            tone: 'ok',
            title: 'Connector queued',
            description: `${name} will begin indexing once credentials are verified.`,
          })
        }}
      />
    </>
  )
}

function SourceDrawer({
  source,
  onClose,
}: {
  source: KnowledgeSource | null
  onClose: () => void
}) {
  const { push } = useToast()
  if (!source) return null

  const days = daysSince(source.lastSyncedAt)
  const isStale = days > source.stalenessThresholdDays

  return (
    <Drawer
      open={Boolean(source)}
      onClose={onClose}
      title={source.name}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <IngestStatusBadge status={source.status} />
          <Badge tone="neutral">{source.provider}</Badge>
          <Badge tone="neutral">{humanize(source.kind)}</Badge>
        </div>
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            icon={<RefreshCw className="size-4" aria-hidden="true" />}
            onClick={() =>
              push({ tone: 'info', title: 'Re-sync queued', description: source.name })
            }
          >
            Re-sync now
          </Button>
        </>
      }
    >
      <div className="space-y-4 p-5">
        {source.error ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-3">
            <AlertTriangle
              className="mt-px size-4 shrink-0 text-[var(--danger)]"
              aria-hidden="true"
            />
            <div>
              <p className="text-xs font-semibold text-[var(--danger)]">Connection failed</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                {source.error}
              </p>
            </div>
          </div>
        ) : null}

        {isStale && !source.error ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
            <AlertTriangle
              className="mt-px size-4 shrink-0 text-[var(--warn)]"
              aria-hidden="true"
            />
            <div>
              <p className="text-xs font-semibold text-[var(--warn)]">
                Stale by {days - source.stalenessThresholdDays} days
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                Any impact analysis relying on this source may miss changes made after{' '}
                {relativeTime(source.lastSyncedAt)}. Policy POL-014 will flag affected analyses.
              </p>
            </div>
          </div>
        ) : null}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          {[
            ['Owner', source.owner],
            ['Last synced', relativeTime(source.lastSyncedAt)],
            ['Entities indexed', formatNumber(source.entities)],
            ['Documents parsed', formatNumber(source.documents)],
            ['Size on disk', source.sizeLabel],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[11px] font-medium tracking-wide text-[var(--text-tertiary)] uppercase">
                {k}
              </dt>
              <dd className="tabular mt-0.5 text-sm text-[var(--text-primary)]">{v}</dd>
            </div>
          ))}

          {/*
           * Freshness stated as headroom rather than a bare threshold. "14
           * days" alone told you the rule but not whether this source was
           * within it.
           */}
          <div>
            <dt className="text-[11px] font-medium tracking-wide text-[var(--text-tertiary)] uppercase">
              Freshness
            </dt>
            <dd className="mt-0.5 text-sm">
              <DaysRemaining days={source.stalenessThresholdDays - days} />
              <span className="ml-1.5 text-xs text-[var(--text-tertiary)]">
                of {source.stalenessThresholdDays} days
              </span>
            </dd>
          </div>
        </dl>

        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <p className="text-xs font-medium text-[var(--text-secondary)]">Parse coverage</p>
            <span className="tabular text-xs text-[var(--text-tertiary)]">{source.coverage}%</span>
          </div>
          <Meter
            value={source.coverage}
            tone={source.coverage >= 80 ? 'ok' : source.coverage >= 50 ? 'warn' : 'danger'}
            label="Parse coverage"
          />
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
            {100 - source.coverage}% of this source could not be parsed into graph nodes. Meridian
            treats unparsed regions as blind spots and declares them on any analysis that touches
            this source.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          icon={<ExternalLink className="size-3.5" aria-hidden="true" />}
        >
          Open in {source.provider}
        </Button>
      </div>
    </Drawer>
  )
}

const CONNECTORS = [
  {
    name: 'Workday',
    kind: 'Packaged platform',
    detail: 'Tenant config, business processes, reports',
  },
  {
    name: 'SAP S/4HANA',
    kind: 'Packaged platform',
    detail: 'Customizing tables, ABAP objects, IDocs',
  },
  { name: 'Dynamics 365', kind: 'Packaged platform', detail: 'Dataverse schema, flows, plugins' },
  { name: 'GitHub', kind: 'Repository', detail: 'Code symbols, dependency graph, history' },
  { name: 'Confluence', kind: 'Wiki', detail: 'Spaces, pages, decision records' },
  { name: 'Figma', kind: 'Design', detail: 'Frames, components, prototype flows' },
]

function AddSourceModal({
  open,
  onClose,
  onConnect,
}: {
  open: boolean
  onClose: () => void
  onConnect: (name: string) => void
}) {
  const [picked, setPicked] = useState<string | null>(null)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Connect a knowledge source"
      description="Meridian reads in advisory mode only. No connector is granted write access to a production system."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!picked} onClick={() => picked && onConnect(picked)}>
            Continue
          </Button>
        </>
      }
    >
      <fieldset>
        <legend className="sr-only">Available connectors</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {CONNECTORS.map((c) => {
            const active = picked === c.name
            return (
              <button
                key={c.name}
                type="button"
                aria-pressed={active}
                onClick={() => setPicked(c.name)}
                className={cn(
                  'cursor-pointer rounded-lg border p-3 text-left transition-colors duration-200',
                  active
                    ? 'border-[var(--accent)] bg-[var(--accent-subtle)]'
                    : 'border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]',
                )}
              >
                <p className="text-sm font-medium text-[var(--text-primary)]">{c.name}</p>
                <p className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">{c.kind}</p>
                <p className="mt-1.5 text-xs leading-snug text-[var(--text-secondary)]">
                  {c.detail}
                </p>
              </button>
            )
          })}
        </div>
      </fieldset>
    </Modal>
  )
}

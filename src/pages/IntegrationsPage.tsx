import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Blocks,
  Check,
  KeyRound,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Unplug,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SearchInput,
  Segmented,
  TableSkeleton,
} from '@/components/ui/primitives'
import { Modal, Tabs, useToast } from '@/components/ui/overlays'
import { IngestStatusBadge } from '@/components/domain/status'
import { BrandIcon } from '@/components/domain/BrandIcon'
import { BrowserSessionPanel } from '@/components/domain/BrowserSessionPanel'
import {
  ConnectorLimitations,
  RequiredArtifacts,
  SetupSteps,
} from '@/components/domain/ConnectorSetupGuide'
import {
  CredentialFieldsForm,
  missingFields,
  visibleFields,
} from '@/components/domain/CredentialFields'
import { api } from '@/lib/api'
import type { CredentialField } from '@/lib/api-live'
import { ApiError } from '@/lib/http'
import { useAsync, useAsyncList } from '@/lib/useAsync'
import { cn, relativeTime } from '@/lib/utils'
import { CURRENT_USER } from '@/lib/mock-data'
import type {
  AuthMethod,
  Connection,
  ConnectorCategory,
  ConnectorDefinition,
  SyncCadence,
} from '@/lib/mock-connectors'

const CATEGORY_LABEL: Record<ConnectorCategory, string> = {
  hcm: 'HCM',
  erp: 'ERP',
  ticketing: 'Ticketing',
  code: 'Code',
  docs: 'Documents',
  design: 'Design',
  messaging: 'Messaging',
  custom: 'Custom',
}

const AUTH_LABEL: Record<AuthMethod, string> = {
  oauth2: 'OAuth 2.0',
  api_key: 'API key',
  basic: 'Username and password',
  service_account: 'Service account',
  webhook: 'Inbound webhook',
}

const CADENCE_LABEL: Record<SyncCadence, string> = {
  realtime: 'Real time',
  hourly: 'Hourly',
  daily: 'Daily',
  weekly: 'Weekly',
  manual: 'Manual only',
}

/**
 * Ordering for the connected list. Anything needing a human comes first: a
 * page that lists connectors alphabetically makes you hunt for the broken one,
 * which is the only reason most people open this screen.
 */
const ATTENTION_RANK: Record<Connection['status'], number> = {
  error: 0,
  disconnected: 1,
  stale: 2,
  syncing: 3,
  indexing: 4,
  connected: 5,
}

const needsAttention = (c: Connection) =>
  c.status === 'error' || c.status === 'stale' || c.status === 'disconnected'

/** Status reduced to a dot plus a word, sized for a card corner. */
function StatusPip({ status }: { status: Connection['status'] }) {
  const map: Record<Connection['status'], { label: string; dot: string; text: string }> = {
    connected: { label: 'Connected', dot: 'bg-[var(--ok-solid)]', text: 'text-[var(--ok)]' },
    syncing: { label: 'Syncing', dot: 'bg-[var(--info-solid)]', text: 'text-[var(--info)]' },
    indexing: { label: 'Indexing', dot: 'bg-[var(--info-solid)]', text: 'text-[var(--info)]' },
    stale: { label: 'Stale', dot: 'bg-[var(--warn-solid)]', text: 'text-[var(--warn)]' },
    error: { label: 'Error', dot: 'bg-[var(--danger-solid)]', text: 'text-[var(--danger)]' },
    disconnected: {
      label: 'Disconnected',
      dot: 'bg-[var(--neutral-solid)]',
      text: 'text-[var(--text-tertiary)]',
    },
  }
  const s = map[status]
  const live = status === 'syncing' || status === 'indexing'
  return (
    <span className={cn('flex shrink-0 items-center gap-1.5 text-[11px] font-medium', s.text)}>
      <span
        className={cn('size-1.5 rounded-full', s.dot, live && 'animate-pulse')}
        aria-hidden="true"
      />
      {s.label}
    </span>
  )
}

export function IntegrationsPage() {
  /*
   * A nonce rather than a reload callback: useAsyncList re-runs on dependency
   * change, so bumping this is the refetch. Keeps the mutation path honest —
   * the list always comes from the API, never from a locally patched copy that
   * could drift from what the server actually did.
   */
  const [nonce, setNonce] = useState(0)
  const reload = () => setNonce((n) => n + 1)

  const { items: connections, loading } = useAsyncList(() => api.getConnections(), [nonce])
  const { items: connectors } = useAsyncList(() => api.getConnectors(), [nonce])
  const [tab, setTab] = useState('connected')
  const [query, setQuery] = useState('')
  const [detail, setDetail] = useState<Connection | null>(null)
  const [connecting, setConnecting] = useState<ConnectorDefinition | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const { push } = useToast()

  const byId = useMemo(
    () => new Map(connectors.map((c) => [c.id, c] as const)),
    [connectors],
  )

  const attention = connections.filter(needsAttention)

  const sortedConnections = useMemo(() => {
    const q = query.trim().toLowerCase()
    return [...connections]
      .filter((c) => {
        if (!q) return true
        const def = byId.get(c.connectorId)
        return `${def?.name ?? ''} ${c.label} ${c.owner}`.toLowerCase().includes(q)
      })
      .sort((a, b) => ATTENTION_RANK[a.status] - ATTENTION_RANK[b.status])
  }, [connections, query, byId])

  /**
   * The full catalogue, filtered only by search.
   *
   * Deliberately not "connectors you have not connected yet". Hiding a
   * connected one made the tab count (11) disagree with what was on screen (6),
   * and it is legitimate to want a second instance — a sandbox tenant beside
   * production, or a second Jira project. Cards say how many are already
   * connected instead, and the button reads "Add another".
   */
  const available = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return connectors
    return connectors.filter((c) =>
      `${c.name} ${c.vendor} ${CATEGORY_LABEL[c.category]}`.toLowerCase().includes(q),
    )
  }, [connectors, query])

  async function runTest(conn: Connection) {
    setBusy(conn.id)
    const result = await api.testConnection(conn.id)
    setBusy(null)
    push({
      title: result.ok ? 'Connection healthy' : 'Connection failed',
      description: result.message,
      tone: result.ok ? 'ok' : 'danger',
    })
  }

  async function runSync(conn: Connection) {
    setBusy(conn.id)
    await api.syncConnection(conn.id)
    setBusy(null)
    reload()
    push({ title: 'Sync started', description: `${conn.label} is refreshing now.`, tone: 'ok' })
  }

  async function runDisconnect(conn: Connection) {
    setBusy(conn.id)
    await api.disconnectConnection(conn.id)
    setBusy(null)
    setDetail(null)
    reload()
    push({
      title: 'Disconnected',
      // Says what was kept, because "disconnect" reads as "delete" and people
      // hesitate over an irreversible-sounding button.
      description: 'Indexed data and past evidence are kept. Nothing new will be pulled.',
      tone: 'warn',
    })
  }

  return (
    <>
      <PageHeader
        title="Integrations"
        icon={<Blocks aria-hidden="true" />}
        tone="accent"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={<Plus className="size-4" />} onClick={() => setCustomOpen(true)}>
              Custom connector
            </Button>
          </div>
        }
      />

      <PageBody>
        {/*
         * Attention banner. The count is also on the sidebar, but a number in
         * a rail tells you something is wrong without telling you what — this
         * names the connector and the reason in one line.
         */}
        {attention.length > 0 ? (
          <Card className="mb-4 border-[var(--danger-border)] bg-[var(--danger-subtle)] p-4">
            <div className="flex items-start gap-3">
              <ShieldAlert
                className="mt-0.5 size-4 shrink-0 text-[var(--danger)]"
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-semibold text-[var(--text-primary)]">
                  {attention.length} connection{attention.length === 1 ? '' : 's'} need attention
                </p>
                <p className="mt-0.5 text-[12px] text-[var(--text-secondary)]">
                  While a connector is down, anything it feeds is working from the last data it
                  managed to pull. Evidence gathered now may be incomplete.
                </p>
                <ul className="mt-2 space-y-1">
                  {attention.map((c) => (
                    <li key={c.id} className="text-[12px] text-[var(--text-secondary)]">
                      <button
                        onClick={() => setDetail(c)}
                        className="cursor-pointer font-medium text-[var(--text-primary)] underline underline-offset-2"
                      >
                        {byId.get(c.connectorId)?.name ?? c.connectorId} — {c.label}
                      </button>
                      {c.error ? <span> · {c.error}</span> : null}
                      {c.status === 'stale' && c.lastSyncedAt ? (
                        <span> · last synced {relativeTime(c.lastSyncedAt)}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Card>
        ) : null}

        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Tabs
            items={[
              { id: 'connected', label: 'Connected', count: connections.length },
              { id: 'browse', label: 'Browse connectors', count: connectors.length },
            ]}
            value={tab}
            onChange={setTab}
          />
          <SearchInput
            value={query}
            onChange={setQuery}
            label="Search integrations"
            placeholder={tab === 'connected' ? 'Search connections…' : 'Search connectors…'}
            icon={<Search className="size-4" />}
            className="sm:w-64"
          />
        </div>

        {tab === 'connected' ? (
          loading ? (
            <TableSkeleton rows={5} cols={4} />
          ) : sortedConnections.length === 0 ? (
            <EmptyState
              icon={<Plug className="size-5" />}
              title={query ? 'No matching connections' : 'Nothing connected yet'}
              description={
                query
                  ? 'No connection matches that search.'
                  : 'Connect a system to start building the change record.'
              }
            />
          ) : (
            // Cards stretch to a uniform height per row (grid's default), and
            // each card's internal layout fills that height — see the h-full
            // flex column below. items-start was tried and made every card a
            // different size, which is worse: a ragged grid reads as broken.
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {sortedConnections.map((conn) => {
                const def = byId.get(conn.connectorId)
                return (
                  <li key={conn.id}>
                    {/*
                     * The whole card opens Manage. Previously the only way in
                     * was a small button in the corner, which left most of a
                     * 300px target inert.
                     */}
                    <Card
                      onClick={() => setDetail(conn)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          setDetail(conn)
                        }
                      }}
                      tabIndex={0}
                      role="button"
                      aria-label={`Manage ${def?.name ?? conn.connectorId} — ${conn.label}`}
                      className={cn(
                        'group/card relative flex h-full cursor-pointer flex-col p-4',
                        'transition-[border-color,box-shadow] duration-200',
                        'hover:border-[var(--border-strong)] hover:shadow-[var(--shadow-md)]',
                        'focus-visible:ring-2 focus-visible:ring-[var(--accent)]/30 focus-visible:outline-none',
                        // A failing connector is edged in red rather than only
                        // labelled, so a wall of cards can be triaged at a glance.
                        conn.status === 'error' && 'border-[var(--danger-border)]',
                        conn.status === 'stale' && 'border-[var(--warn-border)]',
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <BrandIcon name={def?.name ?? conn.connectorId} size="lg" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[14px] font-semibold text-[var(--text-primary)]">
                            {def?.name ?? conn.connectorId}
                          </p>
                          <p className="truncate text-[12px] text-[var(--text-tertiary)]">
                            {conn.label}
                          </p>
                          <div className="mt-1.5">
                            <StatusPip status={conn.status} />
                          </div>
                        </div>
                      </div>

                      {/*
                       * One meta line instead of a 2×2 grid of uppercase
                       * labels. The labels were larger than the values they
                       * described; separators carry the same structure at a
                       * fraction of the ink.
                       */}
                      <p className="mt-3 truncate text-[11px] text-[var(--text-tertiary)]">
                        <span className="text-[var(--text-secondary)]">
                          {conn.lastSyncedAt ? relativeTime(conn.lastSyncedAt) : 'Never synced'}
                        </span>
                        {' · '}
                        {CADENCE_LABEL[conn.cadence]}
                        {' · '}
                        {conn.owner}
                      </p>

                      {conn.recordCount > 0 ? (
                        <p className="numeral mt-1 text-[11px] text-[var(--text-tertiary)]">
                          {conn.recordCount.toLocaleString()} records · {AUTH_LABEL[conn.authMethod]}
                        </p>
                      ) : (
                        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                          {AUTH_LABEL[conn.authMethod]}
                        </p>
                      )}

                      {/*
                       * Clamped to one line. Cards in a row stretch to the
                       * tallest, so an unclamped three-line error inflated
                       * every neighbour. The full text is in Manage.
                       */}
                      {conn.error ? (
                        <p className="mt-2.5 flex items-start gap-1.5 rounded-lg bg-[var(--danger-subtle)] px-2 py-1.5 text-[11px] leading-snug text-[var(--danger)]">
                          <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
                          <span className="line-clamp-1">{conn.error}</span>
                        </p>
                      ) : null}

                      {/*
                       * mt-auto pins the actions to the bottom of the stretched
                       * card, so buttons line up across the row instead of
                       * floating at a different height on every card.
                       *
                       * Kept in the layout and only faded: revealing them by
                       * changing display would resize the card and shove the
                       * grid about as the pointer moves. focus-within matters
                       * too — without it these are unreachable by keyboard,
                       * which is how "reveal on hover" usually breaks.
                       */}
                      <div
                        className={cn(
                          'mt-auto flex items-center gap-2 pt-3',
                          'opacity-0 transition-opacity duration-200',
                          'group-hover/card:opacity-100 group-focus-within/card:opacity-100',
                        )}
                      >
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={(e) => {
                            e.stopPropagation()
                            setDetail(conn)
                          }}
                        >
                          Manage
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={busy === conn.id}
                          onClick={(e) => {
                            e.stopPropagation()
                            runTest(conn)
                          }}
                        >
                          Test
                        </Button>
                      </div>
                    </Card>
                  </li>
                )
              })}
            </ul>
          )
        ) : (
          <BrowseConnectors
            connectors={available}
            connections={connections}
            onConnect={setConnecting}
            onCustom={() => setCustomOpen(true)}
          />
        )}
      </PageBody>

      {detail ? (
        <ManageConnection
          connection={detail}
          definition={byId.get(detail.connectorId) ?? null}
          busy={busy === detail.id}
          onClose={() => setDetail(null)}
          onTest={() => runTest(detail)}
          onSync={() => runSync(detail)}
          onDisconnect={() => runDisconnect(detail)}
          onCadence={async (cadence) => {
            await api.setConnectionCadence(detail.id, cadence)
            reload()
            push({ title: 'Schedule updated', description: `Now syncing ${CADENCE_LABEL[cadence].toLowerCase()}.`, tone: 'ok' })
          }}
        />
      ) : null}

      {connecting ? (
        <ConnectWizard
          definition={connecting}
          onClose={() => setConnecting(null)}
          onDone={async () => {
            setConnecting(null)
            reload()
            setTab('connected')
            push({
              title: 'Connected',
              description: 'The first sync is running. Data appears as it is indexed.',
              tone: 'ok',
            })
          }}
        />
      ) : null}

      {customOpen ? (
        <CustomConnectorModal
          onClose={() => setCustomOpen(false)}
          onDone={async () => {
            setCustomOpen(false)
            // Refetch before switching tabs: the toast promises the connector
            // "now appears under Browse", and without this the list still
            // holds the pre-creation catalogue and it does not.
            reload()
            push({
              title: 'Custom connector registered',
              description: 'It now appears under Browse connectors, ready to connect.',
              tone: 'ok',
            })
            setTab('browse')
          }}
        />
      ) : null}
    </>
  )
}

/* --------------------------------------------------------------- browse tab */

function BrowseConnectors({
  connectors,
  connections,
  onConnect,
  onCustom,
}: {
  connectors: ConnectorDefinition[]
  connections: Connection[]
  onConnect: (c: ConnectorDefinition) => void
  onCustom: () => void
}) {
  const [category, setCategory] = useState<'all' | ConnectorCategory>('all')

  const shown = connectors.filter((c) => category === 'all' || c.category === category)

  /* Only offer filters that would actually return something. */
  const categories = Array.from(new Set(connectors.map((c) => c.category)))

  return (
    <>
      <div className="mb-3">
        <Segmented
          label="Filter by category"
          value={category}
          onChange={setCategory}
          options={[
            { id: 'all' as const, label: 'All' },
            ...categories.map((c) => ({ id: c, label: CATEGORY_LABEL[c] })),
          ]}
        />
      </div>

      {shown.length === 0 ? (
        <EmptyState
          icon={<Plug className="size-5" />}
          title="No connectors match"
          description="Nothing in this category matches your search."
          action={
            <Button variant="secondary" icon={<Plus className="size-4" />} onClick={onCustom}>
              Build a custom connector
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((def) => {
            const existing = connections.filter(
              (c) => c.connectorId === def.id && c.status !== 'disconnected',
            ).length
            return (
              <li key={def.id}>
                <Card
                  className={cn(
                    'flex h-full flex-col p-4 transition-[border-color,box-shadow] duration-200',
                    // Coming-soon tiles stay flat: a hover lift on something
                    // you cannot click is a promise the card does not keep.
                    !def.comingSoon &&
                      'hover:border-[var(--border-strong)] hover:shadow-[var(--shadow-md)]',
                    def.comingSoon && 'opacity-70',
                  )}
                >
                  <div className="flex items-start gap-3">
                    <BrandIcon name={def.name} size="lg" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14px] font-semibold text-[var(--text-primary)]">
                        {def.name}
                      </p>
                      <p className="truncate text-[12px] text-[var(--text-tertiary)]">
                        {def.vendor}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge tone="neutral">{CATEGORY_LABEL[def.category]}</Badge>
                      {def.custom ? <Badge tone="info">Custom</Badge> : null}
                    </div>
                  </div>

                  <p className="mt-3 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                    {def.description}
                  </p>

                  {/* What it contributes, so the choice is about outcome rather
                      than brand recognition. */}
                  <ul className="mt-3 space-y-1">
                    {def.provides.map((p) => (
                      <li
                        key={p}
                        className="flex items-start gap-1.5 text-[11px] text-[var(--text-tertiary)]"
                      >
                        <Check className="mt-px size-3 shrink-0 text-[var(--ok)]" aria-hidden="true" />
                        {p}
                      </li>
                    ))}
                  </ul>

                  <div className="mt-auto flex items-center gap-2 pt-3">
                    {def.comingSoon ? (
                      <Badge tone="neutral">Coming soon</Badge>
                    ) : (
                      <Button size="sm" variant="secondary" onClick={() => onConnect(def)}>
                        {existing ? 'Add another' : 'Connect'}
                      </Button>
                    )}
                    {existing ? (
                      <span className="text-[11px] text-[var(--text-tertiary)]">
                        {existing} connected
                      </span>
                    ) : null}
                  </div>
                </Card>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}

/* ------------------------------------------------------------ connect flow */

/**
 * Four steps: what to do in the source system, how to authenticate, what to
 * grant, when to sync.
 *
 * The first step is new and is the reason this is a wizard rather than a form.
 * Connecting Workday means creating an integration user, a security group,
 * granting domains, activating the policy change, registering an API client
 * and minting a refresh token — before a single field on this screen can be
 * filled in. A form that opens by demanding a token endpoint from someone who
 * has not done any of that is a form they abandon.
 *
 * Scopes keep their own screen: granting them is a decision with consequences
 * and buried among other fields it gets clicked past, which is how
 * integrations end up with more access than anyone intended.
 */
function ConnectWizard({
  definition,
  onClose,
  onDone,
}: {
  definition: ConnectorDefinition
  onClose: () => void
  onDone: () => void
}) {
  const { data: setup } = useAsync(
    () => api.getConnectorSetup(definition.id),
    [definition.id],
  )

  const [step, setStep] = useState(0)
  const [authMethod, setAuthMethod] = useState<AuthMethod>(definition.authMethods[0] ?? 'oauth2')
  const [label, setLabel] = useState('')
  const [owner, setOwner] = useState('')
  const [optional, setOptional] = useState<Set<string>>(new Set())
  const [cadence, setCadence] = useState<SyncCadence>('daily')
  const [saving, setSaving] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [showMissing, setShowMissing] = useState(false)
  const [error, setError] = useState<string[] | null>(null)
  const { push } = useToast()

  const fields = setup?.credentialFields ?? []
  const hasSetupWork = Boolean(setup?.setupSteps?.length)

  /*
   * Steps are built from what this connector actually needs. A connector with
   * no tenant-side setup and no credential fields shows two steps, not four —
   * padding a simple flow to match a complex one wastes the user's clicks.
   */
  const STEPS = [
    ...(hasSetupWork ? ['Before you start'] : []),
    ...(fields.length ? ['Connect'] : ['Authenticate']),
    'Permissions',
    'Schedule',
  ]
  const stepName = STEPS[step]

  const required = definition.scopes.filter((s) => s.required)
  const optionalScopes = definition.scopes.filter((s) => !s.required)
  /*
   * Includes required writes, not only ticked optional ones. Slack cannot post
   * an approval request without write access, so its write scope is mandatory
   * — and a mandatory write is exactly the kind a security reviewer most needs
   * told about, not the kind to stay silent on because there was no checkbox.
   */
  const writeScopes = definition.scopes.filter(
    (s) => s.writes && (s.required || optional.has(s.id)),
  )

  const gaps = fields.length
    ? missingFields(fields, values, values.method ?? '')
    : []

  function setValue(id: string, value: string) {
    setValues((prev) => ({ ...prev, [id]: value }))
    setShowMissing(false)
    setError(null)
  }

  function advance() {
    // Validate before leaving the credential step, so a missing token endpoint
    // is caught here rather than after the user has also picked scopes and a
    // schedule and pressed Connect.
    if (stepName === 'Connect' && gaps.length) {
      setShowMissing(true)
      return
    }
    setStep((s) => s + 1)
  }

  async function submit() {
    if (gaps.length) {
      setShowMissing(true)
      setError(gaps)
      return
    }

    setSaving(true)
    setError(null)
    try {
      await api.createConnection({
        connectorId: definition.id,
        label,
        authMethod,
        grantedScopes: [...optional],
        cadence,
        owner: owner.trim() || CURRENT_USER.name,
        values,
      })
      onDone()
    } catch (err) {
      // The server's refusal is the useful part — it names which values are
      // missing or why the credentials were rejected. Flattening it to
      // "something went wrong" would discard the only actionable content.
      const reasons =
        err instanceof ApiError && err.reasons.length
          ? err.reasons
          : [err instanceof Error ? err.message : String(err)]
      setError(reasons)
      push({
        title: 'Could not connect',
        description: reasons[0],
        tone: 'danger',
      })
    } finally {
      setSaving(false)
    }
  }

  const fieldClass =
    'h-9 w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 text-[13px] text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10'

  return (
    <Modal
      open
      onClose={onClose}
      title={`Connect ${definition.name}`}
      description={definition.vendor}
      icon={<BrandIcon name={definition.name} size="md" />}
      size="lg"
    >
      {/* Step indicator. Three dots and a label beat a progress bar here: the
          steps are named, and a bar would imply duration rather than position. */}
      <ol className="mb-4 flex items-center gap-2" aria-label="Connection steps">
        {STEPS.map((name, i) => (
          <li key={name} className="flex items-center gap-2">
            <span
              className={cn(
                'flex size-5 items-center justify-center rounded-full text-[10px] font-bold',
                i < step
                  ? 'bg-[var(--ok)] text-white'
                  : i === step
                    ? 'bg-[var(--accent)] text-[var(--accent-on)]'
                    : 'border border-[var(--border-default)] text-[var(--text-tertiary)]',
              )}
              aria-current={i === step ? 'step' : undefined}
            >
              {i < step ? <Check className="size-3" aria-hidden="true" /> : i + 1}
            </span>
            <span
              className={cn(
                'text-[12px]',
                i === step
                  ? 'font-semibold text-[var(--text-primary)]'
                  : 'text-[var(--text-tertiary)]',
              )}
            >
              {name}
            </span>
            {i < STEPS.length - 1 ? (
              <span className="h-px w-4 bg-[var(--border-default)]" aria-hidden="true" />
            ) : null}
          </li>
        ))}
      </ol>

      {stepName === 'Before you start' ? (
        <div className="space-y-4">
          {setup?.limitations?.length ? (
            <ConnectorLimitations items={setup.limitations} />
          ) : null}
          <SetupSteps steps={setup?.setupSteps ?? []} vendor={definition.name} />
          {setup?.requiredArtifacts?.length ? (
            <RequiredArtifacts
              artifacts={setup.requiredArtifacts}
              vendor={definition.name}
              buildSteps={setup.artifactBuildSteps}
            />
          ) : null}
        </div>
      ) : null}

      {stepName === 'Connect' ? (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="cx-label"
                className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
              >
                Name this connection
              </label>
              <input
                id="cx-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Implementation Tenant"
                className={fieldClass}
              />
              <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                You will have more than one. Name it after the environment.
              </p>
            </div>
            <div>
              <label
                htmlFor="cx-owner"
                className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
              >
                Owning team
              </label>
              <input
                id="cx-owner"
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="HR Systems"
                className={fieldClass}
              />
              <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                Who to ask when this breaks at 2am.
              </p>
            </div>
          </div>

          <CredentialFieldsForm
            fields={fields}
            values={values}
            onChange={setValue}
            showMissing={showMissing}
            secretsConfigured={setup?.secretsConfigured ?? true}
          />

          {error ? (
            <div className="rounded-lg border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-2.5">
              <p className="flex items-start gap-1.5 text-[12px] font-medium text-[var(--danger)]">
                <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                Could not connect
              </p>
              <ul className="mt-1 space-y-0.5 pl-5">
                {error.map((reason) => (
                  <li key={reason} className="text-[11px] text-[var(--danger)]">
                    {reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {stepName === 'Authenticate' ? (
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]">
              Authentication method
            </label>
            <div className="space-y-2">
              {definition.authMethods.map((m) => (
                <label
                  key={m}
                  className={cn(
                    'flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 transition-colors',
                    authMethod === m
                      ? 'border-[var(--accent-border)] bg-[var(--accent-subtle)]'
                      : 'border-[var(--border-subtle)] hover:bg-[var(--bg-hover)]',
                  )}
                >
                  <input
                    type="radio"
                    name="auth"
                    checked={authMethod === m}
                    onChange={() => setAuthMethod(m)}
                    className="mt-0.5 size-3.5 accent-[var(--accent)]"
                  />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-[var(--text-primary)]">
                      {AUTH_LABEL[m]}
                    </span>
                    <span className="block text-[11px] text-[var(--text-tertiary)]">
                      {m === 'oauth2'
                        ? 'Recommended. You approve access in ' +
                          definition.vendor +
                          ', and Meridian never sees a password.'
                        : m === 'service_account'
                          ? 'For unattended syncs that must survive someone leaving the company.'
                          : m === 'api_key'
                            ? 'A token you paste here. Rotate it on your own schedule.'
                            : 'Least preferred — credentials are stored rather than delegated.'}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="cx-label"
                className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
              >
                Name this connection
              </label>
              <input
                id="cx-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Production Tenant"
                className={fieldClass}
              />
              <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                You will have more than one. Name it after the environment.
              </p>
            </div>
            <div>
              <label
                htmlFor="cx-owner"
                className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
              >
                Owning team
              </label>
              <input
                id="cx-owner"
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="HR Systems"
                className={fieldClass}
              />
              <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                Who to ask when this breaks at 2am.
              </p>
            </div>
          </div>
        </div>
      ) : null}

      {stepName === 'Permissions' ? (
        <div className="space-y-4">
          <div>
            <p className="text-[12px] font-semibold text-[var(--text-primary)]">
              Always granted
            </p>
            <p className="mb-2 text-[11px] text-[var(--text-tertiary)]">
              {definition.name} cannot do its job without these, so they are not optional.
            </p>
            <ul className="space-y-1.5">
              {required.map((s) => (
                <li
                  key={s.id}
                  className="flex items-start gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-2.5"
                >
                  <Check className="mt-0.5 size-3.5 shrink-0 text-[var(--ok)]" aria-hidden="true" />
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      <span className="text-[12px] font-medium text-[var(--text-primary)]">
                        {s.label}
                      </span>
                      {/* A required scope can still be a write. Flagging it
                          here is the only place that fact surfaces, since
                          there is no checkbox to attach it to. */}
                      {s.writes ? <Badge tone="warn">Can write</Badge> : null}
                    </span>
                    <span className="block text-[11px] text-[var(--text-tertiary)]">
                      {s.description}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {optionalScopes.length ? (
            <div>
              <p className="text-[12px] font-semibold text-[var(--text-primary)]">Optional</p>
              <p className="mb-2 text-[11px] text-[var(--text-tertiary)]">
                Grant only what you need. Each one can be added later without reconnecting.
              </p>
              <ul className="space-y-1.5">
                {optionalScopes.map((s) => {
                  const on = optional.has(s.id)
                  return (
                    <li key={s.id}>
                      <label
                        className={cn(
                          'flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 transition-colors',
                          on
                            ? 'border-[var(--accent-border)] bg-[var(--accent-subtle)]'
                            : 'border-[var(--border-subtle)] hover:bg-[var(--bg-hover)]',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() =>
                            setOptional((prev) => {
                              const next = new Set(prev)
                              if (next.has(s.id)) next.delete(s.id)
                              else next.add(s.id)
                              return next
                            })
                          }
                          className="mt-0.5 size-3.5 accent-[var(--accent)]"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="text-[12px] font-medium text-[var(--text-primary)]">
                              {s.label}
                            </span>
                            {/* A write scope is a different order of risk from
                                a read one, and should say so before it is
                                ticked, not in a support ticket afterwards. */}
                            {s.writes ? <Badge tone="warn">Can write</Badge> : null}
                          </span>
                          <span className="block text-[11px] text-[var(--text-tertiary)]">
                            {s.description}
                          </span>
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null}

          {writeScopes.length ? (
            <p className="flex items-start gap-1.5 rounded-lg bg-[var(--warn-subtle)] p-2.5 text-[11px] text-[var(--warn)]">
              <AlertTriangle className="mt-px size-3 shrink-0" aria-hidden="true" />
              This connection will be able to change data in {definition.vendor}. Every write is
              recorded in the audit chain.
            </p>
          ) : null}
        </div>
      ) : null}

      {stepName === 'Schedule' ? (
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]">
              Sync frequency
            </label>
            <div className="space-y-2">
              {(['realtime', 'hourly', 'daily', 'weekly', 'manual'] as SyncCadence[]).map((c) => (
                <label
                  key={c}
                  className={cn(
                    'flex cursor-pointer items-center gap-2.5 rounded-lg border p-2.5 transition-colors',
                    cadence === c
                      ? 'border-[var(--accent-border)] bg-[var(--accent-subtle)]'
                      : 'border-[var(--border-subtle)] hover:bg-[var(--bg-hover)]',
                  )}
                >
                  <input
                    type="radio"
                    name="cadence"
                    checked={cadence === c}
                    onChange={() => setCadence(c)}
                    className="size-3.5 accent-[var(--accent)]"
                  />
                  <span className="text-[13px] font-medium text-[var(--text-primary)]">
                    {CADENCE_LABEL[c]}
                  </span>
                  {c === 'daily' ? (
                    <Badge tone="neutral" className="ml-auto">
                      Recommended
                    </Badge>
                  ) : null}
                </label>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
            <p className="text-[12px] font-semibold text-[var(--text-primary)]">Summary</p>
            <dl className="mt-2 space-y-1 text-[12px]">
              <div className="flex justify-between gap-3">
                <dt className="text-[var(--text-tertiary)]">Connection</dt>
                <dd className="text-right text-[var(--text-secondary)]">
                  {label.trim() || definition.name}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-[var(--text-tertiary)]">Authentication</dt>
                <dd className="text-right text-[var(--text-secondary)]">{AUTH_LABEL[authMethod]}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-[var(--text-tertiary)]">Permissions</dt>
                <dd className="text-right text-[var(--text-secondary)]">
                  {required.length + optional.size} granted
                  {writeScopes.length ? `, ${writeScopes.length} can write` : ', read only'}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}

      <div className="mt-5 flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] pt-4">
        <Button
          variant="ghost"
          icon={<ArrowLeft className="size-4" />}
          onClick={() => (step === 0 ? onClose() : setStep((s) => s - 1))}
        >
          {step === 0 ? 'Cancel' : 'Back'}
        </Button>
        {step < STEPS.length - 1 ? (
          <Button variant="primary" onClick={advance}>
            Continue
          </Button>
        ) : (
          <Button variant="primary" loading={saving} onClick={submit}>
            Connect {definition.name}
          </Button>
        )}
      </div>
    </Modal>
  )
}

/* ----------------------------------------------------------- manage a live one */

function ManageConnection({
  connection,
  definition,
  busy,
  onClose,
  onTest,
  onSync,
  onDisconnect,
  onCadence,
}: {
  connection: Connection
  definition: ConnectorDefinition | null
  busy: boolean
  onClose: () => void
  onTest: () => void
  onSync: () => void
  onDisconnect: () => void
  onCadence: (c: SyncCadence) => void
}) {
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)
  const [tab, setTab] = useState('overview')
  const [limitationsOpen, setLimitationsOpen] = useState(false)

  /*
   * The setup guide is fetched here as well as in the wizard. A connection that
   * never completed — no credentials, or a tenant step skipped — is exactly the
   * case where someone needs the checklist again, and closing the wizard used
   * to be the only way to reach it. Reopening a connection has to be a way
   * forward, not a dead end with a disabled Sync button.
   */
  const { data: setup } = useAsync(
    () => (definition ? api.getConnectorSetup(definition.id) : Promise.resolve(null)),
    [definition?.id],
  )

  const granted = (definition?.scopes ?? []).filter((s) =>
    connection.grantedScopes.includes(s.id),
  )

  /*
   * Session status, refetched on demand rather than polled. A session's
   * remaining time is displayed in minutes, so a ticking countdown would be
   * churn for no information; the panel reloads after any action that changes
   * it.
   */
  const [sessionNonce, setSessionNonce] = useState(0)
  const usesBrowser = connection.grantedScopes.includes('discover.browser')
  const { data: browserSession } = useAsync(
    () =>
      usesBrowser
        ? api.getBrowserSession(connection.id)
        : Promise.resolve(null),
    [connection.id, usesBrowser, sessionNonce],
  )
  const reloadSession = () => setSessionNonce((n) => n + 1)

  const fields = setup?.credentialFields ?? []
  const hasSetupWork = Boolean(setup?.setupSteps?.length)
  const limitations = setup?.limitations ?? []

  /*
   * Sync state is a separate fact from connection status: a connection can be
   * authenticated and still never have pulled a record, which looks identical
   * to a healthy one until someone asks why the graph is empty.
   */
  const syncSummary = connection.lastSyncedAt
    ? `Synced ${relativeTime(connection.lastSyncedAt)}`
    : 'Never synced'

  const tabs = [
    { id: 'overview', label: 'Overview' },
    ...(fields.length ? [{ id: 'credentials', label: 'Credentials' }] : []),
    ...(hasSetupWork ? [{ id: 'setup', label: 'Setup guide' }] : []),
  ]

  return (
    <Modal
      open
      onClose={onClose}
      /*
       * The label leads, since it is what distinguishes one connection from
       * another; the system it belongs to is named underneath rather than
       * prefixed, so a long tenant name never pushes it off the line. Status
       * sits here too — whether this thing is working is the first question
       * anyone opening it has, and it should not depend on which tab is open.
       */
      title={connection.label}
      description={definition?.name ?? connection.connectorId}
      icon={<BrandIcon name={definition?.name ?? connection.connectorId} size="md" />}
      meta={
        <>
          <IngestStatusBadge status={connection.status} />
          <span className="text-[11px] text-[var(--text-tertiary)]">{syncSummary}</span>
          {/*
           * Limitations are a property of the connector, so they belong beside
           * the connector's identity rather than buried in one tab. The button
           * carries the count and the noun — an icon alone reads as decoration
           * and gets no clicks.
           */}
          {limitations.length ? (
            <button
              type="button"
              onClick={() => {
                setTab('setup')
                setLimitationsOpen(true)
              }}
              className="flex cursor-pointer items-center gap-1 rounded-full border border-[var(--warn-border)] bg-[var(--warn-subtle)] px-2 py-0.5 text-[11px] font-medium text-[var(--warn)] transition-colors hover:brightness-[0.97]"
            >
              <AlertTriangle className="size-3" aria-hidden="true" />
              {limitations.length} {limitations.length === 1 ? 'limitation' : 'limitations'}
            </button>
          ) : null}
        </>
      }
      size="lg"
      headerNav={
        tabs.length > 1 ? <Tabs items={tabs} value={tab} onChange={setTab} /> : null
      }
    >
      {tab === 'credentials' ? (
        <ConnectionCredentials
          connection={connection}
          fields={fields}
          secretsConfigured={setup?.secretsConfigured ?? true}
        />
      ) : tab === 'setup' ? (
        <div className="space-y-4">
          {limitations.length ? (
            <ConnectorLimitations
              items={limitations}
              open={limitationsOpen}
              onOpenChange={setLimitationsOpen}
            />
          ) : null}
          <SetupSteps steps={setup?.setupSteps ?? []} vendor={definition?.name ?? 'the system'} />
          {/*
           * Only when the connection was granted browser discovery. Showing a
           * capture panel to someone who did not enable the scope offers work
           * that would achieve nothing.
           */}
          {connection.grantedScopes.includes('discover.browser') ? (
            <BrowserSessionPanel
              connectionId={connection.id}
              session={browserSession ?? null}
              onChange={reloadSession}
            />
          ) : null}
          {setup?.requiredArtifacts?.length ? (
            <RequiredArtifacts
              artifacts={setup.requiredArtifacts}
              vendor={definition?.name ?? 'the system'}
              buildSteps={setup.artifactBuildSteps}
            />
          ) : null}
        </div>
      ) : (
      <div className="space-y-4">
        {/* Brand mark and status now live in the header, beside the title. */}
        <p className="text-[12px] text-[var(--text-tertiary)]">
          Connected by {connection.connectedBy} · {relativeTime(connection.connectedAt)}
        </p>

        {connection.error ? (
          <p className="flex items-start gap-1.5 rounded-lg border border-[var(--danger-border)] bg-[var(--danger-subtle)] p-2.5 text-[12px] text-[var(--danger)]">
            <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            {connection.error}
          </p>
        ) : null}

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[
            // Last sync is in the header; repeating it here spends a cell on
            // something already answered two lines above.
            ['Records indexed', connection.recordCount.toLocaleString()],
            ['Next sync', connection.nextSyncAt ? relativeTime(connection.nextSyncAt) : '—'],
            ['Owner', connection.owner],
            ['Auth', AUTH_LABEL[connection.authMethod]],
            [
              'Last tested',
              connection.lastTestedAt ? relativeTime(connection.lastTestedAt) : 'Never',
            ],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[10px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
                {k}
              </dt>
              <dd className="mt-0.5 text-[13px] text-[var(--text-secondary)]">{v}</dd>
            </div>
          ))}
        </dl>

        <div>
          <p className="mb-1.5 text-[12px] font-semibold text-[var(--text-primary)]">
            Granted permissions
          </p>
          <ul className="space-y-1.5">
            {granted.map((s) => (
              <li
                key={s.id}
                className="flex items-start gap-2 rounded-lg border border-[var(--border-subtle)] p-2.5"
              >
                <KeyRound
                  className="mt-0.5 size-3.5 shrink-0 text-[var(--text-tertiary)]"
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="text-[12px] font-medium text-[var(--text-primary)]">
                      {s.label}
                    </span>
                    {s.writes ? <Badge tone="warn">Can write</Badge> : null}
                  </span>
                  <span className="block text-[11px] text-[var(--text-tertiary)]">
                    {s.description}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <label
            htmlFor="cadence-select"
            className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
          >
            Sync frequency
          </label>
          <select
            id="cadence-select"
            value={connection.cadence}
            onChange={(e) => onCadence(e.target.value as SyncCadence)}
            className="h-9 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 text-[13px] text-[var(--text-primary)]"
          >
            {(Object.keys(CADENCE_LABEL) as SyncCadence[]).map((c) => (
              <option key={c} value={c}>
                {CADENCE_LABEL[c]}
              </option>
            ))}
          </select>
        </div>
      </div>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border-subtle)] pt-4">
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" loading={busy} onClick={onTest}>
            Test connection
          </Button>
          <Button
            variant="secondary"
            icon={<RefreshCw className="size-4" />}
            loading={busy}
            onClick={onSync}
            disabled={connection.status === 'disconnected'}
          >
            Sync now
          </Button>
        </div>
        {connection.status === 'disconnected' ? null : confirmDisconnect ? (
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[var(--text-secondary)]">
              Stop syncing? Indexed data is kept.
            </span>
            <Button variant="danger" size="sm" loading={busy} onClick={onDisconnect}>
              Disconnect
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmDisconnect(false)}>
              Keep
            </Button>
          </div>
        ) : (
          <Button
            variant="ghost"
            icon={<Unplug className="size-4" />}
            onClick={() => setConfirmDisconnect(true)}
          >
            Disconnect
          </Button>
        )}
      </div>
    </Modal>
  )
}

/**
 * Edit the credentials on an existing connection.
 *
 * Stored secrets come back as a `••••••••` presence marker rather than a value,
 * so the form can show "a secret is stored" without the secret crossing the
 * wire. Leaving a masked field untouched keeps what is stored — the PATCH
 * merges rather than replaces, so clearing one field does not silently wipe the
 * rest of a working connection.
 */
function ConnectionCredentials({
  connection,
  fields,
  secretsConfigured,
}: {
  connection: Connection
  fields: CredentialField[]
  secretsConfigured: boolean
}) {
  // Bumped after a save so the read-only view reflects what was stored,
  // rather than the edits that happen to still be in local state.
  const [reloadNonce, setReloadNonce] = useState(0)
  const { data: stored, loading } = useAsync(
    () => api.getConnection(connection.id),
    [connection.id, reloadNonce],
  )
  const [values, setValues] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [showMissing, setShowMissing] = useState(false)
  const [editing, setEditing] = useState(false)
  const { push } = useToast()

  // Server values seed the form once loaded; edits win from then on.
  const current = useMemo(
    () => ({ ...(stored?.settings ?? {}), ...values }) as Record<string, string>,
    [stored, values],
  )

  /*
   * The form keys authentication off `values.method`, the same field the
   * wizard writes. A connection made before that was stored falls back to the
   * connection's own auth method so the right fields still appear.
   */
  const method = current.method || (connection.authMethod as string)
  const missing = missingFields(fields, current, method)

  async function save() {
    if (missing.length) {
      setShowMissing(true)
      return
    }
    setSaving(true)
    try {
      // Only what was actually edited — untouched masked fields keep their
      // stored value rather than being overwritten with bullet characters.
      await api.updateConnectionCredentials(connection.id, values)
      push({ title: 'Credentials updated', tone: 'ok' })
      setValues({})
      setTouched(false)
      setEditing(false)
      setReloadNonce((n) => n + 1)
    } catch (err) {
      const reasons = err instanceof ApiError ? err.reasons : []
      push({
        title: 'Could not save credentials',
        description: reasons.length ? reasons.join(', ') : String(err),
        tone: 'danger',
      })
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <TableSkeleton rows={4} />

  /*
   * Read-only until asked otherwise. These are live credentials for a system of
   * record: opening a tab should not put a working connection one stray
   * keystroke away from breaking. Editing is a deliberate act, and cancelling
   * discards rather than half-saves.
   */
  if (!editing) {
    const shown = visibleFields(fields, method)
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[12px] text-[var(--text-tertiary)]">
            Stored credentials. Secrets are never displayed.
          </p>
          <Button
            variant="secondary"
            size="sm"
            icon={<Pencil className="size-3.5" />}
            onClick={() => setEditing(true)}
          >
            Edit
          </Button>
        </div>

        <dl className="divide-y divide-[var(--border-subtle)] overflow-hidden rounded-lg border border-[var(--border-subtle)]">
          {shown.map((f) => {
            const raw = (current[f.id] ?? '').trim()
            const isSecret = f.kind === 'password'
            // A select stores an id; show the label the user actually picked.
            const display = f.options.find((o) => o.id === raw)?.label ?? raw
            return (
              <div key={f.id} className="grid gap-1 px-3 py-2.5 sm:grid-cols-[minmax(0,13rem)_1fr]">
                <dt className="text-[12px] font-medium text-[var(--text-secondary)]">
                  {f.label}
                </dt>
                <dd
                  className={cn(
                    'min-w-0 font-mono text-[12px] break-all',
                    raw ? 'text-[var(--text-primary)]' : 'text-[var(--text-tertiary)]',
                  )}
                >
                  {/* A stored secret reads as set, without revealing length. */}
                  {!raw ? 'Not set' : isSecret ? '••••••••' : display}
                </dd>
              </div>
            )
          })}
        </dl>

        {missing.length ? (
          <p className="flex items-start gap-1.5 rounded-lg border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-2.5 text-[12px] text-[var(--warn)]">
            <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            Still needed: {missing.join(', ')}.
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <CredentialFieldsForm
        fields={fields}
        values={{ ...current, method }}
        secretsConfigured={secretsConfigured}
        showMissing={showMissing}
        onChange={(id, v) => {
          setValues((prev) => ({ ...prev, [id]: v }))
          setTouched(true)
        }}
      />

      <div className="flex items-center justify-end gap-2 border-t border-[var(--border-subtle)] pt-3">
        <Button
          variant="ghost"
          onClick={() => {
            // Discard, so cancelling never leaves a partial edit staged.
            setValues({})
            setTouched(false)
            setShowMissing(false)
            setEditing(false)
          }}
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          loading={saving}
          disabled={!touched || !secretsConfigured}
          onClick={save}
        >
          Save credentials
        </Button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ custom connector */

function CustomConnectorModal({
  onClose,
  onDone,
}: {
  onClose: () => void
  onDone: () => void
}) {
  const [name, setName] = useState('')
  const [vendor, setVendor] = useState('')
  const [description, setDescription] = useState('')
  const [authMethod, setAuthMethod] = useState<AuthMethod>('api_key')
  const [provides, setProvides] = useState('')
  const [saving, setSaving] = useState(false)

  const valid = name.trim().length > 1

  const fieldClass =
    'w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 py-2 text-[13px] text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10'

  async function submit() {
    setSaving(true)
    await api.createCustomConnector({
      name,
      vendor,
      description,
      authMethod,
      provides: provides
        .split('\n')
        .map((p) => p.trim())
        .filter(Boolean),
    })
    setSaving(false)
    onDone()
  }

  return (
    <Modal open onClose={onClose} title="Build a custom connector" size="lg">
      <p className="mb-4 text-[12px] text-[var(--text-secondary)]">
        For internal systems and anything not in the catalogue. Meridian calls an endpoint you
        expose and treats what comes back as a knowledge source like any other.
      </p>

      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label
              htmlFor="cc-name"
              className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
            >
              System name
            </label>
            <input
              id="cc-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Claims Engine"
              className={fieldClass}
            />
          </div>
          <div>
            <label
              htmlFor="cc-vendor"
              className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
            >
              Owner or vendor
            </label>
            <input
              id="cc-vendor"
              value={vendor}
              onChange={(e) => setVendor(e.target.value)}
              placeholder="Internal"
              className={fieldClass}
            />
          </div>
        </div>

        <div>
          <label
            htmlFor="cc-desc"
            className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
          >
            What it is
          </label>
          <textarea
            id="cc-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="In-house claims adjudication service. Owns the rules that decide payout eligibility."
            className={fieldClass}
          />
        </div>

        <div>
          <label
            htmlFor="cc-provides"
            className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
          >
            What it contributes
          </label>
          <textarea
            id="cc-provides"
            value={provides}
            onChange={(e) => setProvides(e.target.value)}
            rows={3}
            placeholder={'Adjudication rules\nPayout thresholds\nRule change history'}
            className={fieldClass}
          />
          <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
            One per line. This is what appears on the connector card, so write it for whoever picks
            it next.
          </p>
        </div>

        <div>
          <label
            htmlFor="cc-auth"
            className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
          >
            How Meridian authenticates
          </label>
          <select
            id="cc-auth"
            value={authMethod}
            onChange={(e) => setAuthMethod(e.target.value as AuthMethod)}
            className="h-9 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 text-[13px] text-[var(--text-primary)]"
          >
            {(Object.keys(AUTH_LABEL) as AuthMethod[]).map((m) => (
              <option key={m} value={m}>
                {AUTH_LABEL[m]}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] pt-4">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" disabled={!valid} loading={saving} onClick={submit}>
          Register connector
        </Button>
      </div>
    </Modal>
  )
}

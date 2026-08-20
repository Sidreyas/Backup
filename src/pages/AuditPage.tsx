import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Cpu,
  Download,
  FileWarning,
  Gavel,
  Link2,
  Loader2,
  Lock,
  RotateCcw,
  Search,
  ScrollText,
  Server,
  ShieldAlert,
  ShieldCheck,
  User,
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
import { Tabs, useToast } from '@/components/ui/overlays'
import { api } from '@/lib/api'
import { detectModelDrift } from '@/lib/provenance'
import { cn, formatDateTime, formatDuration, formatNumber, formatUsd, humanize } from '@/lib/utils'
import type { AuditAction, AuditEntry, ChainVerification, RetentionClass } from '@/lib/types'

const ACTOR_ICON = {
  human: User,
  agent: Bot,
  system: Server,
} as const

/** Actions that change the governance state get stronger visual weight. */
const ACTION_TONE: Partial<Record<AuditAction, 'ok' | 'danger' | 'warn' | 'info' | 'accent'>> = {
  'approval.granted': 'ok',
  'approval.rejected': 'danger',
  'policy.violated': 'danger',
  'change.deployed': 'accent',
  'impact.generated': 'info',
  'test.run': 'info',
  'test.generated': 'info',
  'graph.link_confirmed': 'ok',
  'incident.raised': 'danger',
  'incident.updated': 'warn',
  'chain.verified': 'warn',
  'evidence.exported': 'accent',
  'defect.raised': 'warn',
  'closure.signed': 'ok',
  'plan.state_changed': 'info',
  'testcase.edited': 'info',
}

/**
 * What each retention class means, in the terms the obligation is written in.
 * Shown rather than the bare enum, because "sox" tells a reviewer nothing and
 * "7 years — SOX ITGC" tells them whether they can delete it.
 */
const RETENTION_LABEL: Record<RetentionClass, { label: string; detail: string }> = {
  standard: { label: '12 months', detail: 'Operational record, no external obligation' },
  ai_act: { label: '6 months min.', detail: 'EU AI Act Art. 12 — automatically generated log' },
  sox: { label: '7 years', detail: 'SOX ITGC — change and approval control evidence' },
  gxp: { label: 'Product lifetime', detail: 'GxP / 21 CFR Part 11 electronic record' },
  permanent: { label: 'Permanent', detail: 'AI incident record — retained indefinitely' },
}

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('all')
  const [query, setQuery] = useState('')
  const [verification, setVerification] = useState<ChainVerification | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [exporting, setExporting] = useState(false)
  const { push } = useToast()

  /* Load the chain, then immediately verify it. The banner reports a real
   * computation from first paint rather than an assertion. */
  const load = useCallback(async () => {
    setLoading(true)
    const list = await api.getAudit()
    setEntries(list)
    setLoading(false)
    setVerifying(true)
    setVerification(await api.verifyAuditChain())
    setVerifying(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const reverify = async () => {
    setVerifying(true)
    const result = await api.verifyAuditChain()
    setVerification(result)
    setEntries(await api.getAudit())
    setVerifying(false)
    push({
      tone: result.valid ? 'ok' : 'danger',
      title: result.valid ? 'Chain verified' : 'Chain integrity FAILED',
      description: result.detail,
    })
  }

  /* The demonstration: corrupt an entry, then let verification find it. */
  const tamper = async () => {
    const target = entries[Math.floor(entries.length / 2)]
    if (!target) return
    await api.simulateTamper(target.seq)
    push({
      tone: 'warn',
      title: `Entry #${target.seq} altered directly in storage`,
      description: 'Now re-verify the chain and watch the alteration surface.',
    })
    setEntries(await api.getAudit())
    setVerification(null)
  }

  const restore = async () => {
    await api.resetChain()
    setEntries(await api.getAudit())
    setVerification(await api.verifyAuditChain())
    push({ tone: 'ok', title: 'Chain restored', description: 'Demonstration state reset.' })
  }

  const exportPack = async () => {
    setExporting(true)
    try {
      const pack = await api.exportEvidencePack({ scope: 'Full audit chain + AI incident register' })
      /* A real file, not a toast. The pack is the deliverable. */
      const blob = new Blob([pack.content], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = pack.filename
      a.click()
      URL.revokeObjectURL(url)
      setEntries(await api.getAudit())
      push({
        tone: 'ok',
        title: 'Evidence pack exported',
        description: `${pack.filename} — manifest ${pack.manifestHash.slice(0, 16)}…`,
      })
    } finally {
      setExporting(false)
    }
  }

  const counts = useMemo(
    () => ({
      all: entries.length,
      human: entries.filter((e) => e.actorType === 'human').length,
      agent: entries.filter((e) => e.actorType === 'agent').length,
      policy: entries.filter((e) => e.action.startsWith('policy')).length,
      ai: entries.filter((e) => e.ai).length,
      held: entries.filter((e) => e.legalHold).length,
    }),
    [entries],
  )

  const filtered = useMemo(() => {
    let list = entries
    if (tab === 'human') list = list.filter((e) => e.actorType === 'human')
    if (tab === 'agent') list = list.filter((e) => e.actorType === 'agent')
    if (tab === 'policy') list = list.filter((e) => e.action.startsWith('policy'))
    if (tab === 'ai') list = list.filter((e) => e.ai)
    if (tab === 'changes') list = list.filter((e) => (e.changes?.length ?? 0) > 0)
    const q = query.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (e) =>
          e.summary.toLowerCase().includes(q) ||
          e.actor.toLowerCase().includes(q) ||
          (e.reason ?? '').toLowerCase().includes(q) ||
          (e.requirementRef ?? '').toLowerCase().includes(q),
      )
    }
    return list
  }, [entries, tab, query])

  const totalCost = entries.reduce((a, e) => a + e.costUsd, 0)
  const humanSeconds = entries
    .filter((e) => e.actorType === 'human')
    .reduce((a, e) => a + e.durationSeconds, 0)
  const agentSeconds = entries
    .filter((e) => e.actorType !== 'human')
    .reduce((a, e) => a + e.durationSeconds, 0)

  return (
    <>
      <PageHeader
        title="Audit Chain"
        icon={<ScrollText aria-hidden="true" />}
        tone="purple"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={reverify}
              disabled={verifying}
              icon={
                verifying ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <ShieldCheck className="size-4" aria-hidden="true" />
                )
              }
            >
              {verifying ? 'Verifying…' : 'Re-verify chain'}
            </Button>
            <Button
              variant="primary"
              disabled={exporting}
              icon={
                exporting ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Download className="size-4" aria-hidden="true" />
                )
              }
              onClick={exportPack}
            >
              {exporting ? 'Building…' : 'Export for audit'}
            </Button>
          </div>
        }
      />

      <PageBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Chain entries"
            value={counts.all}
            tone="accent"
            sublabel={`Sequence up to #${entries[0]?.seq ?? 0}`}
          />
          <StatTile
            label="Human actions"
            value={counts.human}
            tone="info"
            sublabel={formatDuration(humanSeconds) + ' of recorded human time'}
          />
          <StatTile
            label="AI-attributed"
            value={counts.ai}
            tone="asserted"
            sublabel={formatDuration(agentSeconds) + ' of agent runtime, model pinned'}
          />
          <StatTile
            label="Attributed cost"
            value={formatUsd(totalCost, { precise: true })}
            tone="ok"
            sublabel="Traced to individual chain entries"
          />
        </div>

        <IntegrityBanner
          verification={verification}
          verifying={verifying}
          entryCount={counts.all}
          heldCount={counts.held}
          onTamper={tamper}
          onRestore={restore}
        />

        <Card>
          <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] p-3 sm:flex-row sm:items-center sm:justify-between">
            <Tabs
              className="border-b-0"
              value={tab}
              onChange={setTab}
              items={[
                { id: 'all', label: 'All events', count: counts.all },
                { id: 'human', label: 'Human', count: counts.human },
                { id: 'agent', label: 'Agent', count: counts.agent },
                { id: 'ai', label: 'AI-attributed', count: counts.ai },
                {
                  id: 'changes',
                  label: 'Field changes',
                  count: entries.filter((e) => (e.changes?.length ?? 0) > 0).length,
                },
                { id: 'policy', label: 'Policy', count: counts.policy },
              ]}
            />
            <SearchInput
              className="sm:w-64"
              value={query}
              onChange={setQuery}
              placeholder="Filter the chain…"
              label="Filter audit entries"
              icon={<Search className="size-3.5" aria-hidden="true" />}
            />
          </div>

          {loading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<ScrollText className="size-5" aria-hidden="true" />}
              title="No entries match this filter"
              description="The chain is append-only — entries are never deleted, so widening the filter will bring them back."
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
            <ol className="relative">
              {filtered.map((entry, i) => (
                <AuditRow
                  key={entry.id}
                  entry={entry}
                  isLast={i === filtered.length - 1}
                  broken={verification?.firstBrokenSeq != null && entry.seq >= verification.firstBrokenSeq}
                  isBreakPoint={verification?.firstBrokenSeq === entry.seq}
                />
              ))}
            </ol>
          )}
        </Card>
      </PageBody>
    </>
  )
}

/* ------------------------------------------------------------ integrity */

/**
 * The verification result, reported rather than asserted.
 *
 * The previous version of this banner was static copy claiming the chain was
 * verified. A tamper-evidence product cannot make that claim without running
 * the check, and it has to be able to render the failure — which is what the
 * demonstration control below is for.
 */
function IntegrityBanner({
  verification,
  verifying,
  entryCount,
  heldCount,
  onTamper,
  onRestore,
}: {
  verification: ChainVerification | null
  verifying: boolean
  entryCount: number
  heldCount: number
  onTamper: () => void
  onRestore: () => void
}) {
  if (verifying || !verification) {
    return (
      <div className="flex items-start gap-2.5 rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-2)] p-3">
        <Loader2
          className="mt-px size-4 shrink-0 animate-spin text-[var(--text-tertiary)]"
          aria-hidden="true"
        />
        <div>
          <p className="text-xs font-semibold text-[var(--text-primary)]">
            {verification === null && !verifying
              ? 'Chain not yet verified'
              : 'Recomputing the chain…'}
          </p>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            Every entry’s hash is being re-derived from its content and compared with what is
            stored.
          </p>
        </div>
      </div>
    )
  }

  const ok = verification.valid

  return (
    <div
      className={cn(
        'flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-start sm:justify-between',
        ok
          ? 'border-[var(--ok-border)] bg-[var(--ok-subtle)]'
          : 'border-[var(--danger-border)] bg-[var(--danger-subtle)]',
      )}
    >
      <div className="flex items-start gap-2.5">
        {ok ? (
          <ShieldCheck className="mt-px size-4 shrink-0 text-[var(--ok)]" aria-hidden="true" />
        ) : (
          <ShieldAlert className="mt-px size-4 shrink-0 text-[var(--danger)]" aria-hidden="true" />
        )}
        <div className="min-w-0">
          <p
            className={cn(
              'text-xs font-semibold',
              ok ? 'text-[var(--ok)]' : 'text-[var(--danger)]',
            )}
          >
            {ok ? 'Chain integrity verified' : 'Chain integrity FAILED'}
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
            {verification.detail}
          </p>
          <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
            {formatNumber(verification.entriesChecked)} of {formatNumber(entryCount)} entries
            recomputed · SHA-256 · verified at {formatDateTime(verification.verifiedAt)}
            {heldCount > 0 ? ` · ${heldCount} under legal hold` : ''}
          </p>
        </div>
      </div>

      {/* Demonstration controls. A tamper-evidence claim nobody can watch fail
          is a marketing line; these make the mechanism inspectable. */}
      <div className="flex shrink-0 gap-2">
        {ok ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={onTamper}
            icon={<FileWarning className="size-3.5" aria-hidden="true" />}
          >
            Simulate tampering
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            onClick={onRestore}
            icon={<RotateCcw className="size-3.5" aria-hidden="true" />}
          >
            Restore chain
          </Button>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------- row */

function AuditRow({
  entry,
  isLast,
  broken,
  isBreakPoint,
}: {
  entry: AuditEntry
  isLast: boolean
  broken: boolean
  isBreakPoint: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const Icon = ACTOR_ICON[entry.actorType]
  const tone = ACTION_TONE[entry.action]
  const drift = entry.ai ? detectModelDrift(entry.ai.modelVersion) : null
  const retention = RETENTION_LABEL[entry.retention]

  const toneRing = {
    ok: 'border-[var(--ok-border)] bg-[var(--ok-subtle)] text-[var(--ok)]',
    danger: 'border-[var(--danger-border)] bg-[var(--danger-subtle)] text-[var(--danger)]',
    warn: 'border-[var(--warn-border)] bg-[var(--warn-subtle)] text-[var(--warn)]',
    info: 'border-[var(--info-border)] bg-[var(--info-subtle)] text-[var(--info)]',
    accent: 'border-[var(--accent-border)] bg-[var(--accent-subtle)] text-[var(--accent-text)]',
  }

  return (
    <li
      className={cn(
        'relative border-b border-[var(--border-subtle)] last:border-b-0',
        broken && 'bg-[var(--danger-subtle)]',
      )}
    >
      {!isLast ? (
        <span
          aria-hidden="true"
          className={cn(
            'absolute top-11 bottom-0 left-[30px] w-px',
            broken ? 'bg-[var(--danger)]' : 'bg-[var(--border-default)]',
          )}
        />
      ) : null}

      <button
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className="flex w-full cursor-pointer items-start gap-3 p-4 text-left transition-colors duration-150 hover:bg-[var(--bg-hover)]"
      >
        <span
          className={cn(
            'relative z-[var(--z-base)] mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border',
            broken
              ? 'border-[var(--danger-border)] bg-[var(--danger-subtle)] text-[var(--danger)]'
              : tone
                ? toneRing[tone]
                : 'border-[var(--border-default)] bg-[var(--bg-surface-2)] text-[var(--text-tertiary)]',
          )}
        >
          {isBreakPoint ? (
            <AlertTriangle className="size-4" aria-hidden="true" />
          ) : (
            <Icon className="size-4" aria-hidden="true" />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="tabular font-mono text-[10px] text-[var(--text-tertiary)]">
              #{entry.seq}
            </span>
            <Badge tone={tone === 'danger' ? 'danger' : tone === 'ok' ? 'ok' : 'neutral'}>
              {humanize(entry.action)}
            </Badge>
            {entry.requirementRef ? (
              <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                {entry.requirementRef}
              </span>
            ) : null}
            {entry.ai ? (
              <Badge tone={drift?.drifted ? 'warn' : 'neutral'}>
                <Cpu className="mr-1 inline size-2.5" aria-hidden="true" />
                {entry.ai.modelVersion}
              </Badge>
            ) : null}
            {(entry.changes?.length ?? 0) > 0 ? (
              <Badge tone="neutral">{entry.changes!.length} field change(s)</Badge>
            ) : null}
            {entry.legalHold ? (
              <Badge tone="warn">
                <Lock className="mr-1 inline size-2.5" aria-hidden="true" />
                Legal hold
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-sm leading-snug text-[var(--text-primary)]">{entry.summary}</p>
          <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
            {entry.actor} · {formatDateTime(entry.at)}
            {entry.durationSeconds > 0 ? ` · ${formatDuration(entry.durationSeconds)}` : ''}
            {entry.costUsd > 0 ? ` · ${formatUsd(entry.costUsd, { precise: true })}` : ''}
          </p>

          {isBreakPoint ? (
            <p className="mt-2 rounded border border-[var(--danger-border)] bg-[var(--bg-surface)] px-2 py-1.5 text-[11px] leading-relaxed text-[var(--danger)]">
              This is where the chain breaks. This entry’s content no longer matches its stored
              hash, which invalidates it and every entry after it.
            </p>
          ) : null}

          {expanded ? (
            <div className="mt-3 space-y-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
              {/* Part 11 §11.10(e): the before/after values */}
              {entry.changes?.length ? (
                <div>
                  <SectionLabel>Field-level changes</SectionLabel>
                  <ul className="mt-1.5 space-y-1.5">
                    {entry.changes.map((c) => (
                      <li key={c.field}>
                        <p className="text-[11px] font-medium text-[var(--text-secondary)]">
                          {c.label}
                        </p>
                        <div className="mt-1 flex flex-col gap-1 sm:flex-row sm:items-start">
                          <span className="min-w-0 flex-1 rounded border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-2 py-1 font-mono text-[11px] break-words text-[var(--text-tertiary)] line-through">
                            {c.before ?? '—'}
                          </span>
                          <ArrowRight
                            className="mt-1 hidden size-3 shrink-0 text-[var(--text-tertiary)] sm:block"
                            aria-hidden="true"
                          />
                          <span className="min-w-0 flex-1 rounded border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-2 py-1 font-mono text-[11px] break-words text-[var(--text-primary)]">
                            {c.after ?? '—'}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {entry.reason ? (
                <div>
                  <SectionLabel>Reason for change</SectionLabel>
                  <p className="mt-1 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--text-primary)]">
                    <Gavel
                      className="mt-0.5 size-3 shrink-0 text-[var(--text-tertiary)]"
                      aria-hidden="true"
                    />
                    {entry.reason}
                  </p>
                </div>
              ) : null}

              {/* Art. 12 / NIST AI RMF: which model, which version, what input */}
              {entry.ai ? (
                <div>
                  <SectionLabel>Model provenance</SectionLabel>
                  <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-3">
                    <div>
                      <dt className="text-[var(--text-tertiary)]">Model</dt>
                      <dd className="font-mono text-[var(--text-primary)]">{entry.ai.model}</dd>
                    </div>
                    <div>
                      <dt className="text-[var(--text-tertiary)]">Version</dt>
                      <dd
                        className={cn(
                          'font-mono',
                          drift?.drifted ? 'text-[var(--warn)]' : 'text-[var(--text-primary)]',
                        )}
                      >
                        {entry.ai.modelVersion}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[var(--text-tertiary)]">Temperature</dt>
                      <dd className="font-mono text-[var(--text-primary)]">
                        {entry.ai.temperature}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[var(--text-tertiary)]">Tokens in / out</dt>
                      <dd className="font-mono text-[var(--text-primary)]">
                        {formatNumber(entry.ai.tokensIn)} / {formatNumber(entry.ai.tokensOut)}
                      </dd>
                    </div>
                    <div className="col-span-2">
                      <dt className="text-[var(--text-tertiary)]">Prompt hash</dt>
                      <dd className="truncate font-mono text-[var(--text-primary)]">
                        {entry.ai.promptHash}
                      </dd>
                    </div>
                  </dl>
                  {drift?.drifted ? (
                    <p className="mt-1.5 rounded border border-[var(--warn-border)] bg-[var(--warn-subtle)] px-2 py-1 text-[11px] leading-relaxed text-[var(--warn)]">
                      {drift.detail}
                    </p>
                  ) : null}
                </div>
              ) : null}

              <div>
                <SectionLabel>Entry hash</SectionLabel>
                <p className="mt-1 flex items-center gap-1.5 font-mono text-xs break-all text-[var(--text-primary)]">
                  {broken ? (
                    <AlertTriangle
                      className="size-3 shrink-0 text-[var(--danger)]"
                      aria-hidden="true"
                    />
                  ) : (
                    <CheckCircle2 className="size-3 shrink-0 text-[var(--ok)]" aria-hidden="true" />
                  )}
                  {entry.hash}
                </p>
              </div>
              <div>
                <SectionLabel>Commits to previous</SectionLabel>
                <p className="mt-1 flex items-center gap-1.5 font-mono text-xs break-all text-[var(--text-tertiary)]">
                  <Link2 className="size-3 shrink-0" aria-hidden="true" />
                  {entry.prevHash}
                </p>
              </div>

              <div>
                <SectionLabel>Retention</SectionLabel>
                <p className="mt-1 text-[11px] text-[var(--text-primary)]">
                  {retention.label}
                  <span className="text-[var(--text-tertiary)]"> — {retention.detail}</span>
                  {entry.legalHold ? (
                    <span className="text-[var(--warn)]">
                      {' '}
                      · under legal hold, deletion suspended
                    </span>
                  ) : null}
                </p>
              </div>

              <p className="text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                Altering this entry would change its hash and break every entry after it. That is
                what makes the record tamper-evident rather than merely a log.
              </p>
            </div>
          ) : null}
        </div>
      </button>
    </li>
  )
}

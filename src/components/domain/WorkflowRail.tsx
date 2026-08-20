import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowUpRight, Check, CircleDashed, CircleSlash, MoreVertical, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useStlc } from '@/lib/useStlc'
import type { ProposedCase, RunStatus } from '@/lib/types'

/** One row in the rail — a recorded case or one just proposed in-thread. */
interface RailRow {
  id: string
  ref: string
  title: string
  status?: RunStatus
  approved?: boolean
  /** Proposed in this conversation and not yet on record. */
  isNew?: boolean
  /** True once a person has kept it; false while it is only proposed. */
  accepted?: boolean
}

const LEVEL_LABEL: Record<string, string> = {
  unit: 'Unit',
  integration: 'Integration',
  system: 'System',
  uat: 'UAT',
  regression: 'Regression',
}

/**
 * The outcome of a row, as a word plus a chip.
 *
 * A status column that lines up can be scanned in one pass, which is the whole
 * reason to keep this panel open while reading the transcript — an icon alone
 * makes you decode five shapes instead of reading five words.
 */
function statusOf(row: RailRow): {
  label: string
  chip: string
  Icon: typeof Check
  iconClass: string
} {
  if (row.status === 'passed')
    return {
      label: 'Succeeded',
      chip: 'border-[var(--ok-border)] bg-[var(--ok-subtle)] text-[var(--ok)]',
      Icon: Check,
      iconClass: 'text-[var(--ok)]',
    }
  if (row.status === 'failed')
    return {
      label: 'Failed',
      chip: 'border-[var(--danger-border)] bg-[var(--danger-subtle)] text-[var(--danger)]',
      Icon: X,
      iconClass: 'text-[var(--danger)]',
    }
  if (row.status === 'flaky')
    return {
      label: 'Flaky',
      chip: 'border-[var(--warn-border)] bg-[var(--warn-subtle)] text-[var(--warn)]',
      Icon: CircleSlash,
      iconClass: 'text-[var(--warn)]',
    }
  if (row.status === 'skipped')
    return {
      label: 'Skipped',
      chip: 'border-[var(--border-default)] text-[var(--text-tertiary)]',
      Icon: CircleSlash,
      iconClass: 'text-[var(--text-tertiary)]',
    }
  if (row.isNew)
    return {
      /*
       * An accepted proposal is "Not run", not "In review": accepting it is
       * what took it out of review. Falling through to the recorded-case
       * branch called it "In review" because a proposal carries no `approved`
       * flag — the absence of a field, read as a decision nobody made.
       */
      label: row.accepted ? 'Not run' : 'Proposed',
      chip: 'border-[var(--border-default)] text-[var(--text-tertiary)]',
      Icon: CircleDashed,
      iconClass: row.accepted ? 'text-[var(--text-tertiary)]' : 'text-[var(--border-strong)]',
    }
  return {
    label: row.approved ? 'Not run' : 'In review',
    chip: 'border-[var(--border-default)] text-[var(--text-tertiary)]',
    Icon: CircleDashed,
    iconClass: row.approved ? 'text-[var(--text-tertiary)]' : 'text-[var(--border-strong)]',
  }
}

/**
 * The test cases this conversation produced, beside the conversation.
 *
 * A table rather than a list: name, status, actions. Every row has an outcome,
 * and outcomes that line up in a column are read far faster than outcomes
 * scattered through prose.
 *
 * Reports rather than acts. The row menu links out to the pages that own each
 * case; nothing here mutates anything, because a governed change needs the
 * context and audit trail those pages provide.
 */
export function WorkflowRail({
  requirementId,
  proposed = [],
  acceptedIds,
  proposedStatusById,
}: {
  requirementId: string
  /**
   * Cases proposed in the current conversation and not yet persisted. Shown
   * alongside the recorded ones so the panel reflects what just happened,
   * rather than making someone reload to see their own work.
   */
  proposed?: ProposedCase[]
  /** Ids from `proposed` that a person has accepted. */
  acceptedIds?: Set<string>
  /**
   * Outcomes for proposed cases run in the conversation, keyed by proposal id.
   * Recorded cases take their status from the execution history instead.
   */
  proposedStatusById?: Record<string, RunStatus>
}) {
  const { cases, executions } = useStlc(requirementId)

  /** Latest outcome per case, so a re-run supersedes the run before it. */
  const resultByCase = useMemo(() => {
    const map = new Map<string, RunStatus>()
    executions.forEach((e) => e.results.forEach((r) => map.set(r.caseId, r.status)))
    return map
  }, [executions])

  const groups = useMemo(() => {
    const by = new Map<string, RailRow[]>()
    const add = (key: string, row: RailRow) => {
      if (!by.has(key)) by.set(key, [])
      by.get(key)!.push(row)
    }
    cases.forEach((c) =>
      add(LEVEL_LABEL[c.level] ?? c.level, {
        id: c.id,
        ref: c.ref,
        title: c.title,
        status: resultByCase.get(c.id),
        approved: c.state === 'approved',
      }),
    )
    /* Proposed cases group by their journey, which is what the crawl found —
       they have no test level yet because nobody has classified them. */
    proposed.forEach((p) =>
      add(p.group, {
        id: p.id,
        ref: p.ref,
        title: p.title,
        // A run outcome outranks "Proposed": once it has been executed, the
        // interesting fact about the row is what happened, not its origin.
        status: proposedStatusById?.[p.id],
        isNew: true,
        accepted: acceptedIds?.has(p.id) ?? false,
      }),
    )
    return [...by.entries()]
  }, [cases, proposed, resultByCase, acceptedIds, proposedStatusById])

  const all = groups.flatMap(([, rows]) => rows)
  const executed = all.filter((r) => r.status).length
  const failed = all.filter((r) => r.status === 'failed' || r.status === 'flaky').length

  return (
    /*
     * The panel is a canvas holding one card, matching the rest of the app:
     * white header band, grey group headers, white rows. Previously it was a
     * bare table drawn straight onto the surface, which made it the only
     * tabular thing in the product without card chrome around it.
     */
    <div className="flex h-full flex-col gap-3 bg-[var(--bg-base)] p-3">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
        {/* Column header, so the status column is labelled rather than implied. */}
        <div className="grid shrink-0 grid-cols-[minmax(0,26rem)_auto_24px] items-center gap-3 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2.5">
          <span className="text-[11px] font-medium text-[var(--text-tertiary)]">Test case</span>
          <span className="text-[11px] font-medium text-[var(--text-tertiary)]">Status</span>
          <span className="sr-only">Actions</span>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
        {groups.map(([group, rows]) => (
          <section key={group}>
            {/*
             * The group header links out to the page owning the whole group —
             * the shortcut people reach for once they have decided the group
             * as a whole needs attention.
             */}
            <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-1.5">
              <h3 className="flex-1 text-[11px] font-medium text-[var(--text-secondary)]">
                {group}
              </h3>
              <Link
                to="/test-cases"
                aria-label={`Open ${group} test cases`}
                className="text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-primary)]"
              >
                <ArrowUpRight className="size-3" aria-hidden="true" />
              </Link>
            </div>

            <ul>
              {rows.map((row) => {
                const s = statusOf(row)
                const bad = row.status === 'failed' || row.status === 'flaky'
                return (
                  <li
                    key={row.id}
                    className={cn(
                      /*
                       * minmax(0,26rem) rather than 1fr on the title: at the
                       * panel's full width a 1fr column pushed the status pill
                       * against the far edge, leaving a lake of space between
                       * a case and its own outcome. Capping the name column
                       * keeps the pair readable as one fact at any width.
                       */
                      'group grid grid-cols-[minmax(0,26rem)_auto_24px] items-center gap-3',
                      'border-b border-[var(--border-subtle)] py-2 pr-1 pl-3',
                      'transition-colors hover:bg-[var(--bg-hover)]',
                      /*
                       * A coloured left edge only where something is wrong. The
                       * status column already reports every row; edging all of
                       * them would spend the strongest signal on the ones that
                       * need it least.
                       */
                      bad && 'shadow-[inset_2px_0_0_0_var(--danger-solid)]',
                    )}
                  >
                    <Link to="/test-cases" className="flex min-w-0 items-center gap-2">
                      <s.Icon className={cn('size-3.5 shrink-0', s.iconClass)} aria-hidden="true" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12px] text-[var(--text-primary)]">
                          {row.title}
                        </span>
                        <span className="numeral block text-[10px] text-[var(--text-tertiary)]">
                          {row.ref}
                        </span>
                      </span>
                    </Link>

                    <span
                      className={cn(
                        'shrink-0 rounded-full border px-1.5 py-px text-[10px] font-medium',
                        s.chip,
                      )}
                    >
                      {s.label}
                    </span>

                    <RowMenu title={row.title} hasRun={Boolean(row.status)} />
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
        </div>

        {/* Footer band, inside the card and tonally recessed so it reads as a
            summary of the rows above rather than another row. */}
        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-2.5">
          <p className="text-[11px] text-[var(--text-tertiary)]">
            {executed === 0 ? (
              `${all.length} case${all.length === 1 ? '' : 's'}, none run yet`
            ) : failed > 0 ? (
              <span className="text-[var(--danger)]">
                {failed} failed of {executed} run
              </span>
            ) : (
              `${executed} of ${all.length} passed`
            )}
          </p>
          <Link
            to={executed > 0 ? '/test-runs' : '/test-cases'}
            className="flex shrink-0 items-center gap-1.5 text-[12px] font-medium text-[var(--accent)] hover:underline"
          >
            {executed > 0 ? 'View run' : 'Review cases'}
            <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </div>
  )
}

/** Per-row overflow menu, as in the reference. */
function RowMenu({ title, hasRun }: { title: string; hasRun: boolean }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const items: { label: string; to: string }[] = [
    { label: 'Open test case', to: '/test-cases' },
    ...(hasRun ? [{ label: 'View last run', to: '/test-runs' }] : []),
    { label: 'Open test plan', to: '/test-plan' },
  ]

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Actions for ${title}`}
        className={cn(
          'flex size-6 cursor-pointer items-center justify-center rounded-md',
          'text-[var(--text-tertiary)] transition-[opacity,background-color]',
          // Revealed on hover but always focusable: a menu that exists only on
          // pointer hover is a menu some people never reach.
          'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
          'hover:bg-[var(--bg-active)] hover:text-[var(--text-primary)]',
          open && 'bg-[var(--bg-active)] text-[var(--text-primary)] opacity-100',
        )}
      >
        <MoreVertical className="size-3.5" aria-hidden="true" />
      </button>

      {open ? (
        <div
          role="menu"
          className={cn(
            'animate-scale-in absolute top-full right-0 z-[var(--z-dropdown)] mt-1 w-[150px]',
            'overflow-hidden rounded-lg border border-[var(--border-default)]',
            'bg-[var(--bg-surface)] p-1 shadow-[var(--shadow-lg)]',
          )}
        >
          {items.map((i) => (
            <button
              key={i.label}
              role="menuitem"
              onClick={() => {
                setOpen(false)
                navigate(i.to)
              }}
              className="flex w-full cursor-pointer items-center rounded-md px-2 py-1.5 text-left text-[12px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              {i.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

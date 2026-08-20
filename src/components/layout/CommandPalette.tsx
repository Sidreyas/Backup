import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CornerDownLeft, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SOURCES, REQUIREMENTS } from '@/lib/mock-data'

/**
 * One searchable destination. `keywords` carry the words people actually type
 * that do not appear in the label — "kanban" for Jira, "payroll" for Workday —
 * so the palette matches intent rather than only exact spelling.
 */
export interface CommandItem {
  id: string
  label: string
  group: string
  to: string
  hint?: string
  keywords?: string
}

/** Navigation destinations, kept in step with the sidebar's own groups. */
const PAGE_ITEMS: CommandItem[] = [
  { id: 'p-overview', label: 'Overview', group: 'Pages', to: '/', keywords: 'dashboard home' },
  // Not "integrations"/"connectors" — those belong to the Integrations page,
  // and claiming them here put this row above the page people were asking for.
  // Carries the old Data Ingestion keywords: that page folded into this one,
  // and someone searching "ingest" should still land where ingesting happens.
  { id: 'p-sources', label: 'Knowledge Sources', group: 'Pages', to: '/sources', keywords: 'indexed catalogue coverage graph ingest ingestion sync import pipeline upload add data' },
  { id: 'p-integrations', label: 'Integrations', group: 'Pages', to: '/integrations', keywords: 'connectors apps workday jira slack sap connect' },
  { id: 'p-reqs', label: 'Requirements', group: 'Pages', to: '/requirements', keywords: 'stories intake queue' },
  { id: 'p-impact', label: 'Impact Analysis', group: 'Pages', to: '/impact', keywords: 'blast radius dependencies' },
  { id: 'p-plan', label: 'Test Plan', group: 'Pages', to: '/test-plan', keywords: 'stlc scope strategy' },
  { id: 'p-cases', label: 'Test Cases', group: 'Pages', to: '/test-cases', keywords: 'stlc design suite' },
  { id: 'p-runs', label: 'Test Execution', group: 'Pages', to: '/test-runs', keywords: 'stlc run defects retest' },
  { id: 'p-closure', label: 'Test Closure', group: 'Pages', to: '/test-closure', keywords: 'stlc sign off summary' },
  { id: 'p-evidence', label: 'Evidence Runs', group: 'Pages', to: '/evidence', keywords: 'proof verification' },
  { id: 'p-approvals', label: 'Approvals', group: 'Pages', to: '/approvals', keywords: 'gates sign off queue' },
  { id: 'p-audit', label: 'Audit Chain', group: 'Pages', to: '/audit', keywords: 'log history trail' },
  { id: 'p-incidents', label: 'AI Incidents', group: 'Pages', to: '/incidents', keywords: 'failures postmortem' },
  { id: 'p-policies', label: 'Policies', group: 'Pages', to: '/policies', keywords: 'rules guardrails compliance' },
  { id: 'p-analytics', label: 'Cost & Efficiency', group: 'Pages', to: '/analytics', keywords: 'spend dora metrics' },
  { id: 'p-settings', label: 'Settings', group: 'Pages', to: '/settings' },
  { id: 'p-support', label: 'Help & Support', group: 'Pages', to: '/support', keywords: 'docs contact' },
]

/**
 * Records are searchable too, because "find the thing" is far more often the
 * real intent than "find the page that lists the thing". Built once at module
 * scope: the fixtures are static, and rebuilding per keystroke would be work
 * for no gain.
 */
function recordItems(): CommandItem[] {
  return [
    ...REQUIREMENTS.map((r) => ({
      id: `r-${r.id}`,
      label: r.title,
      group: 'Requirements',
      to: `/requirements/${r.id}`,
      hint: r.ref,
      keywords: `${r.ref} ${r.platform}`,
    })),
    ...SOURCES.map((s) => ({
      id: `s-${s.id}`,
      label: s.name,
      group: 'Connected apps',
      to: '/sources',
      hint: s.provider,
      keywords: `${s.provider} ${s.kind}`,
    })),
  ]
}

const ALL_ITEMS: CommandItem[] = [...PAGE_ITEMS, ...recordItems()]

/** Case-insensitive substring match across label, hint and keywords. */
function matches(item: CommandItem, q: string) {
  const hay = `${item.label} ${item.hint ?? ''} ${item.keywords ?? ''}`.toLowerCase()
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => hay.includes(term))
}

/**
 * Command palette opened from the sidebar's search field or ⌘K / Ctrl-K.
 *
 * The sidebar field is a button rather than a real input: typing there would
 * mean a 200px-wide results list crammed into the rail. Clicking it opens this
 * overlay, which has room to group results and show what each one is.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  /*
   * With no query the palette shows pages only. Dumping every requirement and
   * source into an unfiltered list would bury the fifteen destinations most
   * people want behind rows they were not looking for.
   */
  const results = useMemo(() => {
    const pool = query.trim() ? ALL_ITEMS : PAGE_ITEMS
    return query.trim() ? pool.filter((i) => matches(i, query)) : pool
  }, [query])

  /** Group order follows first appearance, so Pages stay on top. */
  const groups = useMemo(() => {
    const out: { name: string; items: CommandItem[] }[] = []
    for (const item of results) {
      const found = out.find((g) => g.name === item.group)
      if (found) found.items.push(item)
      else out.push({ name: item.group, items: [item] })
    }
    return out
  }, [results])

  /* A flat view of what is rendered, so arrow keys cross group boundaries. */
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      // Focus after paint: the input does not exist until this render commits.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  // Typing changes the result set, so a held index could point past its end.
  useEffect(() => {
    setActive(0)
  }, [query])

  /* Keep the highlighted row in view when arrowing past the fold. */
  useEffect(() => {
    if (!open) return
    listRef.current
      ?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [active, open])

  function go(item: CommandItem) {
    onClose()
    navigate(item.to)
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (flat.length ? (i + 1) % flat.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (flat.length ? (i - 1 + flat.length) % flat.length : 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = flat[active]
      if (item) go(item)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  if (!open) return null

  let index = -1

  return (
    <div
      className="animate-fade fixed inset-0 z-[var(--z-modal)] bg-[var(--scrim)] p-4 pt-[12vh]"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search Meridian"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className={cn(
          'animate-scale-in mx-auto flex max-h-[64vh] w-full max-w-[560px] flex-col',
          'overflow-hidden rounded-xl border border-[var(--border-default)]',
          'bg-[var(--bg-surface)] shadow-[var(--shadow-lg)]',
        )}
      >
        <div className="flex shrink-0 items-center gap-2.5 border-b border-[var(--border-subtle)] px-3.5">
          <Search className="size-4 shrink-0 text-[var(--text-tertiary)]" aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search pages, requirements and apps…"
            aria-label="Search Meridian"
            aria-controls="command-results"
            className={cn(
              'h-12 min-w-0 flex-1 bg-transparent text-[14px] text-[var(--text-primary)] outline-none',
              'placeholder:text-[var(--text-tertiary)]',
            )}
          />
          <kbd className="shrink-0 rounded border border-[var(--border-default)] bg-[var(--bg-surface-2)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-tertiary)]">
            Esc
          </kbd>
        </div>

        <div ref={listRef} id="command-results" className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {flat.length === 0 ? (
            <p className="px-2.5 py-6 text-center text-[13px] text-[var(--text-tertiary)]">
              No matches for “{query}”.
            </p>
          ) : (
            groups.map((group) => (
              <div key={group.name} className="mb-1 last:mb-0">
                <p className="px-2.5 py-1.5 text-[11px] font-semibold text-[var(--text-tertiary)]">
                  {group.name}
                </p>
                {group.items.map((item) => {
                  index += 1
                  const isActive = index === active
                  const myIndex = index
                  return (
                    <button
                      key={item.id}
                      data-active={isActive}
                      onMouseEnter={() => setActive(myIndex)}
                      onClick={() => go(item)}
                      className={cn(
                        'flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left',
                        'transition-colors duration-150',
                        isActive ? 'bg-[var(--accent-subtle)]' : 'hover:bg-[var(--bg-hover)]',
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--text-primary)]">
                        {item.label}
                      </span>
                      {item.hint ? (
                        <span className="numeral shrink-0 text-[11px] text-[var(--text-tertiary)]">
                          {item.hint}
                        </span>
                      ) : null}
                      {/* Only the active row gets the Enter glyph — on every row
                          it would read as decoration rather than as the key
                          that acts on the current selection. */}
                      {isActive ? (
                        <CornerDownLeft
                          className="size-3.5 shrink-0 text-[var(--text-tertiary)]"
                          aria-hidden="true"
                        />
                      ) : null}
                    </button>
                  )
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

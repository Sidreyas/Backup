import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, Search } from 'lucide-react'
import { cn, relativeTime } from '@/lib/utils'
import { ScopeSwitcher } from './ScopeSwitcher'

/**
 * A notification is a thing that happened to work you own, with somewhere to
 * go and look at it. Anything without a destination is a toast, not a
 * notification — it would leave the panel as a row you cannot act on.
 */
interface Notice {
  id: string
  title: string
  detail: string
  at: string
  to: string
  unread: boolean
  tone: 'danger' | 'warn' | 'info'
}

/*
 * Placeholder feed, in the same spirit as the rest of the mock layer. Kept
 * here rather than in mock-data because nothing else consumes it yet; it moves
 * the moment a second caller appears.
 */
const NOTICES: Notice[] = [
  {
    id: 'n-1',
    title: 'Workday connector needs re-authorisation',
    detail: 'The refresh token expired. Nothing new is being pulled.',
    at: '2026-08-11T09:12:00Z',
    to: '/integrations',
    unread: true,
    tone: 'danger',
  },
  {
    id: 'n-2',
    title: 'MER-1042 is waiting on your approval',
    detail: 'Blocking dissent recorded — it cannot proceed until resolved.',
    at: '2026-08-11T08:40:00Z',
    to: '/approvals',
    unread: true,
    tone: 'warn',
  },
  {
    id: 'n-3',
    title: 'Regression suite finished',
    detail: '182 of 186 passed. Four failures are triaged to Payroll.',
    at: '2026-08-10T22:05:00Z',
    to: '/test-runs',
    unread: false,
    tone: 'info',
  },
]

const TONE_DOT: Record<Notice['tone'], string> = {
  danger: 'bg-[var(--danger)]',
  warn: 'bg-[var(--warn)]',
  info: 'bg-[var(--accent)]',
}

/**
 * The application bar that sits above every page.
 *
 * Scope on the left, utilities on the right. The scope moved out of the
 * sidebar because it answers "where am I working", which frames the content
 * rather than the navigation — and in the rail it was competing with the nav
 * items for the same first glance.
 */
export function TopBar({
  onOpenSearch,
  onOpenNav,
}: {
  onOpenSearch: () => void
  onOpenNav: () => void
}) {
  const unread = NOTICES.filter((n) => n.unread).length

  return (
    <header
      className={cn(
        'flex h-14 shrink-0 items-center gap-3 border-b border-[var(--border-subtle)]',
        'bg-[var(--bg-surface)] px-3 sm:px-4',
      )}
    >
      {/* Mobile nav trigger lives in the bar now that there is one, rather
          than floating over the page content. */}
      <button
        onClick={onOpenNav}
        aria-label="Open navigation"
        className={cn(
          'flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-lg',
          'text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)]',
          'hover:text-[var(--text-primary)] lg:hidden',
        )}
      >
        <PanelIcon />
      </button>

      <ScopeSwitcher variant="bar" />

      {/* The gap between scope and utilities. Also the flex spacer that keeps
          the right cluster pinned to the edge at every width. */}
      <div className="min-w-0 flex-1" />

      {/*
       * A button, not an input. The real search is the command palette, and a
       * focusable field that immediately hands focus to an overlay is a small
       * lie about what clicking it does — this looks like the field it opens
       * and says so.
       */}
      <button
        onClick={onOpenSearch}
        className={cn(
          'group hidden h-9 cursor-pointer items-center gap-2 rounded-lg md:flex',
          'w-[200px] border border-[var(--border-default)] bg-[var(--bg-surface-2)] px-2.5',
          'text-left transition-colors hover:bg-[var(--bg-hover)] lg:w-[260px]',
        )}
      >
        <Search className="size-4 shrink-0 text-[var(--text-tertiary)]" aria-hidden="true" />
        <span className="flex-1 truncate text-[13px] text-[var(--text-tertiary)]">Search…</span>
      </button>

      {/* Below md the field collapses to its icon rather than disappearing —
          search is not a desktop-only capability. */}
      <button
        onClick={onOpenSearch}
        aria-label="Search"
        className={cn(
          'flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-lg md:hidden',
          'text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)]',
          'hover:text-[var(--text-primary)]',
        )}
      >
        <Search className="size-4" aria-hidden="true" />
      </button>

      <NotificationBell unread={unread} />
    </header>
  )
}

/** The hamburger, drawn to match the rail's own panel glyph. */
function PanelIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M3 6h18M3 12h18M3 18h18" />
    </svg>
  )
}

function NotificationBell({ unread }: { unread: number }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

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

  return (
    <div className="relative shrink-0" ref={rootRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        className={cn(
          'flex size-9 cursor-pointer items-center justify-center rounded-lg',
          'text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)]',
          'hover:text-[var(--text-primary)]',
          open && 'bg-[var(--bg-hover)] text-[var(--text-primary)]',
        )}
      >
        <span className="relative">
          <Bell className="size-4" aria-hidden="true" />
          {/*
           * The count itself. "9+" past nine: the badge is pinned to the
           * corner of a 16px icon, and a third digit would grow it wider than
           * the glyph it sits on.
           */}
          {unread > 0 ? (
            <span
              className={cn(
                'absolute -top-1.5 -right-2 flex h-4 min-w-4 items-center justify-center',
                'rounded-full bg-[var(--danger)] px-1 text-[10px] font-bold leading-none',
                'text-white tabular-nums ring-2 ring-[var(--bg-surface)]',
              )}
              aria-hidden="true"
            >
              {unread > 9 ? '9+' : unread}
            </span>
          ) : null}
        </span>
      </button>

      {open ? (
        <div
          role="menu"
          className={cn(
            'animate-scale-in absolute right-0 top-full z-[var(--z-dropdown)] mt-2 w-[320px]',
            'overflow-hidden rounded-xl border border-[var(--border-default)]',
            'bg-[var(--bg-surface)] shadow-[var(--shadow-lg)]',
          )}
        >
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-3 py-2">
            <p className="text-[13px] font-bold text-[var(--text-primary)]">Notifications</p>
            {unread > 0 ? (
              <span className="text-[11px] font-medium text-[var(--text-tertiary)]">
                {unread} unread
              </span>
            ) : null}
          </div>

          {NOTICES.length === 0 ? (
            <p className="px-3 py-6 text-center text-[12px] text-[var(--text-tertiary)]">
              Nothing needs you right now.
            </p>
          ) : (
            <ul className="max-h-[360px] overflow-y-auto">
              {NOTICES.map((n) => (
                <li key={n.id}>
                  <Link
                    to={n.to}
                    onClick={() => setOpen(false)}
                    className={cn(
                      'flex gap-2.5 border-b border-[var(--border-subtle)] px-3 py-2.5',
                      'transition-colors last:border-b-0 hover:bg-[var(--bg-hover)]',
                    )}
                  >
                    <span
                      className={cn('mt-1.5 size-1.5 shrink-0 rounded-full', TONE_DOT[n.tone])}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1">
                      <span
                        className={cn(
                          'block text-[12.5px] leading-snug',
                          n.unread
                            ? 'font-semibold text-[var(--text-primary)]'
                            : 'font-medium text-[var(--text-secondary)]',
                        )}
                      >
                        {n.title}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] leading-snug text-[var(--text-tertiary)]">
                        {n.detail}
                      </span>
                      <span className="mt-1 block text-[10.5px] text-[var(--text-tertiary)]">
                        {relativeTime(n.at)}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity,
  BadgeCheck,
  ChevronsRight,
  ClipboardCheck,
  Database,
  FlaskConical,
  LayoutGrid,
  MessagesSquare,
  PanelLeft,
  AlertOctagon,
  ScrollText,
  Shield,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { CountBadge } from '@/components/ui/primitives'
import { Tooltip } from '@/components/ui/overlays'
import { SOURCES, REQUIREMENTS } from '@/lib/mock-data'
import { DEFECTS } from '@/lib/mock-stlc'
import { ProfileMenu } from './ProfileMenu'
import { CommandPalette } from './CommandPalette'
import { TopBar } from './TopBar'

interface NavItem {
  to: string
  label: string
  Icon: typeof LayoutGrid
  badge?: { text: string; tone: 'warn' | 'danger' | 'info' }
  /**
   * Trailing count. A bare numeral rather than a coloured pill: it is a volume
   * cue, not a warning, and pills on eight rows would make everything shout.
   */
  count?: number
  children?: { to: string; label: string }[]
}

interface NavGroup {
  label: string
  items: NavItem[]
}

/*
 * Counts describe work waiting on you, not the size of a table. "Requirements
 * 8" would be a fact about a fixture; "Requirements 4" meaning four still in
 * flight is a reason to click. Anything settled — signed off, rejected,
 * closed — is deliberately excluded.
 */
const OPEN_REQUIREMENTS = REQUIREMENTS.filter(
  (r) => r.stage !== 'signed_off' && r.stage !== 'rejected',
).length

const OPEN_DEFECTS = DEFECTS.filter((d) => d.status !== 'closed' && d.status !== 'wont_fix').length

/**
 * Connectors needing attention. Surfaced as a badge on Knowledge Sources
 * rather than as a list of apps in the rail: the rail is for navigation, and
 * eight connector rows pushed the actual nav items off the bottom of it.
 */
const BROKEN_CONNECTORS = SOURCES.filter(
  (s) => s.status === 'error' || s.status === 'stale' || s.status === 'disconnected',
).length

/**
 * Navigation mirrors the change lifecycle, so the sidebar doubles as a mental
 * model of the process: Understand → Decide → Prove → Account.
 *
 * Overview stands outside the sections: it is not a stage of the workflow, it
 * is the view across all of them.
 */
const OVERVIEW_ITEM: NavItem = { to: '/', label: 'Overview', Icon: LayoutGrid }

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Workflow',
    items: [
      {
        to: '/sources',
        label: 'Knowledge Sources',
        Icon: Database,
        /*
         * A broken connector is a hole in the evidence, not a settings detail,
         * so it earns the one coloured badge in the rail. Absent when nothing
         * is wrong — a permanent "0" would train people to ignore it.
         *
         * On the parent rather than the Integrations child: children only
         * render while their group is open, so a badge down there would be
         * invisible exactly when it most needs to be seen.
         */
        badge: BROKEN_CONNECTORS
          ? { text: String(BROKEN_CONNECTORS), tone: 'danger' as const }
          : undefined,
        children: [
          { to: '/sources', label: 'All sources' },
          { to: '/integrations', label: 'Integrations' },
        ],
      },
      {
        to: '/requirements',
        label: 'Requirements',
        Icon: MessagesSquare,
        count: OPEN_REQUIREMENTS,
        children: [
          { to: '/requirements', label: 'All / My Queue' },
          { to: '/impact', label: 'Impact Analysis' },
        ],
      },
      {
        to: '/test-plan',
        label: 'Testing',
        Icon: FlaskConical,
        count: OPEN_DEFECTS,
        children: [
          { to: '/test-plan', label: 'Test Plan' },
          { to: '/test-cases', label: 'Test Cases' },
          { to: '/test-runs', label: 'Test Execution' },
          { to: '/test-closure', label: 'Test Closure' },
        ],
      },
      { to: '/evidence', label: 'Evidence Runs', Icon: ClipboardCheck },
      { to: '/approvals', label: 'Approvals', Icon: BadgeCheck },
    ],
  },
  {
    label: 'Oversight',
    items: [
      { to: '/audit', label: 'Audit Chain', Icon: ScrollText },
      { to: '/incidents', label: 'AI Incidents', Icon: AlertOctagon },
      { to: '/policies', label: 'Policies', Icon: Shield },
      { to: '/analytics', label: 'Cost & Efficiency', Icon: Activity },
    ],
  },
]


function MeridianMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        // --brand, not --accent: blue is the interaction colour, and a
        // permanently blue logo reads as a selected item.
        'flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-[var(--brand)]',
        'text-[16px] leading-none font-bold text-[var(--brand-on)]',
        className,
      )}
      aria-hidden="true"
    >
      M
    </span>
  )
}

/** True when this item or any of its children owns the current route. */
function ownsRoute(item: NavItem, pathname: string) {
  // A prefix test on item.to is not enough: children like /ingest live outside
  // their parent's path.
  return pathname === item.to || (item.children ?? []).some((c) => pathname.startsWith(c.to))
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const location = useLocation()

  /**
   * Accordion: at most one group is expanded at a time, so opening one closes
   * whichever was open. Held as a single id rather than a set — that is what
   * makes the exclusivity structural instead of something to remember to
   * enforce on every toggle.
   *
   * `null` means "follow the route", which keeps the group containing the
   * current page open on load and after navigating from elsewhere.
   */
  const [openGroup, setOpenGroup] = useState<string | null>(null)

  const routeGroup =
    NAV_GROUPS.flatMap((g) => g.items).find((i) => i.children && ownsRoute(i, location.pathname))
      ?.to ?? null

  /*
   * Hand control back to the route only when navigation lands inside a group
   * other than the one held open. Resetting on every navigation would fight
   * the disclosure button: expanding "Testing" while sitting on /sources would
   * be undone the moment you clicked one of its children.
   */
  useEffect(() => {
    setOpenGroup((held) =>
      held !== null && held !== routeGroup && routeGroup !== null ? null : held,
    )
  }, [routeGroup])

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  /*
   * ⌘K / Ctrl-K anywhere. Bound on the window rather than the field so the
   * shortcut works from the middle of a page, which is the only place anyone
   * actually presses it. preventDefault stops Firefox stealing it for its own
   * quick-find bar.
   */
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!mobileOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [mobileOpen])

  const renderItem = (item: NavItem) => {
    const owns = ownsRoute(item, location.pathname)
    const hasChildren = Boolean(item.children?.length)
    const expanded = hasChildren && !collapsed && (openGroup ?? routeGroup) === item.to

    const linkClass = ({ isActive }: { isActive: boolean }) =>
      cn(
        'group flex min-h-9 items-center gap-2.5 rounded-[10px] text-[13px] transition-colors duration-200',
        // Collapsed rows are fixed squares: flex-1 inside the tooltip wrapper
        // would not size them, leaving the icons crowded against the edge.
        collapsed ? 'size-9 justify-center px-0' : 'flex-1 px-2.5 py-1.5',
        /*
         * A grey fill marks the selection. It reads against the white rail,
         * which is what the raised-pill treatment was working around back when
         * the sidebar shared the page canvas.
         */
        isActive || owns
          ? 'bg-[var(--bg-surface-3)] font-bold text-[var(--text-primary)]'
          : /*
             * Hover is --bg-surface-2, a step *lighter* than the selected
             * --bg-surface-3. The shared --bg-hover is within 6/255 of the
             * selected tone, so on the white rail hovering an unselected row
             * looked like selecting it.
             */
            'font-semibold text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]',
      )

    const link = (
      <NavLink
        to={item.to}
        end={item.to === '/'}
        // The row is now the only disclosure control, so it has to announce
        // the state it controls.
        aria-expanded={hasChildren && !collapsed ? expanded : undefined}
        onClick={() => {
          // Clicking a parent opens its group and closes any other.
          if (hasChildren) setOpenGroup(item.to)
        }}
        className={linkClass}
      >
        <item.Icon className="size-[18px] shrink-0" aria-hidden="true" />
        {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
        {/*
         * A filled circle, as in the reference's "Messages 3". Broken
         * connectors are the one danger-toned count in the rail; volume counts
         * stay neutral so a single red circle still means something.
         */}
        {!collapsed && item.badge ? (
          <CountBadge count={Number(item.badge.text)} tone="danger" label="needing attention" />
        ) : null}
        {/*
         * Solid blue, as in the reference. The neutral variant sat within a
         * shade of the rail and read as disabled text rather than a count of
         * work waiting — which is the one thing it exists to say.
         */}
        {!collapsed && item.count !== undefined && !item.badge ? (
          <CountBadge count={item.count} tone="accent" label="open" />
        ) : null}
      </NavLink>
    )

    return (
      <li key={item.to + item.label}>
        {/*
         * No separate disclosure chevron. Clicking the parent already expands
         * its group, so the arrow was a second control for the same outcome —
         * and one that was easy to miss at 14px while the whole row was the
         * larger, more obvious target all along.
         */}
        <div className={cn('flex items-center', collapsed && 'justify-center')}>
          {collapsed ? <Tooltip label={item.label}>{link}</Tooltip> : link}
        </div>

        {expanded ? (
          <ul className="relative mt-0.5 ml-[19px] space-y-0.5 border-l border-[var(--border-default)] pl-3">
            {item.children!.map((child) => (
              <li key={child.to + child.label} className="relative">
                {/*
                 * Not `end`: a detail route like /requirements/req-1 lives
                 * under its list, and exact matching left the sidebar showing
                 * nothing selected while you were plainly inside that section.
                 * Prefix matching is right here because sibling children never
                 * nest under one another.
                 */}
                <NavLink to={child.to} className="block">
                  {({ isActive }) => (
                    <>
                      {/*
                       * A dot on the guide line marks the current child, as in
                       * the reference. Centred on the border rather than beside
                       * it, and ringed in the sidebar's own background so the
                       * line reads as interrupted by the marker rather than
                       * crossed by it.
                       */}
                      {isActive ? (
                        <span
                          className={cn(
                            'absolute top-1/2 -left-[15.5px] size-[7px] -translate-y-1/2 rounded-full',
                            'bg-[var(--text-primary)] ring-[3px] ring-[var(--bg-surface)]',
                          )}
                          aria-hidden="true"
                        />
                      ) : null}
                      <span
                        className={cn(
                          'block rounded-md px-2 py-1.5 text-[13px] transition-colors duration-200',
                          isActive
                            ? 'font-bold text-[var(--text-primary)]'
                            : 'font-medium text-[var(--text-tertiary)] hover:text-[var(--text-primary)]',
                        )}
                      >
                        {child.label}
                      </span>
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        ) : null}
      </li>
    )
  }

  const sidebar = (
    <nav
      aria-label="Main navigation"
      className={cn(
        // White panel against the page canvas, so the rail reads as its own
        // surface and the grey selection has something to sit on.
        'flex h-full flex-col bg-[var(--bg-surface)]',
        'border-r border-[var(--border-subtle)] transition-[width] duration-200',
        collapsed ? 'w-[68px]' : 'w-[248px]',
      )}
    >
      {/*
       * Brand.
       *
       * h-14 and the bottom border are shared with the top bar deliberately:
       * the two sit side by side, so the rule reads as one line across the
       * whole shell rather than stopping at the rail. Any height change here
       * has to move with TopBar's or the line breaks at the seam.
       */}
      <div
        className={cn(
          'flex h-14 shrink-0 items-center gap-2.5 border-b border-[var(--border-subtle)] px-4',
          collapsed && 'justify-center px-0',
        )}
      >
        <MeridianMark />
        {!collapsed && (
          <>
            <span className="flex-1 truncate text-[15px] font-bold tracking-tight text-[var(--text-primary)]">
              Meridian
            </span>
            <button
              onClick={() => setCollapsed(true)}
              className="hidden cursor-pointer rounded-md p-1 text-[var(--text-tertiary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] lg:block"
              aria-label="Collapse sidebar"
            >
              <PanelLeft className="size-4" aria-hidden="true" />
            </button>
          </>
        )}
      </div>

      {/*
       * Scope lives in the top bar now. It frames the content rather than the
       * navigation, and in the rail it competed with the nav items for the
       * same first glance.
       *
       * No search control here either — the palette is reachable with ⌘K from
       * anywhere, and the bar now carries a visible field for it.
       */}

      {/* Nav groups. overflow-x-hidden matters while collapsing: the labels are
          still in the DOM mid-transition and would otherwise push out a
          horizontal scrollbar across the 68px rail. */}
      <div
        className={cn(
          // pt-3 gives the first group heading room off the header rule, which
          // it used to get from the scope block that sat here.
          'min-h-0 flex-1 overflow-x-hidden overflow-y-auto pt-3 pb-3',
          collapsed ? 'px-2' : 'px-3',
        )}
      >
        {/*
         * Overview, on its own above the sections. Given the same "Essentials"
         * heading treatment as every other group rather than floating
         * headingless above them — the reference's first group is labelled too,
         * and an unlabelled row at the top read as a stray item.
         */}
        <div className="mb-4">
          {!collapsed && (
            <p className="mb-1 px-2.5 text-[11px] font-medium tracking-[0.02em] text-[var(--text-tertiary)]">
              Essentials
            </p>
          )}
          <ul>{renderItem(OVERVIEW_ITEM)}</ul>
        </div>

        {NAV_GROUPS.map((group) => (
          /*
           * Rules only while collapsed. Expanded, each group already has a
           * heading to separate it and the reference leans on space alone —
           * a rule under every heading turned the rail into a stack of boxes.
           * Collapsed there are no headings, so the rule is the only thing
           * left holding the grouping.
           */
          <div
            key={group.label}
            className={cn(
              // More air between groups than within one, so the headings read
              // as separating the list rather than just sitting above it.
              collapsed ? 'mb-3 border-b border-[var(--border-subtle)] pb-3' : 'mb-4 last:mb-0',
            )}
          >
            {!collapsed && (
              /*
               * Sentence case, normal tracking — the reference's "Essentials" /
               * "Work" / "Measure", not a shouted uppercase eyebrow. At this
               * size a heading should recede behind the items it labels.
               */
              <p className="mb-1 px-2.5 text-[11px] font-medium tracking-[0.02em] text-[var(--text-tertiary)]">
                {group.label}
              </p>
            )}
            <ul className="space-y-0.5">{group.items.map(renderItem)}</ul>
          </div>
        ))}
      </div>

      {/* Footer: account only. Settings, Help, notifications and theme all
          live inside the account menu, which is what allowed the top bar to be
          removed. */}
      <div
        className={cn(
          'shrink-0 border-t border-[var(--border-subtle)] py-3',
          collapsed ? 'px-2' : 'px-3',
        )}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-1">
            <ProfileMenu collapsed />
            <button
              onClick={() => setCollapsed(false)}
              className="flex size-9 cursor-pointer items-center justify-center rounded-lg text-[var(--text-tertiary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
              aria-label="Expand sidebar"
            >
              <ChevronsRight className="size-4" aria-hidden="true" />
            </button>
          </div>
        ) : (
          <ProfileMenu />
        )}
      </div>
    </nav>
  )

  return (
    // Fills the viewport edge to edge — no page gutter, no floating container.
    <div className="flex h-dvh overflow-hidden bg-[var(--bg-base)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-[var(--z-toast)] focus:rounded-lg focus:bg-[var(--accent)] focus:px-3 focus:py-2 focus:text-sm focus:text-[var(--accent-on)]"
      >
        Skip to main content
      </a>

      {/* Desktop sidebar */}
      <div className="hidden shrink-0 lg:block">{sidebar}</div>

      {/* Mobile drawer */}
      {mobileOpen ? (
        <div
          className="animate-fade fixed inset-0 z-[var(--z-drawer)] bg-[var(--scrim)] lg:hidden"
          onClick={() => setMobileOpen(false)}
        >
          <div
            className="animate-in absolute inset-y-0 left-0"
            onClick={(e) => e.stopPropagation()}
          >
            {sidebar}
            {/*
             * An explicit way out. The scrim closes the drawer too, but that
             * is a discovered gesture — since the trigger now lives in the bar
             * behind the scrim, without this there is no visible close
             * control once the drawer is open.
             */}
            <button
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation"
              className={cn(
                'absolute top-3 -right-11 flex size-9 cursor-pointer items-center justify-center',
                'rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)]',
                'text-[var(--text-secondary)] shadow-[var(--shadow-sm)]',
                'transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
              )}
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* One bar above every page: scope on the left, search and
            notifications on the right. It sits outside <main> so it stays put
            while the page below it scrolls. */}
        <TopBar
          onOpenSearch={() => setPaletteOpen(true)}
          onOpenNav={() => setMobileOpen(true)}
        />

        <main id="main" className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-[var(--bg-base)]">
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}

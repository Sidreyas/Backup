import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bell, Building2, Cpu, Palette, Search, ShieldCheck, User, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/primitives'
import { useFocusTrap } from '@/components/ui/overlays'
import {
  AgentsSection,
  AppearanceSection,
  NotificationsSection,
  ProfileSection,
  WorkspaceSection,
} from '@/components/settings/sections'

/**
 * Settings as an overlay rather than a page.
 *
 * Settings is a detour: you open it to change one thing and return to what you
 * were doing. A modal preserves that context — the page underneath stays put,
 * and closing returns you exactly where you were instead of relying on a back
 * button to unwind a navigation.
 *
 * Its own left rail is what makes the modal viable at this size; a flat scroll
 * of five sections would be worse than the page it replaces.
 */

export type SettingsSectionId = 'profile' | 'appearance' | 'workspace' | 'agents' | 'notifications'

interface SectionDef {
  id: SettingsSectionId
  label: string
  Icon: typeof User
  group: 'Settings' | 'Workspace'
  /** Extra terms the search should match beyond the label. */
  keywords: string
}

const SECTIONS: SectionDef[] = [
  {
    id: 'profile',
    label: 'Profile',
    Icon: User,
    group: 'Settings',
    keywords: 'name email role identity signing sso account',
  },
  {
    id: 'appearance',
    label: 'Appearance',
    Icon: Palette,
    group: 'Settings',
    keywords: 'theme light dark density display',
  },
  {
    id: 'notifications',
    label: 'Notifications',
    Icon: Bell,
    group: 'Settings',
    keywords: 'email alerts digest gate policy budget',
  },
  {
    id: 'workspace',
    label: 'Workspace',
    Icon: Building2,
    group: 'Workspace',
    keywords: 'compliance slug members projects region',
  },
  {
    id: 'agents',
    label: 'Agents & budget',
    Icon: Cpu,
    group: 'Workspace',
    keywords: 'permissions write access spend model cost cap',
  },
]

export function SettingsDialog({
  open,
  onClose,
  initialSection = 'profile',
}: {
  open: boolean
  onClose: () => void
  initialSection?: SettingsSectionId
}) {
  const [section, setSection] = useState<SettingsSectionId>(initialSection)
  const [query, setQuery] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)
  useFocusTrap(panelRef, open, onClose)

  // Reopening should land on the requested section, not the last one viewed.
  useEffect(() => {
    if (open) {
      setSection(initialSection)
      setQuery('')
    }
  }, [open, initialSection])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return SECTIONS
    // Label matches rank above keyword matches: searching "budget" should
    // offer "Agents & budget" before a section that merely mentions budgets.
    const scored = SECTIONS.map((s) => ({
      s,
      score: s.label.toLowerCase().includes(q) ? 0 : s.keywords.includes(q) ? 1 : 2,
    })).filter((x) => x.score < 2)
    return scored.sort((a, b) => a.score - b.score).map((x) => x.s)
  }, [query])

  // Searching to a single match should select it, so the right pane follows.
  useEffect(() => {
    if (query.trim() && filtered.length > 0 && !filtered.some((s) => s.id === section)) {
      setSection(filtered[0].id)
    }
  }, [query, filtered, section])

  if (!open) return null

  const groups = ['Settings', 'Workspace'] as const
  const searching = query.trim().length > 0

  return createPortal(
    <div
      className="animate-fade fixed inset-0 z-[var(--z-modal)] flex items-center justify-center p-4 bg-[var(--scrim)] backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'animate-scale-in relative flex h-[85vh] max-h-[720px] w-full max-w-4xl shrink-0 basis-full',
          'overflow-hidden rounded-xl border border-[var(--border-default)]',
          'bg-[var(--bg-surface)] shadow-[var(--shadow-xl)]',
        )}
      >
        {/* Left rail */}
        <div
          className={cn(
            'flex w-[228px] shrink-0 flex-col border-r border-[var(--border-subtle)]',
            'bg-[var(--bg-surface-2)]',
            // Below sm the rail would leave no room for content, so it becomes
            // a horizontal strip instead of disappearing entirely.
            'max-sm:hidden',
          )}
        >
          <div className="p-3">
            <div className="relative">
              <Search
                className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-[var(--text-tertiary)]"
                aria-hidden="true"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search"
                aria-label="Search settings"
                className={cn(
                  'h-9 w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)]',
                  'pr-3 pl-8 text-[13px] text-[var(--text-primary)] outline-none',
                  'placeholder:text-[var(--text-tertiary)] transition-colors duration-200',
                  'focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10',
                )}
              />
            </div>
          </div>

          <nav aria-label="Settings sections" className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            {searching ? (
              /* While searching, results are one ranked list. Keeping the group
                 headings would re-impose their fixed order and bury the best
                 match under a heading it happens not to sit in. */
              <ul className="space-y-0.5">
                {filtered.map((s) => (
                  <li key={s.id}>
                    <RailButton
                      section={s}
                      active={s.id === section}
                      onSelect={() => setSection(s.id)}
                    />
                  </li>
                ))}
              </ul>
            ) : (
              groups.map((group) => {
                const items = filtered.filter((s) => s.group === group)
                if (items.length === 0) return null
                return (
                  <div key={group} className="mb-3 last:mb-0">
                    <p className="px-2 py-1.5 text-[10px] font-bold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
                      {group}
                    </p>
                    <ul className="space-y-0.5">
                      {items.map((s) => (
                        <li key={s.id}>
                          <RailButton
                            section={s}
                            active={s.id === section}
                            onSelect={() => setSection(s.id)}
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              })
            )}

            {filtered.length === 0 ? (
              <p className="px-2 py-3 text-xs leading-relaxed text-[var(--text-tertiary)]">
                Nothing matches &ldquo;{query}&rdquo;.
              </p>
            ) : null}
          </nav>

          <div className="border-t border-[var(--border-subtle)] p-3">
            <p className="flex items-start gap-2 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
              <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden="true" />
              Changes that affect governance are recorded in the audit chain.
            </p>
          </div>
        </div>

        {/* Right pane */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-4 py-3">
            {/* On small screens the rail is hidden, so the section picker moves
                into the header as a select rather than being unreachable. */}
            <label className="sr-only" htmlFor="settings-section-mobile">
              Settings section
            </label>
            <select
              id="settings-section-mobile"
              value={section}
              onChange={(e) => setSection(e.target.value as SettingsSectionId)}
              className={cn(
                'h-8 cursor-pointer rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)]',
                'px-2 text-[13px] font-semibold text-[var(--text-primary)] outline-none sm:hidden',
              )}
            >
              {SECTIONS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>

            <h2 className="hidden min-w-0 truncate text-[15px] font-semibold text-[var(--text-primary)] sm:block">
              {SECTIONS.find((s) => s.id === section)?.label ?? 'Settings'}
            </h2>

            <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close settings">
              <X className="size-4" aria-hidden="true" />
            </Button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {section === 'profile' ? <ProfileSection /> : null}
            {section === 'appearance' ? <AppearanceSection /> : null}
            {section === 'workspace' ? <WorkspaceSection /> : null}
            {section === 'agents' ? <AgentsSection /> : null}
            {section === 'notifications' ? <NotificationsSection /> : null}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function RailButton({
  section,
  active,
  onSelect,
}: {
  section: SectionDef
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      onClick={onSelect}
      aria-current={active ? 'true' : undefined}
      className={cn(
        'flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5',
        'text-[13px] transition-colors duration-200',
        active
          ? 'bg-[var(--bg-surface-3)] font-semibold text-[var(--text-primary)]'
          : 'font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
      )}
    >
      <section.Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className="truncate">{section.label}</span>
    </button>
  )
}

/** Re-exported so callers can deep-link a section without importing the page. */
export const SETTINGS_SECTIONS = SECTIONS

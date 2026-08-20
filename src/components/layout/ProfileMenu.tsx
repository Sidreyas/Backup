import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  Bell,
  CircleHelp,
  LifeBuoy,
  LogOut,
  Monitor,
  Moon,
  Settings,
  ShieldCheck,
  Sun,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { CURRENT_USER } from '@/lib/mock-data'
import { Badge } from '@/components/ui/primitives'
import { SettingsDialog, type SettingsSectionId } from './SettingsDialog'
import { useTheme } from './theme'

/**
 * Account popover anchored to the sidebar footer.
 *
 * The top bar used to carry theme, notifications and settings as three loose
 * icons. They are account-level concerns rather than page-level ones, so they
 * live here instead — which is what let the header be removed entirely.
 *
 * Opens upward, because the trigger sits at the bottom of the sidebar.
 */
export function ProfileMenu({
  collapsed,
  notificationCount = 3,
}: {
  collapsed?: boolean
  notificationCount?: number
}) {
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsSection, setSettingsSection] = useState<SettingsSectionId>('profile')
  const rootRef = useRef<HTMLDivElement>(null)
  const { theme, setTheme } = useTheme()

  /** Close the popover as the overlay takes over — two stacked layers of
      chrome over the page would be one too many. */
  function openSettings(section: SettingsSectionId) {
    setSettingsSection(section)
    setSettingsOpen(true)
    setOpen(false)
  }

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

  const avatar = (
    <span
      className="flex size-7 shrink-0 items-center justify-center rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface-3)] text-[10px] font-semibold text-[var(--text-secondary)]"
      aria-hidden="true"
    >
      {CURRENT_USER.initials}
    </span>
  )

  return (
    <div className={cn('relative', collapsed && 'flex justify-center')} ref={rootRef}>
      {/* No bell here. The unread signal and its feed live in the top bar now,
          and two bells in one shell would be two places to check for the same
          thing. The account menu keeps a Notifications row, but that opens the
          settings for them rather than the feed. */}
      <div className={cn('flex items-center', collapsed && 'justify-center')}>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-haspopup="menu"
          aria-label={`Account menu for ${CURRENT_USER.name}`}
          className={cn(
            'flex cursor-pointer items-center gap-2 rounded-lg transition-colors duration-200',
            // px-1.5 rather than px-2: the bell takes width from this row, and
            // the role line was truncating mid-word without it.
            collapsed ? 'size-9 justify-center' : 'min-w-0 flex-1 px-1.5 py-1.5',
            open ? 'bg-[var(--bg-hover)]' : 'hover:bg-[var(--bg-hover)]',
          )}
        >
          {avatar}
          {!collapsed ? (
            <>
              <span className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[12px] font-semibold text-[var(--text-primary)]">
                  {CURRENT_USER.name}
                </span>
                <span className="block truncate text-[10px] text-[var(--text-tertiary)]">
                  {CURRENT_USER.role}
                </span>
              </span>
            </>
          ) : null}
        </button>

      </div>

      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className={cn(
            'animate-scale-in absolute bottom-full z-[var(--z-dropdown)] mb-2 w-[280px]',
            'overflow-hidden rounded-xl border border-[var(--border-default)]',
            'bg-[var(--bg-surface)] shadow-[var(--shadow-lg)]',
            collapsed ? 'left-0' : 'left-0',
          )}
        >
          {/* Identity */}
          <div className="border-b border-[var(--border-subtle)] px-3 py-2.5">
            <p className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
              {CURRENT_USER.name}
            </p>
            <p className="truncate text-[11px] text-[var(--text-tertiary)]">{CURRENT_USER.email}</p>
          </div>

          {/* Primary destinations. Settings and Notifications open the settings
              overlay rather than navigating — both are detours from whatever
              page you are on, and a modal returns you to it. */}
          <div className="border-b border-[var(--border-subtle)] p-1.5">
            <MenuButton icon={<Settings />} onClick={() => openSettings('profile')}>
              Settings
            </MenuButton>
            <MenuButton
              icon={<Bell />}
              onClick={() => openSettings('notifications')}
              trailing={
                notificationCount > 0 ? (
                  <Badge tone="danger" className="px-1 py-0">
                    {notificationCount}
                  </Badge>
                ) : null
              }
            >
              Notifications
            </MenuButton>
            <MenuLink to="/support" icon={<LifeBuoy />} onNavigate={() => setOpen(false)}>
              Help &amp; Support
            </MenuLink>
            <MenuLink to="/policies" icon={<ShieldCheck />} onNavigate={() => setOpen(false)}>
              Policies &amp; compliance
            </MenuLink>
          </div>

          {/* Appearance — a segmented row rather than a toggle, so the current
              choice is visible without having to infer it from the icon. */}
          <div className="border-b border-[var(--border-subtle)] p-1.5">
            <p className="px-2 py-1.5 text-[10px] font-bold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Appearance
            </p>
            <div
              role="radiogroup"
              aria-label="Appearance"
              className="flex items-center gap-1 rounded-lg bg-[var(--bg-surface-2)] p-1"
            >
              {(
                [
                  { id: 'light', label: 'Light', Icon: Sun },
                  { id: 'dark', label: 'Dark', Icon: Moon },
                ] as const
              ).map((opt) => {
                const active = theme === opt.id
                return (
                  <button
                    key={opt.id}
                    role="radio"
                    aria-checked={active}
                    onClick={() => setTheme(opt.id)}
                    className={cn(
                      'flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-md px-2 py-1.5',
                      'text-[11px] font-medium transition-colors duration-200',
                      // A raised white pill, matching Segmented. The filled
                      // accent made "Light" look like the page's primary action
                      // every time the menu opened.
                      active
                        ? 'bg-[var(--bg-surface)] font-semibold text-[var(--text-primary)] shadow-[var(--shadow-sm)] ring-1 ring-[var(--border-subtle)]'
                        : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]',
                    )}
                  >
                    <opt.Icon className="size-3.5" aria-hidden="true" />
                    {opt.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Secondary */}
          <div className="p-1.5">
            <MenuButton icon={<CircleHelp />}>What&rsquo;s new</MenuButton>
            <MenuButton icon={<Monitor />}>Keyboard shortcuts</MenuButton>
            <MenuButton icon={<LogOut />} danger>
              Log out
            </MenuButton>
          </div>
        </div>
      ) : null}

      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initialSection={settingsSection}
      />
    </div>
  )
}

const ROW =
  'flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors duration-200'

function MenuLink({
  to,
  icon,
  children,
  onNavigate,
}: {
  to: string
  icon: ReactNode
  children: ReactNode
  onNavigate: () => void
}) {
  return (
    <Link
      role="menuitem"
      to={to}
      onClick={onNavigate}
      className={cn(
        ROW,
        'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
        '[&>svg]:size-4 [&>svg]:shrink-0',
      )}
    >
      {icon}
      <span className="flex-1 truncate">{children}</span>
    </Link>
  )
}

function MenuButton({
  icon,
  children,
  trailing,
  danger,
  onClick,
}: {
  icon: ReactNode
  children: ReactNode
  trailing?: ReactNode
  danger?: boolean
  onClick?: () => void
}) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className={cn(
        ROW,
        danger
          ? 'text-[var(--danger)] hover:bg-[var(--danger-subtle)]'
          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
        '[&>svg]:size-4 [&>svg]:shrink-0',
      )}
    >
      {icon}
      <span className="flex-1 truncate">{children}</span>
      {trailing}
    </button>
  )
}

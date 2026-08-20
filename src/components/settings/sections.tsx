/**
 * Settings section bodies, shared by the settings overlay and the /settings
 * route. They live here rather than in the page so the dialog can import them
 * without dragging the lazily-loaded page into the main bundle.
 */
import { useState } from 'react'
import {
  Bell,
  Building2,
  Check,
  Cpu,
  Moon,
  Palette,
  ShieldCheck,
  Sun,
  User,
  Wallet,
} from 'lucide-react'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  SectionLabel,
  Segmented,
} from '@/components/ui/primitives'
import { useToast } from '@/components/ui/overlays'
import { useTheme } from '@/components/layout/theme'
import { useScope } from '@/lib/workspace'
import { CURRENT_USER } from '@/lib/mock-data'
import { cn, formatUsd } from '@/lib/utils'

/* ------------------------------------------------------------------ shared */

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-2 border-b border-[var(--border-subtle)] p-4 last:border-b-0 sm:grid-cols-[220px_1fr] sm:items-center sm:gap-4">
      <div>
        <p className="text-[13px] font-medium text-[var(--text-primary)]">{label}</p>
        {hint ? (
          <p className="mt-0.5 text-xs leading-snug text-[var(--text-tertiary)]">{hint}</p>
        ) : null}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

const inputClass = cn(
  'h-9 w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3',
  'text-[13px] text-[var(--text-primary)] outline-none transition-colors duration-200',
  'focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10',
)

/**
 * Workspace name field that saves.
 *
 * Commits on blur and on Enter rather than behind a Save button: this panel has
 * no save affordance of its own, so a field that only applied on submit would
 * silently discard every edit. Escape restores the current name.
 */
function WorkspaceNameField({
  name,
  onCommit,
}: {
  name: string
  onCommit: (next: string) => void
}) {
  const [draft, setDraft] = useState(name)

  const commit = () => {
    const next = draft.trim()
    // Empty is not a rename, it is a mistake — restore rather than accept a
    // workspace nobody could identify in the switcher.
    if (!next) {
      setDraft(name)
      return
    }
    if (next !== name) onCommit(next)
  }

  return (
    <input
      className={inputClass}
      value={draft}
      aria-label="Workspace name"
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          commit()
          e.currentTarget.blur()
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          setDraft(name)
        }
      }}
    />
  )
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200',
        checked ? 'bg-[var(--accent)]' : 'bg-[var(--bg-surface-3)]',
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 size-4 rounded-full bg-white shadow-[var(--shadow-sm)] transition-transform duration-200',
          checked ? 'translate-x-[18px]' : 'translate-x-0.5',
        )}
        aria-hidden="true"
      />
    </button>
  )
}

/* ----------------------------------------------------------------- profile */

export function ProfileSection() {
  const { push } = useToast()
  const [name, setName] = useState(CURRENT_USER.name)
  const [role, setRole] = useState(CURRENT_USER.role)

  return (
    <Card>
      <CardHeader
        title="Your profile"
        description="How you appear on approvals and in the audit chain."
        icon={<User aria-hidden="true" />}
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => push({ tone: 'ok', title: 'Profile saved' })}
          >
            Save changes
          </Button>
        }
      />
      <Field label="Display name" hint="Shown next to every decision you sign.">
        <input
          className={inputClass}
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Display name"
        />
      </Field>
      <Field label="Email" hint="Bound to your SSO identity and cannot be changed here.">
        <input
          className={cn(inputClass, 'opacity-60')}
          value={CURRENT_USER.email}
          readOnly
          aria-label="Email"
        />
      </Field>
      <Field label="Role" hint="Determines which approval gates you may satisfy.">
        <input
          className={inputClass}
          value={role}
          onChange={(e) => setRole(e.target.value)}
          aria-label="Role"
        />
      </Field>
      <Field
        label="Signing identity"
        hint="Approvals are non-repudiable and hash-chained to your identity."
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="ok" icon={<ShieldCheck className="size-3" aria-hidden="true" />}>
            SSO verified
          </Badge>
          <span className="font-mono text-xs text-[var(--text-tertiary)]">
            okta · sso.acme.example
          </span>
        </div>
      </Field>
    </Card>
  )
}

/* -------------------------------------------------------------- appearance */

export function AppearanceSection() {
  const { theme, setTheme } = useTheme()
  const [density, setDensity] = useState<'comfortable' | 'compact'>('comfortable')

  return (
    <Card>
      <CardHeader
        title="Appearance"
        description="Display preferences, stored on this device only."
        icon={<Palette aria-hidden="true" />}
      />
      <Field label="Theme" hint="Light and dark are authored as separate palettes.">
        <div className="flex flex-wrap gap-2">
          {/* "System" is omitted deliberately: the app resolves and pins a
              concrete theme before paint, so offering a system option that
              cannot be selected would be a control that lies. */}
          {[
            { id: 'light' as const, label: 'Light', Icon: Sun },
            { id: 'dark' as const, label: 'Dark', Icon: Moon },
          ].map((opt) => {
            const active = opt.id === theme
            return (
              <button
                key={opt.id}
                onClick={() => setTheme(opt.id)}
                aria-pressed={active}
                className={cn(
                  'flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[13px] transition-colors',
                  active
                    ? 'border-[var(--border-strong)] bg-[var(--bg-surface-2)] font-medium text-[var(--text-primary)]'
                    : 'border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]',
                )}
              >
                <opt.Icon className="size-3.5" aria-hidden="true" />
                {opt.label}
                {active ? <Check className="size-3.5" aria-hidden="true" /> : null}
              </button>
            )
          })}
        </div>
      </Field>
      <Field label="Table density" hint="Compact fits more rows without scrolling.">
        <Segmented
          value={density}
          onChange={setDensity}
          options={[
            { id: 'comfortable', label: 'Comfortable' },
            { id: 'compact', label: 'Compact' },
          ]}
        />
      </Field>
    </Card>
  )
}

/* --------------------------------------------------------------- workspace */

export function WorkspaceSection() {
  const { workspace, projects, renameWorkspace } = useScope()
  const { push } = useToast()

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={workspace.name}
          description="Workspace-level settings apply to every project inside it."
          icon={<Building2 aria-hidden="true" />}
          actions={<Badge tone="neutral">{workspace.region}</Badge>}
        />
        <Field label="Workspace name">
          {/*
           * `key` on the workspace id so the field re-seeds when you switch
           * workspaces or rename from the sidebar — an uncontrolled input keeps
           * its first value forever otherwise, and would sit there showing the
           * old name as though the rename had failed.
           */}
          <WorkspaceNameField
            key={`${workspace.id}:${workspace.name}`}
            name={workspace.name}
            onCommit={(next) => renameWorkspace(workspace.id, next)}
          />
        </Field>
        <Field label="Slug" hint="Used in URLs and API scopes.">
          <input
            className={cn(inputClass, 'font-mono')}
            defaultValue={workspace.slug}
            aria-label="Workspace slug"
          />
        </Field>
        <Field
          label="Compliance regime"
          hint="Determines which policy packs are enforced. Changing this is an audited action."
        >
          <div className="flex flex-wrap items-center gap-1.5">
            {workspace.compliance.length ? (
              workspace.compliance.map((c) => (
                <Badge key={c} tone="accent">
                  {c}
                </Badge>
              ))
            ) : (
              <span className="text-xs text-[var(--text-tertiary)]">None configured</span>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                push({
                  tone: 'info',
                  title: 'Requires an administrator',
                  description: 'Compliance regimes are changed by workspace owners.',
                })
              }
            >
              Edit
            </Button>
          </div>
        </Field>
        <Field label="Members" hint="Managed through your identity provider.">
          <span className="tabular text-[13px] text-[var(--text-primary)]">
            {workspace.memberCount} members
          </span>
        </Field>
      </Card>

      <Card>
        <CardHeader
          title="Projects"
          description={`${projects.length} in this workspace.`}
          icon={<Building2 aria-hidden="true" />}
        />
        <ul className="divide-y divide-[var(--border-subtle)]">
          {projects.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <p className="text-[13px] font-medium text-[var(--text-primary)]">{p.name}</p>
                <p className="text-xs text-[var(--text-tertiary)]">
                  {p.platform} · lead {p.lead}
                </p>
              </div>
              <span className="tabular shrink-0 text-xs text-[var(--text-tertiary)]">
                {formatUsd(p.monthlySpendUsd)}/mo
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

/* ------------------------------------------------------------------ agents */

export function AgentsSection() {
  const { push } = useToast()
  const [writeAccess, setWriteAccess] = useState(false)
  const [autoTests, setAutoTests] = useState(true)
  const [budget, setBudget] = useState('1500')

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Agent permissions"
          description="What automated agents are allowed to do in this workspace."
          icon={<Cpu aria-hidden="true" />}
        />

        <div className="border-b border-[var(--border-subtle)] p-4">
          <div className="flex items-start gap-2.5 rounded-lg border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3">
            <ShieldCheck className="mt-px size-4 shrink-0 text-[var(--warn)]" aria-hidden="true" />
            <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
              <span className="font-semibold text-[var(--warn)]">Advisory mode is on.</span> Agents
              can read every connected system, generate tests and assemble evidence, but cannot
              write to a production environment. Granting write access is itself an audited change
              and requires a workspace owner.
            </p>
          </div>
        </div>

        <Field
          label="Production write access"
          hint="Disabled by default. Requires owner approval and a recorded justification."
        >
          <div className="flex items-center gap-2.5">
            <Toggle
              checked={writeAccess}
              onChange={(v) => {
                setWriteAccess(v)
                push({
                  tone: v ? 'warn' : 'ok',
                  title: v ? 'Write access requested' : 'Write access revoked',
                  description: 'Recorded in the audit chain.',
                })
              }}
              label="Production write access"
            />
            <span className="text-xs text-[var(--text-tertiary)]">
              {writeAccess ? 'Pending owner approval' : 'Read-only'}
            </span>
          </div>
        </Field>

        <Field
          label="Auto-generate regression tests"
          hint="After an impact analysis, draft deterministic specs for every impacted node."
        >
          <Toggle
            checked={autoTests}
            onChange={setAutoTests}
            label="Auto-generate regression tests"
          />
        </Field>
      </Card>

      <Card>
        <CardHeader
          title="Spend controls"
          description="Pre-flight approval keeps cost a decision rather than an audit finding."
          icon={<Wallet aria-hidden="true" />}
        />
        <Field label="Monthly budget (USD)" hint="Agents pause when the cap is reached.">
          <input
            className={cn(inputClass, 'tabular max-w-40')}
            type="number"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            aria-label="Monthly budget in USD"
          />
        </Field>
        <Field
          label="Require approval above"
          hint="Any single requirement estimated over this amount needs sign-off before agents run."
        >
          <input
            className={cn(inputClass, 'tabular max-w-40')}
            type="number"
            defaultValue="50"
            aria-label="Approval threshold in USD"
          />
        </Field>
        <Field
          label="Default model"
          hint="Higher tiers are used automatically for impact analysis."
        >
          <select
            className={cn(inputClass, 'max-w-64 cursor-pointer')}
            defaultValue="claude-opus-5"
            aria-label="Default model"
          >
            <option value="claude-opus-5">claude-opus-5</option>
            <option value="claude-sonnet-5">claude-sonnet-5</option>
            <option value="claude-haiku-4-5">claude-haiku-4.5</option>
          </select>
        </Field>
      </Card>
    </div>
  )
}

/* ----------------------------------------------------------- notifications */

const NOTIFICATIONS = [
  { id: 'gate', label: 'A gate is waiting on my decision', defaultOn: true },
  { id: 'blocked', label: 'A policy blocks one of my changes', defaultOn: true },
  { id: 'failed', label: 'Evidence fails or turns flaky', defaultOn: true },
  { id: 'stale', label: 'A connected source goes stale', defaultOn: false },
  { id: 'budget', label: 'Workspace reaches 80% of budget', defaultOn: true },
  { id: 'digest', label: 'Weekly summary of signed-off changes', defaultOn: false },
]

export function NotificationsSection() {
  const [state, setState] = useState<Record<string, boolean>>(
    Object.fromEntries(NOTIFICATIONS.map((n) => [n.id, n.defaultOn])),
  )

  return (
    <Card>
      <CardHeader
        title="Notifications"
        description="Meridian only notifies on things that block a change or need a human."
        icon={<Bell aria-hidden="true" />}
      />
      <div className="p-4">
        <SectionLabel>Email &amp; in-app</SectionLabel>
      </div>
      <ul className="divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">
        {NOTIFICATIONS.map((n) => (
          <li key={n.id} className="flex items-center justify-between gap-4 p-4">
            <p className="text-[13px] text-[var(--text-primary)]">{n.label}</p>
            <Toggle
              checked={state[n.id]}
              onChange={(v) => setState((s) => ({ ...s, [n.id]: v }))}
              label={n.label}
            />
          </li>
        ))}
      </ul>
    </Card>
  )
}

/**
 * Browser session status and capture.
 *
 * Some enterprise configuration exists only on screens — field validation,
 * conditional visibility, the lookup tables behind a leave calculation. No API
 * returns it. Reading it needs a browser that is already signed in, and the
 * only honest way to get one is for a person to sign in themselves.
 *
 * The design problem is that this asks an administrator to run something on
 * their own machine, which no other part of the product does. Three decisions
 * follow from taking that seriously:
 *
 *   - **A download, not a command to copy.** An earlier version showed a
 *     `meridian-capture --meridian … --connection …` line to paste into a
 *     terminal. That put the burden of assembling arguments on the person, and
 *     a mistyped tenant sends them to the wrong customer's login page. The
 *     server knows every value, so it generates the launcher.
 *   - **The reason is stated where the instruction is.** Being asked to run a
 *     local tool is unusual enough that an unexplained instruction reads as a
 *     product defect rather than a security property.
 *   - **The password assurance is inline.** It is the first question a
 *     security-minded admin has, and putting it behind a docs link means they
 *     ask support instead.
 *
 * The session itself is never displayed. It is a bearer credential; showing it
 * would put a live one on screen to no benefit.
 */
import { useState } from 'react'
import {
  Download,
  MonitorPlay,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { Button, buttonClasses } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/overlays'
import type { BrowserSessionStatus } from '@/lib/api-live'
import { api, apiBaseUrl } from '@/lib/api'
import { cn, relativeTime } from '@/lib/utils'

interface Props {
  connectionId: string
  session: BrowserSessionStatus | null
  onChange: () => void
}

/** Minutes remaining, floored, never negative. */
function minutesLeft(seconds: number): number {
  return Math.max(0, Math.floor(seconds / 60))
}

/**
 * How long until the session lapses, in words.
 *
 * Computed from the server's `remainingSeconds` rather than by formatting
 * `expiresAt`: `relativeTime` deliberately collapses every future timestamp to
 * "just now" so clock skew never renders as the future, which is right for the
 * past-tense timestamps it was built for and wrong here — a session with 43
 * minutes left read as "just now", the same words shown once it has expired.
 */
function expiresIn(session: BrowserSessionStatus): string {
  if (!session.expiresAt) return 'Unknown'
  if (session.expired) return 'Expired'
  const mins = minutesLeft(session.remainingSeconds)
  if (mins < 1) return 'Less than a minute'
  if (mins < 60) return `In ${mins} minute${mins === 1 ? '' : 's'}`
  const hours = Math.floor(mins / 60)
  return `In ${hours} hour${hours === 1 ? '' : 's'}`
}

const STEPS = [
  'Download and run the capture tool on your own computer.',
  'A browser opens at your Workday sign-in page.',
  'Sign in as you normally would, including multi-factor.',
  'The window closes by itself and screen discovery becomes available here.',
]

export function BrowserSessionPanel({ connectionId, session, onChange }: Props) {
  const { push } = useToast()
  const [revoking, setRevoking] = useState(false)

  const launcherUrl = `${apiBaseUrl()}/connections/${connectionId}/browser-session/launcher`

  async function revoke() {
    setRevoking(true)
    try {
      await api.revokeBrowserSession(connectionId)
      push({ title: 'Session revoked', tone: 'ok' })
      onChange()
    } catch {
      push({ title: 'Could not revoke the session', tone: 'danger' })
    } finally {
      setRevoking(false)
    }
  }

  const active = session?.present && !session.expired
  const warn = session?.present && (session.expired || session.expiringSoon)

  return (
    <section className="overflow-hidden rounded-lg border border-[var(--border)]">
      <header className="flex items-start gap-3 border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3">
        <div
          className={cn(
            'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md',
            active
              ? 'bg-[var(--ok-subtle)] text-[var(--ok)]'
              : 'bg-[var(--bg-base)] text-[var(--text-tertiary)]',
          )}
        >
          <MonitorPlay className="size-4" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            Screen discovery
          </h3>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            Reads configuration that exists only on Workday screens — validation
            rules, picklist values, and the tables behind leave calculations.
          </p>
        </div>
        <span
          className={cn(
            'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium',
            !session?.present
              ? 'bg-[var(--bg-base)] text-[var(--text-tertiary)]'
              : session.expired
                ? 'bg-[var(--danger-subtle)] text-[var(--danger)]'
                : session.expiringSoon
                  ? 'bg-[var(--warn-subtle)] text-[var(--warn)]'
                  : 'bg-[var(--ok-subtle)] text-[var(--ok)]',
          )}
        >
          {!session?.present
            ? 'Not set up'
            : session.expired
              ? 'Expired'
              : `${minutesLeft(session.remainingSeconds)} min left`}
        </span>
      </header>

      <div className="space-y-4 px-4 py-3">
        {session?.present ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
            {[
              ['Signed in by', session.capturedBy || 'Unknown'],
              ['Captured', session.capturedAt ? relativeTime(session.capturedAt) : '—'],
              ['Last used', session.lastUsedAt ? relativeTime(session.lastUsedAt) : 'Never'],
              ['Expires', expiresIn(session)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-[var(--text-tertiary)]">{label}</dt>
                <dd className="mt-0.5 truncate text-[var(--text-primary)]" title={value}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}

        {warn ? (
          <p className="flex items-start gap-2 rounded-md border border-[var(--warn-border)] bg-[var(--warn-subtle)] px-3 py-2 text-xs text-[var(--warn)]">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>{session?.message}</span>
          </p>
        ) : null}

        {/*
         * Steps are shown whether or not a session exists: re-capturing is the
         * same four steps, and hiding them once set up means hunting for them
         * during an outage, which is exactly when nobody wants to hunt.
         */}
        <ol className="space-y-1.5">
          {STEPS.map((step, index) => (
            <li key={step} className="flex gap-2.5 text-xs text-[var(--text-secondary)]">
              <span className="mt-px flex size-4 shrink-0 items-center justify-center rounded-full bg-[var(--bg-subtle)] text-[10px] font-medium text-[var(--text-tertiary)]">
                {index + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>

        <div className="flex flex-wrap items-center gap-2">
          {/*
           * A plain anchor rather than a fetch: the response is a file
           * download, and letting the browser handle it means no blob URL to
           * revoke and no spinner over a transfer that takes milliseconds.
           */}
          <a
            href={launcherUrl}
            download
            className={buttonClasses('primary')}
          >
            <Download className="size-3.5" aria-hidden="true" />
            {session?.present ? 'Download tool again' : 'Download capture tool'}
          </a>
          {session?.present ? (
            <Button variant="ghost" onClick={onChange} icon={<RefreshCw className="size-3.5" />}>
              Refresh status
            </Button>
          ) : null}
          {session?.present ? (
            <Button variant="ghost" onClick={revoke} disabled={revoking}>
              {revoking ? 'Revoking…' : 'Revoke'}
            </Button>
          ) : null}
        </div>

        {/*
         * The security statement is the whole reason this flow is acceptable,
         * so it sits inline rather than behind a tooltip or a docs link.
         */}
        <p className="flex items-start gap-2 border-t border-[var(--border)] pt-3 text-xs text-[var(--text-secondary)]">
          <ShieldCheck
            className="mt-0.5 size-3.5 shrink-0 text-[var(--ok)]"
            aria-hidden="true"
          />
          <span>
            The tool runs on your computer, not on Meridian's server — which is
            why it is a download. Meridian never receives your password, only
            the session your browser creates after you sign in, and that session
            expires. Discovery can navigate and read; it cannot submit, approve
            or save anything.
          </span>
        </p>
      </div>
    </section>
  )
}

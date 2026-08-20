import { Link, useLocation } from 'react-router-dom'
import { Check, Lock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Tooltip } from '@/components/ui/overlays'

/**
 * The STLC phase rail, drawn as a connected stepper.
 *
 * These four screens are a sequence, not four independent tools, so every one
 * of them carries this rail. It answers the three questions a user has on a
 * multi-step journey at all times: where am I, what is behind me, and what is
 * not open to me yet.
 *
 * The connector between markers is what makes it read as progress rather than
 * four adjacent boxes — a completed segment is filled, an upcoming one is not.
 *
 * What travels through the cycle is the *requirement*, so the requirement is
 * named once above the steps. The steps previously each carried their own
 * artefact ref (TP-1042, and so on), which put the plan's identity where the
 * subject's belongs and repeated the same number four times in different
 * costumes.
 *
 * A locked phase is rendered as a disabled span rather than a link. Letting
 * someone click into a phase whose entry criteria are unmet and then telling
 * them off there would be worse than not offering the click.
 */

/**
 * Temporarily hidden from the UI. The component, its callers and its data are
 * all intact — flip this to `true` to bring the stepper back everywhere at
 * once.
 *
 * A single flag here rather than commenting out the four `below={<StlcRail…>}`
 * call sites: those would rot silently as the pages around them change, and
 * restoring the rail would mean finding all four again.
 */
const STLC_RAIL_VISIBLE = false

export type StlcPhaseId = 'plan' | 'design' | 'execute' | 'close'

export interface StlcPhase {
  id: StlcPhaseId
  label: string
  to: string
  /** Short status line under the label, e.g. "8 cases · 1 in review" */
  detail?: string
  state: 'done' | 'current' | 'available' | 'locked'
  /** Explains the lock — shown on hover so the block is never mysterious */
  lockedReason?: string
}

export interface StlcSubject {
  /** e.g. "MER-1042" */
  ref: string
  /** e.g. "Auto-approve overtime under 4 hours per week" */
  title: string
  /** Link back to the requirement this cycle serves */
  to?: string
}

export function StlcRail({
  phases,
  subject,
  className,
}: {
  phases: StlcPhase[]
  subject?: StlcSubject
  className?: string
}) {
  // After useLocation, never before: an early return above a hook changes the
  // hook order between renders and React throws.
  const location = useLocation()

  if (!STLC_RAIL_VISIBLE) return null

  /**
   * Index of the phase the user is on. Everything before it counts as
   * travelled, which is what fills the connector segments.
   *
   * The route wins over `state: 'current'`. A later phase can legitimately be
   * flagged current by the data while you are standing on an earlier one, and
   * taking that at face value drew the progress line ahead of the user.
   */
  const routeIndex = phases.findIndex((p) => location.pathname.startsWith(p.to.split('?')[0]))
  const activeIndex = routeIndex >= 0 ? routeIndex : phases.findIndex((p) => p.state === 'current')

  /*
   * The ref only — the page title now carries the requirement's name as
   * "Test plan / Auto-approve overtime…", so repeating the title here would
   * put it on screen twice within 40px of itself.
   */
  const heading = subject ? (
    <p className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span className="text-[11px] font-medium tracking-wide text-[var(--text-tertiary)] uppercase">
        Testing life cycle for
      </span>
      {/* An identifier must never break mid-token — on mobile this wrapped
          to "MER-" / "1042" at the hyphen. */}
      {subject.to ? (
        <Link
          to={subject.to}
          className="numeral shrink-0 text-[13px] font-semibold whitespace-nowrap text-[var(--text-primary)] underline-offset-2 hover:underline"
        >
          {subject.ref}
        </Link>
      ) : (
        <span className="numeral shrink-0 text-[13px] font-semibold whitespace-nowrap text-[var(--text-primary)]">
          {subject.ref}
        </span>
      )}
    </p>
  ) : null

  return (
    <nav
      aria-label="Software testing life cycle phases"
      /* No card chrome: the stepper is wayfinding, not content. Boxing it made
         it compete with the cards below for the same visual weight. */
      className={cn('w-full', className)}
    >
      {heading}
      <div className="overflow-x-auto pb-1">
        <ol className="flex min-w-[680px] items-start">
          {phases.map((phase, i) => {
            // Exactly one step is active: the one the route resolved to. Deriving
            // it from activeIndex rather than each phase's own flag stops two
            // steps rendering as current at once.
            const active = i === activeIndex
            const locked = phase.state === 'locked'
            const done = phase.state === 'done'
            // A segment is "travelled" when the phase before it is behind you.
            const reached = done || active || (activeIndex >= 0 && i < activeIndex)

            const marker = (
              <span
                className={cn(
                  'relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full',
                  'border-2 text-[11px] font-semibold transition-colors duration-200',
                  done && 'border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-on)]',
                  // Markers sit on the page background now that the rail has no
                  // card behind it, so they must match it to mask the connector.
                  active &&
                    !done &&
                    'border-[var(--accent)] bg-[var(--bg-base)] text-[var(--accent-text)]',
                  !active &&
                    !done &&
                    'border-[var(--border-default)] bg-[var(--bg-base)] text-[var(--text-tertiary)]',
                )}
              >
                {done ? (
                  <Check className="size-3.5" aria-hidden="true" />
                ) : locked ? (
                  <Lock className="size-3" aria-hidden="true" />
                ) : (
                  // Zero-padded, as in the reference — keeps every marker the
                  // same optical weight regardless of step count.
                  String(i + 1).padStart(2, '0')
                )}
              </span>
            )

            const label = (
              <span className="mt-2 block px-1 text-center">
                <span
                  className={cn(
                    'block truncate text-[13px] font-semibold transition-colors duration-200',
                    active || done ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)]',
                    locked && 'text-[var(--text-tertiary)]',
                  )}
                >
                  {phase.label}
                </span>
                {phase.detail ? (
                  <span className="mt-0.5 block truncate text-[11px] text-[var(--text-tertiary)]">
                    {phase.detail}
                  </span>
                ) : null}
              </span>
            )

            const inner = (
              <span className="flex w-full flex-col items-center">
                {/* Marker row: the connectors are siblings of the marker so they
                  meet its edges exactly rather than passing behind it. */}
                <span className="flex w-full items-center">
                  <span
                    className={cn(
                      'h-0.5 flex-1 rounded-full transition-colors duration-300',
                      i === 0
                        ? 'bg-transparent'
                        : reached
                          ? 'bg-[var(--accent)]'
                          : 'bg-[var(--border-default)]',
                    )}
                    aria-hidden="true"
                  />
                  {marker}
                  <span
                    className={cn(
                      'h-0.5 flex-1 rounded-full transition-colors duration-300',
                      i === phases.length - 1
                        ? 'bg-transparent'
                        : // The segment after a step is filled once the NEXT
                          // step has been reached, so the line stops at where
                          // the user actually is.
                          activeIndex >= 0 && i < activeIndex
                          ? 'bg-[var(--accent)]'
                          : 'bg-[var(--border-default)]',
                    )}
                    aria-hidden="true"
                  />
                </span>
                {label}
              </span>
            )

            return (
              <li key={phase.id} className="min-w-0 flex-1">
                {locked ? (
                  <Tooltip label={phase.lockedReason ?? 'Not available yet'}>
                    <span
                      aria-disabled="true"
                      className="flex w-full cursor-not-allowed flex-col items-center opacity-60"
                    >
                      {inner}
                    </span>
                  </Tooltip>
                ) : (
                  <Link
                    to={phase.to}
                    aria-current={active ? 'step' : undefined}
                    className="group/step flex w-full flex-col items-center rounded-lg py-1 transition-opacity duration-200 hover:opacity-80"
                  >
                    {inner}
                  </Link>
                )}
              </li>
            )
          })}
        </ol>
      </div>
    </nav>
  )
}

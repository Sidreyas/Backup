/**
 * Setup guidance for a connector, rendered from what the backend declares.
 *
 * Connecting Workday is not a matter of pasting a key. Someone has to create
 * an integration user, build a security group, grant domains, activate the
 * policy change, register an API client, mint a refresh token, and — for the
 * configuration that matters most — author custom reports. Eight steps in a
 * system where the tasks have specific names and picking the wrong one
 * produces an account that looks correct and cannot authenticate.
 *
 * So the wizard does not simply present a form. It shows the work first, names
 * each task exactly as Workday's search box does, explains why each step
 * exists, and flags the one people miss. Only then does it ask for values.
 *
 * Nothing here is Workday-specific. Everything is driven by the connector's
 * declaration, so a connector that needs no setup renders no steps.
 */
import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ClipboardList,
  ExternalLink,
  Info,
  Lightbulb,
} from 'lucide-react'
import { Badge, Button, Card } from '@/components/ui/primitives'
import { cn } from '@/lib/utils'
import type { ArtifactBuildStep, RequiredArtifact, SetupStep } from '@/lib/api-live'

/**
 * The tenant-side checklist.
 *
 * Numbered because the order genuinely matters — activating a security policy
 * before granting the permissions does nothing — and each step carries its own
 * justification, because a list of eight demands with no reasons reads as
 * bureaucracy and gets skimmed.
 */
export function SetupSteps({
  steps,
  vendor,
}: {
  steps: SetupStep[]
  vendor: string
}) {
  const [done, setDone] = useState<Set<string>>(new Set())
  const [active, setActive] = useState(0)
  const headingRef = useRef<HTMLHeadingElement>(null)
  // Set when a step change came from a control, so focus moves only then —
  // stealing focus on first render would yank the reader into the middle.
  const shouldFocus = useRef(false)

  useEffect(() => {
    if (!shouldFocus.current) return
    shouldFocus.current = false
    headingRef.current?.focus()
  }, [active])

  if (!steps.length) return null

  const toggle = (id: string) =>
    setDone((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const go = (index: number) => {
    shouldFocus.current = true
    setActive(index)
  }

  const required = steps.filter((s) => !s.optional)
  const completed = required.filter((s) => done.has(s.id)).length

  const step = steps[active]
  const checked = done.has(step.id)
  const isLast = active === steps.length - 1

  return (
    <section aria-labelledby="setup-steps-heading">
      <div className="mb-3">
        <h3
          id="setup-steps-heading"
          className="text-[13px] font-semibold text-[var(--text-primary)]"
        >
          Set up in {vendor}
        </h3>
        <p className="mt-0.5 text-[12px] text-[var(--text-secondary)]">
          Meridian reads only what this account can see. These steps create it.
        </p>
      </div>

      {/*
       * Progress counts steps *marked done*, not the one being viewed: these
       * tasks happen inside Workday, which Meridian cannot observe, so position
       * in the list is not evidence of anything. Optional steps are excluded
       * from the denominator so the bar can legitimately reach 100%.
       */}
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="numeral text-[11px] font-medium text-[var(--text-secondary)]">
          Step {active + 1} of {steps.length}
        </span>
        <span className="numeral text-[11px] text-[var(--text-tertiary)]">
          {completed} of {required.length} marked done
        </span>
      </div>

      {/*
       * A connected stepper: filled tick for done, ringed dot for where you
       * are, hollow ahead — the state of all eight steps readable at a glance.
       *
       * Every node is a real button. Meridian cannot verify work done inside
       * Workday, so gating "Next" would be a lock with nothing behind it, and
       * someone on step 5 routinely needs to re-read step 2.
       */}
      <ol
        className="mb-4 flex items-start"
        aria-label={`${completed} of ${required.length} required steps marked done`}
      >
        {steps.map((s, i) => {
          const isDone = done.has(s.id)
          const isActive = i === active
          // A connector is "travelled" when the step behind it is done, so the
          // line tracks completion rather than mere position.
          const leftFilled = i > 0 && done.has(steps[i - 1].id)
          const rightFilled = isDone

          return (
            <li key={s.id} className="flex min-w-0 flex-1 flex-col items-center">
              <div className="flex w-full items-center">
                <span
                  className={cn(
                    'h-px flex-1 transition-colors',
                    i === 0
                      ? 'bg-transparent'
                      : leftFilled
                        ? 'bg-[var(--ok)]'
                        : 'bg-[var(--border-default)]',
                  )}
                  aria-hidden="true"
                />
                <button
                  type="button"
                  onClick={() => go(i)}
                  aria-current={isActive ? 'step' : undefined}
                  aria-label={`Step ${i + 1} of ${steps.length}: ${s.title}${
                    isDone ? ', marked done' : ''
                  }${s.optional ? ', optional' : ''}`}
                  className={cn(
                    'flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-full border-2 transition-colors',
                    isDone
                      ? 'border-[var(--ok)] bg-[var(--ok)] text-white'
                      : isActive
                        ? 'border-[var(--accent)] bg-[var(--bg-surface)]'
                        : 'border-[var(--border-default)] bg-[var(--bg-surface)] hover:border-[var(--border-strong)]',
                  )}
                >
                  {isDone ? (
                    <Check className="size-3.5" aria-hidden="true" />
                  ) : isActive ? (
                    <span
                      className="size-2 rounded-full bg-[var(--accent)]"
                      aria-hidden="true"
                    />
                  ) : (
                    <span className="numeral text-[10px] font-bold text-[var(--text-tertiary)]">
                      {i + 1}
                    </span>
                  )}
                </button>
                <span
                  className={cn(
                    'h-px flex-1 transition-colors',
                    i === steps.length - 1
                      ? 'bg-transparent'
                      : rightFilled
                        ? 'bg-[var(--ok)]'
                        : 'bg-[var(--border-default)]',
                  )}
                  aria-hidden="true"
                />
              </div>
              {/* Labels are short and centred under their node. Hidden below
                  sm: eight of them at 375px would be unreadable slivers. */}
              <span
                className={cn(
                  'mt-1.5 hidden px-0.5 text-center text-[10px] leading-tight sm:block',
                  isActive
                    ? 'font-semibold text-[var(--text-primary)]'
                    : 'text-[var(--text-tertiary)]',
                )}
                aria-hidden="true"
              >
                {s.short ?? s.title}
              </span>
            </li>
          )
        })}
      </ol>

      <Card
        className={cn(
          'p-4',
          step.critical && !checked && 'border-[var(--warn-border)] bg-[var(--warn-subtle)]',
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          {/* The count leads the heading so a screen reader announces position
              before the title, per the WAI multi-page-form technique. */}
          <h4
            ref={headingRef}
            tabIndex={-1}
            className="text-[14px] font-semibold text-[var(--text-primary)] outline-none"
          >
            <span className="sr-only">
              Step {active + 1} of {steps.length}:{' '}
            </span>
            {step.title}
          </h4>
          {step.critical ? <Badge tone="warn">Most missed</Badge> : null}
          {step.optional ? <Badge tone="neutral">Optional</Badge> : null}
        </div>

        {/*
         * The task name, verbatim and monospaced. A paraphrase ("create an
         * integration user") forces the admin to guess between similar tasks,
         * and guessing wrong here creates an account that looks right and
         * cannot authenticate.
         *
         * Omitted entirely when the step has no task: some steps are settings
         * within a screen you are already on, and an empty "Search for:" label
         * sends someone hunting for a task that does not exist.
         */}
        {step.task ? (
          <p className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="text-[var(--text-tertiary)]">Search for:</span>
            <code className="rounded bg-[var(--bg-surface-2)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
              {step.task}
            </code>
          </p>
        ) : null}

        <p className="mt-2.5 text-[12px] leading-relaxed text-[var(--text-secondary)]">
          {step.detail}
        </p>

        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-[var(--text-tertiary)]">
          <Info className="mt-px size-3 shrink-0" aria-hidden="true" />
          {step.why}
        </p>

        <label className="mt-3 flex w-fit cursor-pointer items-center gap-2 text-[12px] text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={checked}
            onChange={() => toggle(step.id)}
            className="size-3.5 accent-[var(--accent)]"
          />
          Mark this step done
        </label>
      </Card>

      <div className="mt-3 flex items-center justify-between gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="size-3.5" />}
          disabled={active === 0}
          onClick={() => go(active - 1)}
        >
          Back
        </Button>
        <span className="numeral text-[11px] text-[var(--text-tertiary)]">
          {active + 1} / {steps.length}
        </span>
        <Button
          variant={isLast ? 'ghost' : 'secondary'}
          size="sm"
          disabled={isLast}
          onClick={() => go(active + 1)}
        >
          Next
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Button>
      </div>
    </section>
  )
}

/**
 * Limits, stated before the customer invests a day in setup.
 *
 * Workday exposes no API for business process definitions. Discovering that
 * after building an integration would be a betrayal of the effort; saying it
 * on the connector card costs a paragraph.
 */
export function ConnectorLimitations({
  items,
  open: controlledOpen,
  onOpenChange,
}: {
  items: string[]
  /** Controlled when provided, so a header button can drive it. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const [uncontrolled, setUncontrolled] = useState(false)
  const isControlled = controlledOpen !== undefined
  const open = isControlled ? controlledOpen : uncontrolled
  const setOpen = (v: boolean) => (isControlled ? onOpenChange?.(v) : setUncontrolled(v))

  if (!items.length) return null

  return (
    <div>
      {/*
       * Collapsed by default, but the label carries the count and the noun.
       * A bare "⚠ 3" gives no reason to click; hidden content that nobody
       * expands is worse than content that was never written. These are
       * limitations to weigh, not errors blocking the current action, so
       * they earn a disclosure rather than a permanent banner.
       */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls="connector-limitations"
        className={cn(
          'flex w-full cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors',
          'border-[var(--warn-border)] bg-[var(--warn-subtle)] hover:brightness-[0.98]',
        )}
      >
        <AlertTriangle className="size-4 shrink-0 text-[var(--warn)]" aria-hidden="true" />
        <span className="min-w-0 flex-1 text-[12px] font-semibold text-[var(--text-primary)]">
          {items.length} {items.length === 1 ? 'limitation' : 'limitations'}
          <span className="font-normal text-[var(--text-secondary)]">
            {' '}
            — worth reading before you set this up
          </span>
        </span>
        <ChevronDown
          className={cn(
            'size-4 shrink-0 text-[var(--text-tertiary)] transition-transform',
            open && 'rotate-180',
          )}
          aria-hidden="true"
        />
      </button>

      {open ? (
        <ul
          id="connector-limitations"
          className="mt-1.5 space-y-1.5 rounded-lg border border-[var(--warn-border)] bg-[var(--warn-subtle)] p-3"
        >
          {items.map((item) => (
            <li
              key={item}
              className="flex items-start gap-2 text-[12px] leading-relaxed text-[var(--text-secondary)]"
            >
              <span
                className="mt-1.5 size-1 shrink-0 rounded-full bg-[var(--warn)]"
                aria-hidden="true"
              />
              {item}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/**
 * The report pack.
 *
 * Each report is expandable rather than listed flat: the field specification
 * is what someone actually needs while sitting in Workday's report builder,
 * and every report's fields shown at once is a wall nobody reads.
 */
export function RequiredArtifacts({
  artifacts,
  vendor,
  buildSteps = [],
}: {
  artifacts: RequiredArtifact[]
  vendor: string
  buildSteps?: ArtifactBuildStep[]
}) {
  const [open, setOpen] = useState<string | null>(artifacts[0]?.id ?? null)

  if (!artifacts.length) return null

  return (
    <section aria-label="Discovery reports">
      <div className="mb-3">
        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--text-primary)]">
          <ClipboardList className="size-4" aria-hidden="true" />
          Discovery reports
          <Badge tone="neutral">Optional, high value</Badge>
        </h3>
        {/* The limitations box above already explains why these are needed.
            This says what to do about it, and nothing more. */}
        <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--text-secondary)]">
          Build these in {vendor} and Meridian reads them like any other source. You
          can connect without them and add them later; each one deepens the graph.
        </p>
      </div>

      {/*
       * The procedure comes before the list. It is the same for all six
       * reports, and someone with no Workday background needs to know where
       * they are going before a column specification means anything.
       */}
      {buildSteps.length ? (
        <div className="mb-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <p className="text-[12px] font-semibold text-[var(--text-primary)]">
            How to build any of them
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">
            Same four steps every time — only the name, source and columns change.
          </p>

          <ol className="mt-2.5 space-y-2.5">
            {buildSteps.map((s, i) => (
              <li key={s.id} className="flex items-start gap-2.5">
                <span
                  className={cn(
                    'numeral mt-px flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                    s.critical
                      ? 'bg-[var(--warn)] text-white'
                      : 'border border-[var(--border-default)] text-[var(--text-tertiary)]',
                  )}
                  aria-hidden="true"
                >
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[12px] font-medium text-[var(--text-primary)]">
                      {s.title}
                    </span>
                    {s.critical ? <Badge tone="warn">Most missed</Badge> : null}
                  </div>

                  {s.task ? (
                    <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                      <span className="text-[var(--text-tertiary)]">Search for:</span>
                      <code className="rounded bg-[var(--bg-surface)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                        {s.task}
                      </code>
                    </p>
                  ) : null}

                  <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-secondary)]">
                    {s.detail}
                  </p>

                  {/* The failure, not just the instruction: these two settings
                      fail silently, and naming the symptom is what lets someone
                      recognise it later. */}
                  {s.symptom ? (
                    <p className="mt-1 flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                      <AlertTriangle
                        className="mt-px size-3 shrink-0 text-[var(--warn)]"
                        aria-hidden="true"
                      />
                      <span>
                        <span className="font-medium text-[var(--text-secondary)]">
                          If skipped:
                        </span>{' '}
                        {s.symptom}
                      </span>
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <p className="mb-2 text-[11px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
        The {artifacts.length} reports
      </p>

      <ul className="space-y-2">
        {artifacts.map((artifact) => {
          const expanded = open === artifact.id
          return (
            <li key={artifact.id}>
              <Card className="overflow-hidden p-0">
                <button
                  onClick={() => setOpen(expanded ? null : artifact.id)}
                  aria-expanded={expanded}
                  className="flex w-full cursor-pointer items-start gap-3 p-3 text-left transition-colors hover:bg-[var(--bg-hover)]"
                >
                  <ChevronDown
                    className={cn(
                      'mt-0.5 size-4 shrink-0 text-[var(--text-tertiary)] transition-transform',
                      expanded && 'rotate-180',
                    )}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-semibold text-[var(--text-primary)]">
                      {artifact.title}
                    </span>
                    <span className="mt-0.5 block text-[12px] text-[var(--text-secondary)]">
                      {artifact.unlocks}
                    </span>
                  </span>
                </button>

                {expanded ? (
                  <div className="border-t border-[var(--border-subtle)] px-3 pb-3 pt-3">
                    <dl className="space-y-2 text-[12px]">
                      <div>
                        <dt className="text-[10px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
                          Name it
                        </dt>
                        <dd className="mt-0.5">
                          <code className="rounded bg-[var(--bg-surface-2)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                            {artifact.reportName}
                          </code>
                          <span className="ml-1.5 text-[11px] text-[var(--text-tertiary)]">
                            or tell Meridian the name you used
                          </span>
                        </dd>
                      </div>

                      <div>
                        <dt className="text-[10px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
                          Build it on
                        </dt>
                        {/* The single most common setup failure is the wrong
                            data source, so it is stated exactly rather than
                            left to the report author's judgement. */}
                        <dd className="mt-0.5 text-[var(--text-secondary)]">
                          {artifact.dataSource}
                        </dd>
                      </div>

                      <div>
                        <dt className="text-[10px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
                          Columns to include
                        </dt>
                        <dd className="mt-1">
                          <ul className="space-y-1">
                            {artifact.fields.map((field) => (
                              <li key={field.name} className="flex items-start gap-1.5">
                                <code className="shrink-0 rounded bg-[var(--bg-surface-2)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                                  {field.name}
                                </code>
                                {!field.required ? (
                                  <span className="mt-0.5 shrink-0 text-[10px] text-[var(--text-tertiary)]">
                                    optional
                                  </span>
                                ) : null}
                                <span className="text-[11px] text-[var(--text-tertiary)]">
                                  {field.description}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </dd>
                      </div>

                      <div className="rounded-lg bg-[var(--bg-surface-2)] p-2.5">
                        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--text-secondary)]">
                          <Lightbulb
                            className="mt-px size-3 shrink-0 text-[var(--text-tertiary)]"
                            aria-hidden="true"
                          />
                          <span>
                            <span className="font-medium text-[var(--text-primary)]">
                              Why a report:
                            </span>{' '}
                            {artifact.whyReport}
                          </span>
                        </p>
                        <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--text-secondary)]">
                          <ExternalLink
                            className="mt-px size-3 shrink-0 text-[var(--text-tertiary)]"
                            aria-hidden="true"
                          />
                          <span>
                            <span className="font-medium text-[var(--text-primary)]">
                              Produces:
                            </span>{' '}
                            {artifact.produces}
                          </span>
                        </p>
                      </div>

                      {artifact.notes.length ? (
                        <ul className="space-y-1">
                          {artifact.notes.map((note) => (
                            <li
                              key={note}
                              className="text-[11px] leading-relaxed text-[var(--text-tertiary)]"
                            >
                              {note}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </dl>
                  </div>
                ) : null}
              </Card>
            </li>
          )
        })}
      </ul>

      <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-[var(--bg-surface-2)] p-2.5 text-[11px] leading-relaxed text-[var(--text-secondary)]">
        <Info className="mt-px size-3 shrink-0 text-[var(--text-tertiary)]" aria-hidden="true" />
        Every report must be an <strong className="font-semibold">Advanced</strong> report with
        “Enable As Web Service” ticked, and shared with the integration user’s security group. A
        report the account cannot see returns a permission error rather than empty data.
      </p>
    </section>
  )
}

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Globe,
  Loader2,
  Wrench,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { CrawlResult, ProposedCase } from '@/lib/types'

/**
 * Milliseconds between words as an answer streams in.
 *
 * At 55ms a 300-word answer took 16 seconds to reveal — six times longer than
 * the model took to produce it, which turns the animation from pacing into
 * waiting. 16ms is roughly one word per frame: fast enough to read as arriving
 * rather than being typed at you, and a 300-word answer lands in under five
 * seconds.
 */
const WORD_MS = 16

/**
 * How long one word takes to resolve.
 *
 * Must stay close to `WORD_MS`. At 420ms against a 55ms cadence about eight
 * words were mid-animation simultaneously, so the tail of the sentence was
 * permanently half-blurred and the whole reveal read as sluggish — the blur
 * was the lag, not the pacing.
 */
const WORD_FADE_MS = 90

/**
 * Reveals text a word at a time, each word resolving out of blur.
 *
 * The answer arrives from the API whole, so this is presentation rather than
 * transport: it paces the reveal so a long answer can be read as it lands
 * instead of appearing as a wall. Two consequences that shaped it:
 *
 *  - It streams once, on mount, and stops. An answer that re-animated on every
 *    re-render would rewrite settled history further up the transcript.
 *  - `onAdvance` fires per word so the page can keep the view pinned to the
 *    bottom while the text grows, which is the whole point of streaming.
 */
export function StreamingText({
  text,
  onAdvance,
  onDone,
}: {
  text: string
  onAdvance?: () => void
  onDone?: () => void
}) {
  const words = text.split(' ')
  const [count, setCount] = useState(0)
  const done = count >= words.length

  /*
   * Held in refs so a parent that passes inline callbacks does not restart the
   * timer on every render — the effect depends on `count` alone.
   */
  const advanceRef = useRef(onAdvance)
  const doneRef = useRef(onDone)
  advanceRef.current = onAdvance
  doneRef.current = onDone

  /*
   * Driven by the frame clock rather than one `setTimeout` per word.
   *
   * A 16ms timeout is below what `setTimeout` reliably delivers — the browser
   * clamps it, background tabs clamp it harder, and each tick cost a render,
   * so a long answer produced hundreds of them and stuttered. Advancing by
   * elapsed time inside `requestAnimationFrame` reveals however many words the
   * frame budget allows, which keeps the pace steady on a slow machine
   * instead of simply running late.
   */
  useEffect(() => {
    if (!words.length) return

    let frame = 0
    let start = 0
    let last = -1

    const tick = (now: number) => {
      if (!start) start = now
      const reached = Math.min(words.length, Math.floor((now - start) / WORD_MS) + 1)

      if (reached !== last) {
        last = reached
        setCount(reached)
        advanceRef.current?.()
      }
      if (reached < words.length) {
        frame = requestAnimationFrame(tick)
      } else {
        doneRef.current?.()
      }
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [words.length])

  return (
    <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
      {/*
       * The full text stays in the accessibility tree from the first frame.
       * Revealing it word by word to a screen reader would either read a
       * half-sentence or re-announce the whole answer on every tick.
       */}
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {words.slice(0, count).map((word, i) => (
          <span
            key={i}
            className="inline [will-change:filter,opacity]"
            style={{
              animation: `stream-in ${WORD_FADE_MS}ms cubic-bezier(0.22,0.61,0.25,1) both`,
            }}
          >
            {word}{' '}
          </span>
        ))}
        {!done ? (
          <span
            className="ml-0.5 inline-block h-3 w-0.5 translate-y-0.5 rounded-full bg-[var(--text-primary)]"
            style={{ animation: 'fade 150ms ease-out both' }}
          />
        ) : null}
      </span>
    </p>
  )
}

/**
 * A site crawl, rendered inline in the transcript.
 *
 * The crawl is the evidence for everything proposed after it, so it sits with
 * the claim rather than in a side panel: "these are the pages I found, and
 * these are the tests I wrote from them" reads as one argument.
 */
export function CrawlCard({ crawl }: { crawl: CrawlResult }) {
  const [open, setOpen] = useState(false)
  const running = crawl.status === 'running'

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border-subtle)]">
      <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-2">
        {running ? (
          <Loader2
            className="size-3.5 shrink-0 animate-spin text-[var(--accent)]"
            aria-hidden="true"
          />
        ) : crawl.status === 'failed' ? (
          <Globe className="size-3.5 shrink-0 text-[var(--danger)]" aria-hidden="true" />
        ) : (
          <Check className="size-3.5 shrink-0 text-[var(--ok)]" aria-hidden="true" />
        )}
        <span className="text-[12px] font-medium text-[var(--text-primary)]">
          {running ? 'Website crawl running' : crawl.status === 'failed' ? 'Crawl failed' : 'Website crawl'}
        </span>
        <span className="ml-auto text-[11px] text-[var(--text-tertiary)]">
          {running ? 'Started just now' : `${crawl.pages.length} pages`}
        </span>
      </div>

      <dl className="divide-y divide-[var(--border-subtle)] text-[12px]">
        <div className="flex items-baseline gap-3 px-3 py-2">
          <dt className="w-[68px] shrink-0 text-[var(--text-tertiary)]">Start URL</dt>
          <dd className="min-w-0 flex-1 truncate">
            {/*
             * Not a live link. The crawl target is someone's application, and a
             * clickable URL in a governance record invites a click that leaves
             * the audit trail — the text is what matters here, not navigation.
             */}
            <span className="text-[var(--accent)]">{crawl.startUrl}</span>
          </dd>
        </div>
        <div className="flex items-baseline gap-3 px-3 py-2">
          <dt className="w-[68px] shrink-0 text-[var(--text-tertiary)]">Max depth</dt>
          <dd className="numeral text-[var(--text-secondary)]">{crawl.maxDepth}</dd>
        </div>
      </dl>

      {crawl.error ? (
        <p className="border-t border-[var(--border-subtle)] bg-[var(--danger-subtle)] px-3 py-2 text-[11px] text-[var(--danger)]">
          {crawl.error}
        </p>
      ) : null}

      {crawl.pages.length > 0 ? (
        <div className="border-t border-[var(--border-subtle)]">
          <button
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-[var(--bg-hover)]"
          >
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">
              Crawled pages ({crawl.pages.length})
            </span>
            <ChevronDown
              className={cn(
                'ml-auto size-3.5 text-[var(--text-tertiary)] transition-transform duration-200',
                open && 'rotate-180',
              )}
              aria-hidden="true"
            />
          </button>

          {open ? (
            <ul className="divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">
              {crawl.pages.map((p) => (
                <li key={p.url} className="px-3 py-2">
                  <p className="text-[12px] font-medium text-[var(--text-primary)]">{p.title}</p>
                  <p className="mt-0.5 truncate text-[11px] text-[var(--text-tertiary)]">{p.url}</p>
                  {/* What the crawler judged worth testing here. Without it the
                      page list is a sitemap, not a finding. */}
                  <p className="mt-1 text-[11px] leading-snug text-[var(--text-secondary)]">
                    {p.note}
                  </p>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

/**
 * Cases the assistant proposed on this turn.
 *
 * Labelled "Proposed", not "Created". They are not in the plan until a
 * reviewer accepts them — saying "Created" would claim a write that has not
 * happened and put unreviewed machine output into the record.
 */
export function GeneratedCasesCard({
  cases,
  accepted,
  onAccept,
  busy,
}: {
  cases: ProposedCase[]
  accepted: boolean
  onAccept: () => void
  busy?: boolean
}) {
  const [expanded, setExpanded] = useState<string | null>(null)

  /* Grouped by journey, as the crawl found them. */
  const groups = cases.reduce<Record<string, ProposedCase[]>>((acc, c) => {
    ;(acc[c.group] ??= []).push(c)
    return acc
  }, {})

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border-subtle)]">
      <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-2">
        <span className="text-[12px] font-semibold text-[var(--text-primary)]">
          {accepted ? 'Test cases added' : 'Proposed test cases'}
        </span>
        <span className="numeral ml-auto text-[11px] text-[var(--text-tertiary)]">
          {cases.length}
        </span>
      </div>

      {Object.entries(groups).map(([group, list]) => (
        <section key={group}>
          <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-surface-2)]/60 px-3 py-1">
            <h4 className="text-[10px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
              {group}
            </h4>
          </div>
          <ul className="divide-y divide-[var(--border-subtle)]">
            {list.map((c) => {
              const open = expanded === c.id
              return (
                <li key={c.id} className="px-3 py-2">
                  <div className="flex items-start gap-2">
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12px] font-medium text-[var(--text-primary)]">
                        {c.title}
                      </span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-[var(--text-secondary)]">
                        {c.summary}
                      </span>
                    </span>
                    {accepted ? (
                      <span className="flex shrink-0 items-center gap-1 text-[11px] text-[var(--ok)]">
                        <Check className="size-3" aria-hidden="true" />
                        Added
                      </span>
                    ) : (
                      <span className="shrink-0 text-[11px] text-[var(--text-tertiary)]">
                        Proposed
                      </span>
                    )}
                  </div>

                  <button
                    onClick={() => setExpanded(open ? null : c.id)}
                    aria-expanded={open}
                    className="mt-1 cursor-pointer text-[11px] text-[var(--accent)] hover:underline"
                  >
                    {open ? 'Hide steps' : 'Show steps'}
                  </button>

                  {open ? (
                    <ol className="mt-1.5 space-y-1">
                      {c.steps.map((s, i) => (
                        <li
                          key={s}
                          className="flex gap-2 text-[11px] leading-snug text-[var(--text-secondary)]"
                        >
                          <span className="numeral shrink-0 text-[var(--text-tertiary)]">
                            {i + 1}
                          </span>
                          {s}
                        </li>
                      ))}
                    </ol>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </section>
      ))}

      <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border-subtle)] px-3 py-2">
        {accepted ? (
          <>
            <span className="text-[11px] text-[var(--text-secondary)]">
              Added to the plan as drafts. They still need review before they can run.
            </span>
            <Link
              to="/test-cases"
              className="ml-auto flex items-center gap-1 text-[11px] font-medium text-[var(--accent)] hover:underline"
            >
              Review them
              <ArrowUpRight className="size-3" aria-hidden="true" />
            </Link>
          </>
        ) : (
          <>
            <span className="text-[11px] text-[var(--text-secondary)]">
              Nothing is written to the plan until you add them.
            </span>
            <button
              onClick={onAccept}
              disabled={busy}
              className={cn(
                'ml-auto flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1',
                'bg-[var(--accent)] text-[11px] font-medium text-[var(--accent-on)]',
                'transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-60',
              )}
            >
              {busy ? (
                <Loader2 className="size-3 animate-spin" aria-hidden="true" />
              ) : (
                <Check className="size-3" aria-hidden="true" />
              )}
              Add {cases.length} cases
            </button>
          </>
        )}
      </div>
    </div>
  )
}

/** The "4 tool calls completed" line from the reference. */
export function ToolCallSummary({ calls }: { calls: { label: string; detail?: string }[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-primary)]"
      >
        <Wrench className="size-3" aria-hidden="true" />
        {calls.length} tool call{calls.length === 1 ? '' : 's'} completed
        <ChevronDown
          className={cn('size-3 transition-transform duration-200', open && 'rotate-180')}
          aria-hidden="true"
        />
      </button>
      {open ? (
        <ul className="mt-1 space-y-0.5 border-l border-[var(--border-subtle)] pl-2.5">
          {calls.map((c) => (
            <li key={c.label} className="text-[11px] text-[var(--text-secondary)]">
              <span className="font-medium">{c.label}</span>
              {c.detail ? (
                <span className="text-[var(--text-tertiary)]"> — {c.detail}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

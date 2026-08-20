import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertOctagon,
  ArrowDown,
  ArrowLeft,
  BookOpen,
  Check,
  ChevronDown,
  CornerDownLeft,
  Loader2,
  MessagesSquare,
  Sparkles,
  Target,
} from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, SectionLabel, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/overlays'
import { ConfidenceBadge } from '@/components/domain/status'
import { api, extractUrl, looksLikeGenerateRequest, looksLikeRunRequest } from '@/lib/api'
import { useAsync } from '@/lib/useAsync'
import { useStlc } from '@/lib/useStlc'
import { CURRENT_USER } from '@/lib/mock-data'
import { cn, relativeTime } from '@/lib/utils'
import { WorkflowRail } from '@/components/domain/WorkflowRail'
import {
  CrawlCard,
  GeneratedCasesCard,
  StreamingText,
  ToolCallSummary,
} from '@/components/domain/ChatArtefacts'
import { AttachMenu, AttachmentChips, type Attachment } from '@/components/domain/AttachMenu'
import type { ChatMessage, CrawlResult, ProposedCase, RunStatus } from '@/lib/types'

/** Host only, for prose. Falls back to the raw string when unparseable. */
function safeHostname(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

export function RequirementChatPage() {
  const { id = 'req-1' } = useParams()
  const { data: requirement, loading: reqLoading } = useAsync(() => api.getRequirement(id), [id])
  const { data: initialThread, loading: threadLoading } = useAsync(() => api.getThread(id), [id])

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [attachments, setAttachments] = useState<Attachment[]>([])

  /*
   * Whether this requirement has produced test cases yet. Drives whether the
   * side panel exists at all — see the grid below.
   */
  /* Crawl held for the thread, so a later "generate cases" has something to
     generate from. */
  const [crawl, setCrawl] = useState<CrawlResult | null>(null)
  const [acceptedCaseMsgIds, setAcceptedCaseMsgIds] = useState<Set<string>>(new Set())
  const [accepting, setAccepting] = useState<string | null>(null)
  /* Cases accepted in this thread, mirrored into the panel. */
  const [proposedInThread, setProposedInThread] = useState<ProposedCase[]>([])
  /* Which of those a person has actually accepted. The panel shows both, but
     a proposal and a kept case are not the same claim. */
  const [acceptedIds, setAcceptedIds] = useState<Set<string>>(new Set())
  /*
   * Outcome per proposed case from a rehearsal run in this thread. Held here
   * rather than in the rail so the rail stays a pure view — it renders what the
   * conversation has established, and does not run anything itself.
   */
  const [runStatusById, setRunStatusById] = useState<Record<string, RunStatus>>({})

  const { cases: stlcCases } = useStlc(id)
  /*
   * The panel opens when this requirement has cases — either already on record,
   * or accepted in this conversation. The second half is what makes the panel
   * appear as a result of the chat rather than only on reload.
   */
  const hasCases = stlcCases.length > 0 || proposedInThread.length > 0
  /*
   * What to offer next, derived from where the thread has got to. Each entry
   * is only shown while it is actually possible: "Run the tests" before any
   * exist would fall through to a generic reply and teach people the chips
   * are decorative.
   */
  const hasRun = Object.keys(runStatusById).length > 0
  const followUps =
    proposedInThread.length > 0 && !hasRun
      ? ['Run the tests', 'Add coverage for checkout', 'What did the crawl miss?']
      : hasRun
        ? ['Test checkout details & promos', 'Test cart management & fees', 'Add edge cases']
        : []

  /*
   * The one message allowed to animate its text in.
   *
   * Set when a reply arrives in this session and cleared when it finishes, so
   * the thread loaded from history renders instantly — replaying an old answer
   * word by word would present settled record as if it were happening now.
   */
  const [streamingId, setStreamingId] = useState<string | null>(null)

  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [focused, setFocused] = useState(false)
  const [atBottom, setAtBottom] = useState(true)
  const endRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const { push } = useToast()

  useEffect(() => {
    if (initialThread) setMessages(initialThread)
  }, [initialThread])

  /*
   * Only follow the conversation when the reader is already at the bottom.
   * Yanking them down mid-scroll while they are reading an earlier turn is the
   * standard way chat UIs become annoying.
   */
  useEffect(() => {
    if (atBottom) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, sending, atBottom])

  /** Grow the composer with its content, up to the max-height cap. */
  useEffect(() => {
    const el = composerRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [draft])

  async function send() {
    const text = draft.trim()
    if (!text || sending) return
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      at: new Date().toISOString(),
    }
    setMessages((m) => [...m, userMsg])
    setDraft('')
    setSending(true)

    /*
     * A URL in the message, or one attached, is a target to crawl. The crawl
     * comes first because everything proposed afterwards is derived from it —
     * generating cases for an app nobody has looked at would be invention.
     */
    const url =
      extractUrl(text) ?? attachments.find((a) => a.kind === 'url' && /^https?:/.test(a.label))?.label

    try {
      if (url) {
        // Named `result`, not `crawl`: a local named `crawl` shadows the state
        // variable for the whole function body, so the generate branch below
        // read the shadow and never saw a crawl had happened.
        const result = await api.crawlSite(url)
        setCrawl(result)
        const crawlMsgId = `m-crawl-${Date.now()}`
        setStreamingId(crawlMsgId)
        setMessages((m) => [
          ...m,
          {
            id: crawlMsgId,
            role: 'assistant',
            at: new Date().toISOString(),
            model: 'claude-opus-5',
            content: `I crawled ${safeHostname(url)} to see what is worth testing. It is reachable without a login, and the core journey runs from discovery through to checkout.\n\nTell me to generate test cases and I will draft a first set against that journey.`,
            toolCalls: [
              { label: 'crawl_site', detail: `${result.pages.length} pages, depth ${result.maxDepth}` },
              { label: 'analyse_structure', detail: 'Identified 2 journeys' },
            ],
            crawl: result,
          },
        ])
        return
      }

      /*
       * Running is checked before generating: "run the tests" carries no
       * generate verb, but "create and run the tests" carries both, and at that
       * point there is nothing to run yet. Generate wins by being checked
       * second only for messages that match neither cleanly.
       */
      if (looksLikeRunRequest(text) && proposedInThread.length > 0) {
        const { statusById } = await api.runProposedCases(proposedInThread)
        setRunStatusById(statusById)
        const passed = Object.values(statusById).filter((s) => s === 'passed').length
        const total = proposedInThread.length
        const runMsgId = `m-run-${Date.now()}`
        setStreamingId(runMsgId)
        setMessages((m) => [
          ...m,
          {
            id: runMsgId,
            role: 'assistant',
            at: new Date().toISOString(),
            model: 'claude-opus-5',
            content:
              passed === total
                ? `All ${total} tests passed on the first run. The core journey works end to end: ${proposedInThread.map((c) => c.title.toLowerCase()).join(', ')}.\n\nThese ran against the crawled site as a rehearsal — nothing is written to the plan until you add the cases.`
                : `${passed} of ${total} passed. The failures are listed in the panel; open one to see which step it stopped at.`,
            toolCalls: [{ label: 'run_cases', detail: `${passed}/${total} passed` }],
            runSummary: { passed, total },
          },
        ])
        return
      }

      /*
       * Only generate when asked, and only when there is a crawl to generate
       * from. Without the crawl the cases would not be grounded in anything,
       * which is the failure mode this whole product is built against.
       */
      if (looksLikeGenerateRequest(text) && crawl) {
        const proposed = await api.generateCasesFromCrawl(crawl)
        const genMsgId = `m-gen-${Date.now()}`
        setStreamingId(genMsgId)
        setMessages((m) => [
          ...m,
          {
            id: genMsgId,
            role: 'assistant',
            at: new Date().toISOString(),
            model: 'claude-opus-5',
            content: `Here is a first wave covering the core journey I found — discovery and ordering. Each one is drafted from a page the crawl actually reached, not from assumptions about how a storefront usually works.`,
            toolCalls: [{ label: 'generate_cases', detail: `${proposed.length} proposed` }],
            generatedCases: proposed,
          },
        ])
        /*
         * Open the panel as soon as they exist, not on accept. Generating is
         * the moment there is something to look at, and making someone click
         * Add before they can see the list asks them to commit to work they
         * have not read yet.
         */
        setProposedInThread(proposed)
        return
      }

      const reply = await api.sendMessage(id, text)
      setStreamingId(reply.id)
      setMessages((m) => [...m, reply])
    } catch {
      push({
        tone: 'danger',
        title: 'Could not reach the assistant',
        description: 'Your message was not sent. Try again.',
      })
    } finally {
      setSending(false)
    }
  }

  /**
   * Accept the proposed cases into the plan.
   *
   * They land as drafts needing review, not as approved cases — accepting a
   * proposal is agreeing it is worth having, which is a different act from
   * agreeing it is correct.
   */
  async function acceptCases(message: ChatMessage) {
    if (!message.generatedCases?.length) return
    setAccepting(message.id)
    try {
      // The panel already lists them — they went in at generation. Accepting
      // records that a person agreed to keep them, which is what changes.
      setAcceptedCaseMsgIds((s) => new Set(s).add(message.id))
      setAcceptedIds((s) => {
        const next = new Set(s)
        message.generatedCases!.forEach((c) => next.add(c.id))
        return next
      })
      push({
        tone: 'ok',
        title: `${message.generatedCases.length} cases added`,
        description: 'They are drafts until reviewed. Nothing runs before someone approves them.',
      })
    } finally {
      setAccepting(null)
    }
  }

  return (
    // h-full rather than a viewport calculation: this page fills the scroll
    // container it is given. Subtracting a fixed header height here left a gap
    // the moment the shell's top bar was removed.
    <div className="flex h-full flex-col">
      <PageHeader
        eyebrow="Requirement analysis"
        title={reqLoading ? 'Loading…' : (requirement?.title ?? 'Requirement')}
        icon={<MessagesSquare aria-hidden="true" />}
        tone="accent"
        /*
         * The ref sits beside the name it identifies — it is part of what this
         * requirement is called, not a status of it. Stage, risk and platform
         * are gone: they were three chips restating what the conversation
         * itself makes plain, and they pushed the transcript down the page.
         */
        titleSuffix={
          requirement ? (
            <span className="numeral text-[13px] font-medium text-[var(--text-tertiary)]">
              {requirement.ref}
            </span>
          ) : null
        }
        actions={
          <>
            <Button
              variant="ghost"
              icon={<ArrowLeft className="size-4" aria-hidden="true" />}
              onClick={() => history.back()}
            >
              Back
            </Button>
            <Link to={`/impact/${id}`}>
              <Button variant="primary" icon={<Target className="size-4" aria-hidden="true" />}>
                View impact analysis
              </Button>
            </Link>
          </>
        }
      />

      {/*
       * Flex with an animated width, not a grid template.
       *
       * grid-template-columns does not interpolate between "one column" and
       * "two", so the panel used to snap into place and shove the transcript
       * sideways in a single frame. A width transition on the panel lets the
       * conversation reflow with it.
       */}
      <div className="flex min-h-0 flex-1">
        {/* Conversation */}
        <div
          className={cn(
            'relative flex min-w-0 flex-1 flex-col',
            hasCases && 'lg:border-r lg:border-[var(--border-subtle)]',
          )}
        >
          <div
            ref={scrollRef}
            onScroll={(e) => {
              const el = e.currentTarget
              setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
            }}
            className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6"
          >
            <div className="mx-auto max-w-3xl space-y-5">
              {threadLoading ? (
                <div className="space-y-4">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-24 w-full rounded-xl" />
                  ))}
                </div>
              ) : messages.length === 0 ? (
                <EmptyThread onPick={(q) => setDraft(q)} />
              ) : (
                messages.map((m) => (
                  <MessageBubble
                    key={m.id}
                    message={m}
                    acceptedCases={acceptedCaseMsgIds.has(m.id)}
                    accepting={accepting === m.id}
                    onAcceptCases={() => void acceptCases(m)}
                    streaming={streamingId === m.id}
                    /*
                     * Keep following the text as it grows, but only while the
                     * reader has not scrolled away — same rule the transcript
                     * itself follows.
                     */
                    onStreamAdvance={() => {
                      if (atBottom)
                        endRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' })
                    }}
                    onStreamDone={() => setStreamingId(null)}
                  />
                ))
              )}
              {sending ? (
                <div className="flex items-center gap-2 text-sm text-[var(--text-tertiary)]">
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  <span>Retrieving context from the knowledge graph…</span>
                </div>
              ) : null}
              <div ref={endRef} />
            </div>
          </div>

          {/* Jump back to the newest turn — only offered when it is off-screen,
              so it never sits there as permanent noise. */}
          {!atBottom && messages.length > 0 ? (
            <button
              onClick={() => endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })}
              className={cn(
                'absolute bottom-28 left-1/2 z-[var(--z-sticky)] flex -translate-x-1/2 cursor-pointer',
                'items-center gap-1.5 rounded-full border border-[var(--border-default)]',
                'bg-[var(--bg-surface)] py-1.5 pr-3 pl-2.5 text-xs font-medium',
                'text-[var(--text-secondary)] shadow-[var(--shadow-md)]',
                'transition-colors hover:text-[var(--text-primary)]',
              )}
            >
              <ArrowDown className="size-3.5" aria-hidden="true" />
              Latest
            </button>
          ) : null}

          {/* Composer — no surface slab behind it. The input itself carries the
              elevation, so the eye reads one control rather than a control
              sitting inside a bar. */}
          <div className="shrink-0 px-4 pb-4 sm:px-6">
            <div className="mx-auto max-w-3xl">
              {/* Attachments sit above the field, not inside it: they persist
                  across turns, so burying them in a control that clears on
                  send would misrepresent what the thread is grounded in. */}
              {/*
               * Next-step suggestions, offered only once the thread can act on
               * them. Static prompts would still be sitting there after the
               * run had finished, telling someone to do what they just did.
               */}
              {followUps.length > 0 && !sending ? (
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  {followUps.map((f) => (
                    <button
                      key={f}
                      onClick={() => {
                        setDraft(f)
                        composerRef.current?.focus()
                      }}
                      className={cn(
                        'cursor-pointer rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)]',
                        'px-2.5 py-1.5 text-[12px] text-[var(--text-secondary)] shadow-[var(--shadow-sm)]',
                        'transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
                      )}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              ) : null}

              <AttachmentChips
                attachments={attachments}
                onRemove={(aid) => setAttachments((list) => list.filter((a) => a.id !== aid))}
              />
              <div
                className={cn(
                  'relative rounded-xl border bg-[var(--bg-surface)] transition-[border-color,box-shadow] duration-100',
                  focused
                    ? 'border-[var(--accent)] shadow-[var(--shadow-md)]'
                    : 'border-[var(--border-default)] shadow-[var(--shadow-sm)]',
                )}
              >
                <label htmlFor="composer" className="sr-only">
                  Message the assistant
                </label>
                <textarea
                  ref={composerRef}
                  id="composer"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onFocus={() => setFocused(true)}
                  onBlur={() => setFocused(false)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      void send()
                    }
                    // Escape clears a draft rather than leaving it stranded.
                    if (e.key === 'Escape' && draft) {
                      e.preventDefault()
                      setDraft('')
                    }
                  }}
                  rows={1}
                  disabled={sending}
                  placeholder="Describe what you want to change, or ask what something does…"
                  // pb-10 reserves the row the Send button occupies, so text
                  // never slides underneath it as the field grows.
                  className={cn(
                    'block max-h-40 w-full resize-none bg-transparent',
                    // pb-11 clears the control row, which now holds the attach
                    // button as well as Send.
                    'px-3.5 pt-3 pb-11 text-sm leading-relaxed outline-none',
                    'placeholder:text-[var(--text-tertiary)] disabled:opacity-60',
                  )}
                />

                {/* Controls sit inside the field, on its own surface */}
                <div className="absolute inset-x-2 bottom-2 flex items-center justify-between gap-2">
                  <AttachMenu
                    attachments={attachments}
                    onAdd={(a) => setAttachments((list) => [...list, a])}
                    disabled={sending}
                  />
                  {/* Only shown while composing. An always-on hint under the
                      placeholder repeats what the page header already says and
                      makes an empty field look busy. */}
                  <span className="truncate text-[11px] text-[var(--text-tertiary)]">
                    {sending ? (
                      'Retrieving grounding…'
                    ) : draft.trim() ? (
                      <>
                        <kbd className="font-mono">Enter</kbd> to send ·{' '}
                        <kbd className="font-mono">Esc</kbd> to clear
                      </>
                    ) : null}
                  </span>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => void send()}
                    disabled={!draft.trim()}
                    loading={sending}
                    className="shrink-0"
                  >
                    Send
                    <CornerDownLeft className="size-3.5" aria-hidden="true" />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/*
         * The test cases this thread produced, once there are any.
         *
         * Withheld until then: an empty panel would take a third of the width
         * to say nothing, and while the conversation is the whole job it
         * should have the whole screen. It appears when there is something to
         * show — which is also the moment it becomes useful.
         */}
        {/*
         * Always mounted, animated between 0 and 340px.
         *
         * Unmounting cannot transition — the element has to exist on both
         * sides of the change for width to interpolate. `overflow-hidden`
         * clips the contents while it is closing, and `aria-hidden` plus
         * `inert` keep a zero-width panel out of the accessibility tree and
         * off the tab order, so a screen reader is never handed a table
         * nobody can see.
         */}
        <aside
          className={cn(
            // The canvas, not a surface: the rail draws its own card on top.
            'hidden min-h-0 shrink-0 overflow-hidden bg-[var(--bg-base)] lg:block',
            'transition-[width] duration-180 ease-[cubic-bezier(0.16,1,0.3,1)]',
            /*
             * A share of the content area rather than a fixed 340px. At 1600px
             * the fixed width left the transcript twice the panel's size and
             * the two read as a page with something bolted to the side. The
             * min/max keep it sane at the extremes: below ~1100px an even split
             * would squeeze the table's three columns, and on an ultrawide a
             * true half would be far more than the rows can use.
             */
            hasCases ? 'w-[42%] max-w-[560px] min-w-[340px]' : 'w-0',
          )}
          aria-label="Test cases for this requirement"
          aria-hidden={!hasCases}
          inert={!hasCases}
        >
          {/*
           * The inner width is pinned to the panel's own minimum so the table
           * does not reflow while the panel animates open — without it every
           * column re-measures on each frame and the rows visibly shuffle.
           * Once open it grows to fill, which is what `min-w-full` buys: the
           * animation reflows nothing, the settled state uses the full width.
           */}
          <div className="h-full w-[340px] min-w-full">
            {/*
             * Contents render only while open. `inert` already takes them off
             * the tab order, but a 316px link inside a 0px panel still reports
             * itself as visible to anything checking geometry — clipping is a
             * paint concern, not an existence one. Not rendering is the only
             * answer that is true from every angle.
             */}
            {hasCases ? (
              <WorkflowRail
                requirementId={id}
                proposed={proposedInThread}
                acceptedIds={acceptedIds}
                proposedStatusById={runStatusById}
              />
            ) : null}
          </div>
        </aside>
      </div>
    </div>
  )
}

/**
 * Shown before the first turn. A blank transcript gives a non-technical user
 * nothing to act on, and the prompts double as a statement of what this
 * assistant is actually able to answer.
 */
/**
 * Four, not three — they lay out as two even rows, and a trailing gap in a
 * two-column grid reads as a missing card.
 *
 * Each is a question the graph can actually answer from extracted
 * configuration. A starter that returns "I don't have that" teaches people the
 * assistant is unreliable at the exact moment they are deciding whether to
 * trust it.
 */
const STARTERS = [
  'What does this change touch in our current configuration?',
  'Which approval chains depend on the object I want to change?',
  'What would break if we changed this, and what has no test coverage?',
  'How is leave entitlement calculated, and what drives the amount?',
]

/**
 * The name to greet someone by.
 *
 * First name only: "Hi Sathish Kumar" reads like a form letter, and the whole
 * point of a greeting is that it does not. Falls back to a plain "Hi" when
 * there is no name rather than greeting an empty string — "Hi , how can I
 * help" is worse than no name at all.
 */
function firstName(full: string): string {
  return full.trim().split(/\s+/)[0] ?? ''
}

function EmptyThread({ onPick }: { onPick: (q: string) => void }) {
  const greeting = firstName(CURRENT_USER.name)

  return (
    <div className="pt-2 pb-10 text-center">
      <span className="mx-auto flex size-10 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--text-tertiary)]">
        <Sparkles className="size-5" aria-hidden="true" />
      </span>
      <h2 className="mt-3 text-lg font-semibold text-[var(--text-primary)]">
        {greeting ? `Hi ${greeting}, how can I help?` : 'How can I help?'}
      </h2>
      <p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-[var(--text-secondary)]">
        Describe a change in business language. Every answer is grounded in your connected
        systems and cites the configuration objects it relied on. Nothing here changes a
        production system.
      </p>
      {/*
       * Starters sit above the composer rather than below it. Below puts them
       * between the box and the bottom of the window, where they compete with
       * the send action and shift the composer's position; above, they read as
       * part of the empty state and disappear cleanly once the thread starts.
       */}
      <ul className="mx-auto mt-5 grid max-w-2xl gap-2 sm:grid-cols-2">
        {STARTERS.map((q) => (
          <li key={q}>
            <button
              onClick={() => onPick(q)}
              className={cn(
                'h-full w-full cursor-pointer rounded-lg border border-[var(--border-subtle)]',
                'bg-[var(--bg-surface)] px-3 py-2.5 text-left text-[13px] text-[var(--text-secondary)]',
                'transition-colors duration-100 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]',
              )}
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function MessageBubble({
  message,
  acceptedCases,
  onAcceptCases,
  accepting,
  streaming = false,
  onStreamAdvance,
  onStreamDone,
}: {
  message: ChatMessage
  acceptedCases: boolean
  onAcceptCases: () => void
  accepting: boolean
  streaming?: boolean
  onStreamAdvance?: () => void
  onStreamDone?: () => void
}) {
  const isUser = message.role === 'user'
  const [sourcesOpen, setSourcesOpen] = useState(false)

  if (isUser) {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[85%] rounded-lg rounded-br-sm border border-[var(--accent-border)] bg-[var(--accent-subtle)] px-3.5 py-2.5">
          {/*
           * No timestamp under your own message. You just typed it — "just
           * now" tells you nothing you did not watch happen, and it puts a
           * line of chrome between every question and its answer.
           *
           * The time is kept on the element itself, so it is still available
           * to a screen reader and to anything reading the DOM.
           */}
          <p
            className="text-sm leading-relaxed whitespace-pre-wrap text-[var(--text-primary)]"
            title={relativeTime(message.at)}
          >
            {message.content}
          </p>
        </div>
        <div
          className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--bg-surface-3)] text-[10px] font-semibold text-[var(--text-secondary)]"
          aria-hidden="true"
        >
          {CURRENT_USER.initials}
        </div>
      </div>
    )
  }

  return (
    <div className="group flex gap-3">
      <div
        className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-white"
        aria-hidden="true"
      >
        <Sparkles className="size-3.5" />
      </div>
      <div className="min-w-0 flex-1 space-y-2.5">
        {/*
         * Tool calls first, then the crawl they produced, then the answer.
         * That is the order the work happened in, and reading it in that order
         * is how a reviewer follows what the assistant actually did.
         */}
        {message.toolCalls?.length ? <ToolCallSummary calls={message.toolCalls} /> : null}
        {message.crawl ? <CrawlCard crawl={message.crawl} /> : null}
        {message.runSummary ? <RunCompletedPill summary={message.runSummary} /> : null}

        {/* Answer and its sources share one card. They were two stacked boxes,
            which read as separate claims rather than a claim and its evidence. */}
        <div className="overflow-hidden rounded-xl rounded-tl-sm border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
          <div className="px-3.5 py-2.5">
            {/*
             * Streaming renders the words plainly; the settled message renders
             * through Markdownish. The swap happens on the last word, so the
             * emphasis the answer was written with survives the reveal rather
             * than leaving `**` visible in the transcript.
             */}
            {streaming ? (
              <StreamingText
                text={message.content}
                onAdvance={onStreamAdvance}
                onDone={onStreamDone}
              />
            ) : (
              <Markdownish text={message.content} />
            )}
          </div>

          {/*
           * Sources wait for the answer to finish. They are what the claim
           * rests on, so showing them beside a half-written sentence would
           * offer evidence for something not yet stated.
           */}
          {message.citations?.length && !streaming ? (
            <div
              className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)]"
              style={{ animation: 'fade-in-up 140ms ease-out both' }}
            >
              {/*
               * Collapsed by default. The count is the part that matters at a
               * glance — "grounded in 8 sources" is the trust signal — while
               * eight rows of provenance between every answer and the next
               * pushes the conversation off screen. Expanded is for checking
               * a specific claim, which is a deliberate act.
               */}
              <button
                type="button"
                onClick={() => setSourcesOpen((open) => !open)}
                aria-expanded={sourcesOpen}
                className="flex w-full items-center gap-1.5 px-3.5 py-2.5 text-left transition-colors hover:bg-[var(--bg-subtle)]"
              >
                <BookOpen className="size-3 text-[var(--text-tertiary)]" aria-hidden="true" />
                <SectionLabel>
                  Grounded in {message.citations.length} source
                  {message.citations.length > 1 ? 's' : ''}
                </SectionLabel>
                <ChevronDown
                  className={cn(
                    'ml-auto size-3.5 text-[var(--text-tertiary)] transition-transform duration-150',
                    sourcesOpen && 'rotate-180',
                  )}
                  aria-hidden="true"
                />
              </button>
              {sourcesOpen ? (
                /*
                 * The grid/minmax(0,1fr) pair is what lets the row animate
                 * from zero to the content's own height; `overflow-hidden` on
                 * the inner element is what actually clips during the tween.
                 */
                <div
                  className="grid px-3.5 pb-2.5"
                  style={{ animation: 'expand-rows 130ms cubic-bezier(0.16, 1, 0.3, 1) both' }}
                >
                  <ul className="min-h-0 space-y-1.5 overflow-hidden">
                    {message.citations.map((c) => (
                      <li key={c.nodeId} className="flex flex-wrap items-center gap-1.5">
                        <Link
                          to="/sources?view=graph"
                          className="text-xs font-medium text-[var(--accent-text)] underline-offset-2 hover:underline"
                        >
                          {c.label}
                        </Link>
                        <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                          {c.provenance}
                        </span>
                        <ConfidenceBadge confidence={c.confidence} />
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {message.dissent && !streaming ? <DissentCard dissent={message.dissent} /> : null}

        {/* The cases this turn produced, in the transcript as well as the
            panel — you read them here, you act on them there. Held back until
            the answer has finished: Add is a decision, and offering it under a
            sentence still being written invites a click before the reason for
            it has been read. */}
        {message.generatedCases?.length && !streaming ? (
          <div style={{ animation: 'fade-in-up 140ms ease-out both' }}>
            <GeneratedCasesCard
              cases={message.generatedCases}
              accepted={acceptedCases}
              busy={accepting}
              onAccept={onAcceptCases}
            />
          </div>
        ) : null}

        {/*
         * No model / token / cost line under each turn.
         *
         * It is instrumentation, and a conversation of five answers became
         * five rows of telemetry between the things someone is actually
         * reading. Nothing is lost: every figure is still written to the cost
         * ledger and to the audit chain, and the Cost & Efficiency page
         * aggregates them properly — which is where anyone reconciling spend
         * or asking "which model produced this" actually goes.
         */}
      </div>
    </div>
  )
}

/** The assistant's formal disagreement is a first-class, visually distinct record. */
/**
 * "Test run completed" — the run as an event in the transcript.
 *
 * A bordered pill rather than a sentence: a run is something that happened at a
 * point in time, and giving it the same shape as the assistant's prose would
 * make an event indistinguishable from a claim about one.
 */
function RunCompletedPill({ summary }: { summary: { passed: number; total: number } }) {
  const allPassed = summary.passed === summary.total
  return (
    <div className="flex justify-end">
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-medium',
          allPassed
            ? 'border-[var(--ok-border)] bg-[var(--ok-subtle)] text-[var(--ok)]'
            : 'border-[var(--warn-border)] bg-[var(--warn-subtle)] text-[var(--warn)]',
        )}
      >
        <Check className="size-3.5 shrink-0" aria-hidden="true" />
        Test run completed
        <span className="tabular font-normal opacity-80">
          {summary.passed}/{summary.total} passed
        </span>
      </span>
    </div>
  )
}

function DissentCard({ dissent }: { dissent: NonNullable<ChatMessage['dissent']> }) {
  const blocking = dissent.severity === 'blocking'
  return (
    <div
      className={cn(
        'rounded-xl border p-3',
        blocking
          ? 'border-[var(--danger-border)] bg-[var(--danger-subtle)]'
          : 'border-[var(--warn-border)] bg-[var(--warn-subtle)]',
      )}
    >
      <div className="flex items-start gap-2.5">
        <AlertOctagon
          className={cn(
            'mt-px size-4 shrink-0',
            blocking ? 'text-[var(--danger)]' : 'text-[var(--warn)]',
          )}
          aria-hidden="true"
        />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <p
              className={cn(
                'text-xs font-semibold',
                blocking ? 'text-[var(--danger)]' : 'text-[var(--warn)]',
              )}
            >
              {blocking ? 'Blocking dissent' : 'Advisory dissent'}
            </p>
            {dissent.conflictsWith ? (
              <Badge tone={blocking ? 'danger' : 'warn'}>
                Conflicts with {dissent.conflictsWith}
              </Badge>
            ) : null}
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-secondary)]">
            {dissent.statement}
          </p>
          <p className="mt-2 text-[10px] text-[var(--text-tertiary)]">
            Recorded in the audit chain. A blocking dissent must be resolved or explicitly
            overridden by an accountable approver before this change can proceed.
          </p>
        </div>
      </div>
    </div>
  )
}

/** Renders the small subset of markdown the mock responses use. *//**
 * Assistant output, rendered.
 *
 * `react-markdown` rather than a hand-rolled renderer or Streamdown, for one
 * reason above the others: **security by construction**. Without `rehype-raw`
 * it builds React elements from the parsed AST and never renders raw HTML at
 * all, so there is no sanitiser to misconfigure. Model output is untrusted
 * input, and the strongest position is one where injection has nowhere to
 * land.
 *
 * Streamdown was the obvious alternative and was rejected: it ships
 * `allowedLinkPrefixes: ['*']` and `allowedProtocols: ['*']` by default, and
 * three times the bundle, most of it an HTML parser serving the raw-HTML
 * support we specifically do not want.
 *
 * `remark-gfm` is what supplies tables — CommonMark has none, and comparing
 * configuration objects in a table is the shape these answers reach for.
 */
function Markdownish({ text }: { text: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed text-[var(--text-secondary)]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        /*
         * Block anything that is not plainly safe to follow. A model can emit
         * a link, and `javascript:` or a `data:` payload behind innocuous text
         * is the cheapest attack available here. Images are the exfiltration
         * vector — a remote src turns a rendered answer into a callback to
         * someone else's server — so they resolve to nothing.
         */
        urlTransform={(url) =>
          /^https?:\/\//i.test(url) || url.startsWith('#') ? url : ''
        }
        components={{
          p: ({ children }) => <p>{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-[var(--text-primary)]">{children}</strong>
          ),
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
          h1: ({ children }) => (
            <p className="pt-1 text-sm font-semibold text-[var(--text-primary)]">{children}</p>
          ),
          h2: ({ children }) => (
            <p className="pt-1 text-sm font-semibold text-[var(--text-primary)]">{children}</p>
          ),
          h3: ({ children }) => (
            <p className="pt-1 text-sm font-semibold text-[var(--text-primary)]">{children}</p>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--accent-text)] underline underline-offset-2"
            >
              {children}
            </a>
          ),
          code: ({ children, className }) =>
            // Fenced blocks arrive with a language class; inline code has none.
            // They want different treatment, and react-markdown routes both
            // through this one component.
            className ? (
              <code className="block overflow-x-auto rounded-md bg-[var(--bg-subtle)] p-2.5 font-mono text-xs text-[var(--text-primary)]">
                {children}
              </code>
            ) : (
              <code className="rounded bg-[var(--bg-subtle)] px-1 py-0.5 font-mono text-[0.85em] text-[var(--text-primary)]">
                {children}
              </code>
            ),
          pre: ({ children }) => <pre className="overflow-x-auto">{children}</pre>,
          /*
           * The scroll belongs to the table, not the bubble. A wide table that
           * scrolled its container would drag the whole conversation sideways.
           */
          table: ({ children }) => (
            <div className="-mx-1 overflow-x-auto px-1">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b border-[var(--border)] px-2 py-1.5 text-left font-semibold text-[var(--text-primary)]">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-[var(--border-subtle)] px-2 py-1.5 align-top">
              {children}
            </td>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-[var(--border)] pl-3 text-[var(--text-tertiary)]">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="border-[var(--border-subtle)]" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

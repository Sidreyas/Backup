import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BookOpen,
  ChevronDown,
  CircleHelp,
  ExternalLink,
  LifeBuoy,
  MessageSquare,
  Search,
  Send,
  ShieldCheck,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  IconTile,
  SearchInput,
} from '@/components/ui/primitives'
import { useToast } from '@/components/ui/overlays'
import { cn } from '@/lib/utils'

/** Concept guides — these explain the product's opinions, not its buttons. */
const GUIDES = [
  {
    to: '/evidence',
    title: 'Verified vs asserted evidence',
    blurb:
      'Why an agent saying "it works" is a claim, not proof — and why only deterministic, replayable tests can close a sign-off gate.',
    Icon: ShieldCheck,
  },
  {
    to: '/sources?view=graph',
    title: 'Why links are hypotheses',
    blurb:
      'Cross-artifact links are scored guesses until a human confirms them. Confirming a link teaches the graph and improves later analysis.',
    Icon: BookOpen,
  },
  {
    to: '/impact',
    title: 'Reading an impact analysis',
    blurb:
      'Severity, confidence, coverage gaps and declared blind spots — what each column means before you sign anything.',
    Icon: CircleHelp,
  },
  {
    to: '/policies',
    title: 'How policies block a gate',
    blurb:
      'Policies are evaluated when a change is planned, not discovered at review. A blocking policy cannot be overridden silently.',
    Icon: ShieldCheck,
  },
]

const FAQS = [
  {
    q: 'Why can I not approve this gate?',
    a: 'A gate is blocked when a policy fails or its evidence requirement is unmet. The Approvals screen lists the exact blockers under each gate. The two most common are a payroll-relevant change with an uncovered impacted node (POL-004), and evidence whose flake rate exceeds the 10% ceiling (POL-007).',
  },
  {
    q: 'Can Meridian change my production system?',
    a: 'Not in advisory mode, which is the default. Agents hold read-only access to every connected system. Granting write access is a per-platform decision made by a workspace owner, and the grant itself is recorded in the audit chain.',
  },
  {
    q: 'An impact analysis missed something. What now?',
    a: 'Check the declared blind spots on that analysis first — Meridian states what it could not reason about rather than implying full coverage. If the gap came from an unconfirmed graph link, confirming or rejecting that link in the Graph Explorer improves every future analysis touching the same objects.',
  },
  {
    q: 'Why is there no "hours saved" number?',
    a: 'Because the counterfactual is unobservable. Meridian reports what it can measure — spend, cycle time against your own historical baseline, change failure rate, evidence completeness — and lets you apply your own rate card if you need a cost-avoidance figure.',
  },
  {
    q: 'What does a stale source actually affect?',
    a: 'Any impact analysis relying on it may miss changes made after its last sync. Policy POL-014 flags affected analyses rather than blocking them, and every source shows its staleness threshold on the Knowledge Sources screen.',
  },
  {
    q: 'How do workspaces and projects differ?',
    a: 'A workspace is a governance boundary and carries the compliance regime that its policies and approval gates enforce. A project sits inside one and scopes the working set — which sources are connected and which changes are in flight. A change in one workspace can never satisfy a gate in another.',
  },
]

export function SupportPage() {
  const [query, setQuery] = useState('')
  const [openFaq, setOpenFaq] = useState<number | null>(0)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return FAQS
    return FAQS.filter((f) => f.q.toLowerCase().includes(q) || f.a.toLowerCase().includes(q))
  }, [query])

  return (
    <>
      <PageHeader
        title="Help & Support"
        icon={<LifeBuoy aria-hidden="true" />}
        tone="plain"
      />

      <PageBody className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <div className="min-w-0 space-y-4">
            {/* Concept guides */}
            <Card>
              <CardHeader
                title="Understanding Meridian"
                description="The four ideas the product is built around."
                icon={<BookOpen aria-hidden="true" />}
              />
              <div className="grid gap-3 p-3 sm:grid-cols-2">
                {GUIDES.map((g) => (
                  <Link
                    key={g.title}
                    to={g.to}
                    className="group rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-3.5 transition-colors duration-200 hover:border-[var(--border-default)] hover:bg-[var(--bg-hover)]"
                  >
                    <IconTile className="group-hover:border-[var(--border-strong)]">
                      <g.Icon aria-hidden="true" />
                    </IconTile>
                    <p className="mt-2.5 text-[13px] font-semibold text-[var(--text-primary)]">
                      {g.title}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                      {g.blurb}
                    </p>
                  </Link>
                ))}
              </div>
            </Card>

            {/* FAQ */}
            <Card>
              <CardHeader
                title="Common questions"
                icon={<CircleHelp aria-hidden="true" />}
                actions={
                  <SearchInput
                    className="w-44 sm:w-56"
                    value={query}
                    onChange={setQuery}
                    placeholder="Search help…"
                    label="Search help articles"
                    icon={<Search className="size-3.5" aria-hidden="true" />}
                  />
                }
              />
              {filtered.length === 0 ? (
                <EmptyState
                  icon={<CircleHelp className="size-5" aria-hidden="true" />}
                  title="No answers match that search"
                  description="Try a different term, or send the question to support and a human will pick it up."
                  action={
                    <Button variant="secondary" onClick={() => setQuery('')}>
                      Clear search
                    </Button>
                  }
                />
              ) : (
                <ul className="divide-y divide-[var(--border-subtle)]">
                  {filtered.map((f, i) => {
                    const open = openFaq === i
                    return (
                      <li key={f.q}>
                        <button
                          onClick={() => setOpenFaq(open ? null : i)}
                          aria-expanded={open}
                          className="flex w-full cursor-pointer items-center justify-between gap-3 p-4 text-left transition-colors duration-200 hover:bg-[var(--bg-hover)]"
                        >
                          <span className="text-[13px] font-medium text-[var(--text-primary)]">
                            {f.q}
                          </span>
                          <ChevronDown
                            className={cn(
                              'size-4 shrink-0 text-[var(--text-tertiary)] transition-transform duration-200',
                              open && 'rotate-180',
                            )}
                            aria-hidden="true"
                          />
                        </button>
                        {open ? (
                          <p className="px-4 pb-4 text-[13px] leading-relaxed text-[var(--text-secondary)]">
                            {f.a}
                          </p>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              )}
            </Card>
          </div>

          {/* Contact rail */}
          <aside className="space-y-4">
            <ContactCard />

            <Card>
              <CardHeader title="Status" icon={<LifeBuoy aria-hidden="true" />} />
              <ul className="divide-y divide-[var(--border-subtle)]">
                {[
                  { label: 'Ingestion pipeline', tone: 'ok' as const, value: 'Operational' },
                  { label: 'Agent runners', tone: 'ok' as const, value: 'Operational' },
                  { label: 'Dynamics 365 connector', tone: 'danger' as const, value: 'Degraded' },
                ].map((s) => (
                  <li key={s.label} className="flex items-center justify-between gap-3 p-3">
                    <span className="text-xs text-[var(--text-secondary)]">{s.label}</span>
                    <Badge tone={s.tone}>{s.value}</Badge>
                  </li>
                ))}
              </ul>
              <div className="border-t border-[var(--border-subtle)] p-3">
                <Button
                  variant="secondary"
                  size="sm"
                  className="w-full justify-center"
                  icon={<ExternalLink className="size-3.5" aria-hidden="true" />}
                >
                  Full status page
                </Button>
              </div>
            </Card>
          </aside>
        </div>
      </PageBody>
    </>
  )
}

function ContactCard() {
  const { push } = useToast()
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [touched, setTouched] = useState(false)

  const error =
    touched && body.trim().length < 15
      ? 'Describe the problem in at least 15 characters so support can act on it.'
      : null

  function submit() {
    setTouched(true)
    if (body.trim().length < 15) return
    setSubject('')
    setBody('')
    setTouched(false)
    push({
      tone: 'ok',
      title: 'Message sent',
      description: 'Support replies within one business day.',
    })
  }

  return (
    <Card>
      <CardHeader
        title="Contact support"
        description="Your workspace and project are attached automatically."
        icon={<MessageSquare aria-hidden="true" />}
      />
      <div className="space-y-3 p-4">
        <div>
          <label
            htmlFor="support-subject"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            Subject
          </label>
          <input
            id="support-subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Short summary"
            className="h-9 w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-[13px] outline-none transition-colors duration-200 focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10"
          />
        </div>
        <div>
          <label
            htmlFor="support-body"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            What is happening?{' '}
            <span className="text-[var(--danger)]" aria-hidden="true">
              *
            </span>
          </label>
          <textarea
            id="support-body"
            rows={4}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onBlur={() => setTouched(true)}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? 'support-error' : undefined}
            placeholder="Include the requirement or evidence reference if you have one."
            className="w-full resize-y rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-[13px] outline-none transition-colors duration-200 focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10"
          />
          {error ? (
            <p id="support-error" role="alert" className="mt-1.5 text-xs text-[var(--danger)]">
              {error}
            </p>
          ) : null}
        </div>
        <Button
          variant="primary"
          size="sm"
          className="w-full justify-center"
          icon={<Send className="size-3.5" aria-hidden="true" />}
          onClick={submit}
        >
          Send message
        </Button>
      </div>
    </Card>
  )
}

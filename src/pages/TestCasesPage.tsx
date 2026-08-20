import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FlaskConical,
  Layers,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Search,
  Sparkles,
  Trash2,
  X,
  XCircle,
} from 'lucide-react'
import { PageBody, PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  SearchInput,
  SectionLabel,
  Segmented,
  Skeleton,
} from '@/components/ui/primitives'
import { Modal, Tabs, useToast } from '@/components/ui/overlays'
import {
  NODE_KIND_META,
  OriginBadge,
  PriorityBadge,
  ReviewStateBadge,
  TEST_LEVEL_LABEL,
  TEST_TYPE_LABEL,
} from '@/components/domain/status'
import { StlcRail } from '@/components/domain/StlcRail'
import { api } from '@/lib/api'
import { useAsyncList } from '@/lib/useAsync'
import { useStlc } from '@/lib/useStlc'
import { cn, relativeTime } from '@/lib/utils'
import { diffFields } from '@/lib/provenance'
import { JudgeRubricPanel, RubricScorePill } from '@/components/domain/JudgeRubricPanel'
import { SuiteManager } from '@/components/domain/SuiteManager'
import { ReasonDialog } from '@/components/domain/ReasonDialog'
import type { FieldChange, GraphNode, TestCase, TestStep } from '@/lib/types'

type Filter = 'all' | 'in_review' | 'approved' | 'manual'

export function TestCasesPage() {
  const { cases: fetched, phases, subject, loading } = useStlc()
  const { items: graph } = useAsyncList(() => api.getGraph().then((g) => g.nodes), [])

  /** Local copy so edits and approvals persist while on this page. */
  const [cases, setCases] = useState<TestCase[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<TestCase | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [discardOpen, setDiscardOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null)
  /* Part 11 reason-for-change capture, held between "Save" and the write. */
  const [reasonOpen, setReasonOpen] = useState(false)
  const [pendingChanges, setPendingChanges] = useState<FieldChange[]>([])
  const [saving, setSaving] = useState(false)
  const [suitesOpen, setSuitesOpen] = useState(false)
  /* Bumped after a suite is created or deleted, to refetch the list. */
  const [suiteNonce, setSuiteNonce] = useState(0)
  const { items: suites } = useAsyncList(() => api.getTestSuites(), [suiteNonce])
  const { push } = useToast()

  useEffect(() => {
    if (fetched.length > 0) setCases(fetched)
  }, [fetched])

  // Select the first case once data lands, so the detail pane is never blank.
  useEffect(() => {
    if (!selectedId && cases.length > 0) setSelectedId(cases[0].id)
  }, [cases, selectedId])

  const nodeById = useMemo(() => new Map(graph.map((n: GraphNode) => [n.id, n])), [graph])
  const selected = useMemo(
    () => cases.find((c) => c.id === selectedId) ?? null,
    [cases, selectedId],
  )

  const dirty = useMemo(() => {
    if (!editing || !draft || !selected) return false
    return JSON.stringify(draft) !== JSON.stringify(selected)
  }, [editing, draft, selected])

  const counts = useMemo(
    () => ({
      all: cases.length,
      in_review: cases.filter((c) => c.state === 'in_review').length,
      approved: cases.filter((c) => c.state === 'approved').length,
      manual: cases.filter((c) => !c.automatable).length,
    }),
    [cases],
  )

  const filtered = useMemo(() => {
    let list = cases
    if (filter === 'in_review') list = list.filter((c) => c.state === 'in_review')
    if (filter === 'approved') list = list.filter((c) => c.state === 'approved')
    if (filter === 'manual') list = list.filter((c) => !c.automatable)
    const q = query.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (c) =>
          c.title.toLowerCase().includes(q) ||
          c.ref.toLowerCase().includes(q) ||
          c.tags.some((t) => t.toLowerCase().includes(q)),
      )
    }
    return list
  }, [cases, filter, query])

  /** Guard navigation away from unsaved edits rather than silently dropping them. */
  const guard = useCallback(
    (action: () => void) => {
      if (dirty) {
        setPendingAction(() => action)
        setDiscardOpen(true)
      } else {
        action()
      }
    },
    [dirty],
  )

  function startEdit() {
    if (!selected) return
    setDraft(structuredClone(selected))
    setEditing(true)
  }

  function cancelEdit() {
    guard(() => {
      setEditing(false)
      setDraft(null)
    })
  }

  /**
   * Editing a test case is a governed change, so the reason is captured before
   * it is written rather than inferred afterwards. The dialog shows the diff
   * first: a reviewer who can see that an expected result was weakened writes a
   * different reason than one told only that "a case was edited".
   */
  function save() {
    if (!draft || !selected) return
    const changes = diffFields(selected, draft, [
      { field: 'title', label: 'Title' },
      { field: 'expectedResult', label: 'Expected result' },
      { field: 'priority', label: 'Priority' },
      { field: 'level', label: 'Level' },
      { field: 'type', label: 'Type' },
      { field: 'automatable', label: 'Automatable' },
      { field: 'testData', label: 'Test data' },
    ])
    /* Nothing changed — no record to write and nothing to justify. */
    if (changes.length === 0) {
      setEditing(false)
      setDraft(null)
      return
    }
    setPendingChanges(changes)
    setReasonOpen(true)
  }

  async function commitSave(reason: string) {
    if (!draft) return
    setSaving(true)
    try {
      const saved = await api.saveTestCase(draft, reason)
      setCases((list) => list.map((c) => (c.id === saved.id ? saved : c)))
      setReasonOpen(false)
      setPendingChanges([])
      setEditing(false)
      setDraft(null)
      push({
        tone: 'ok',
        title: 'Test case saved',
        description:
          saved.origin === 'ai_edited_by_human'
            ? 'Marked as AI + human edits. Before/after values and your reason are in the audit chain.'
            : 'Before/after values and your reason are in the audit chain.',
      })
    } finally {
      setSaving(false)
    }
  }

  async function setState(id: string, state: TestCase['state']) {
    const next = await api.setTestCaseState(id, state)
    if (!next) return
    setCases((list) => list.map((c) => (c.id === id ? next : c)))
    push({
      tone: state === 'approved' ? 'ok' : 'info',
      title: state === 'approved' ? 'Case approved' : 'Case rejected',
      description:
        state === 'approved'
          ? 'It can now be selected for execution.'
          : 'It will not be offered for execution.',
    })
  }

  if (loading && cases.length === 0) {
    return (
      <>
        <PageHeader
          title="Test cases"
          icon={<FlaskConical aria-hidden="true" />}
          tone="accent"
        />
        <PageBody className="space-y-4">
          <Skeleton className="h-[76px] w-full rounded-xl" />
          <Skeleton className="h-[560px] w-full rounded-xl" />
        </PageBody>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Test cases"
        icon={<FlaskConical aria-hidden="true" />}
        tone="accent"
        subject={subject?.title}
        // The stepper is wayfinding for a four-screen sequence, so it stays
        // pinned with the title rather than scrolling away with the content.
        below={<StlcRail phases={phases} subject={subject} />}
        actions={
          <>
            <Button
              variant="secondary"
              icon={<Layers className="size-4" aria-hidden="true" />}
              onClick={() => setSuitesOpen(true)}
            >
              Suites
              {suites.length > 0 ? (
                <span className="numeral ml-1 text-[var(--text-tertiary)]">{suites.length}</span>
              ) : null}
            </Button>
            <Button variant="secondary" icon={<Sparkles className="size-4" aria-hidden="true" />}>
              Generate more
            </Button>
            <Link to="/test-runs">
              <Button
                variant="primary"
                icon={<ChevronRight className="size-4" aria-hidden="true" />}
                disabled={counts.approved === 0}
              >
                Run tests
              </Button>
            </Link>
          </>
        }
      />

      <PageBody fill>
        {/*
         * Master-detail: the list stays put while a case is reviewed, so a
         * reviewer never loses their position in a long queue.
         *
         * From `lg` each column scrolls inside itself so the page never grows
         * taller than the screen. That is what keeps the app shell fixed —
         * previously the tall detail column pushed the whole document down and
         * took the sticky header with it.
         *
         * Every level from here down to the scrolling <ul> needs min-h-0.
         * Grid and flex items default to `min-height: auto`, which means they
         * refuse to shrink below their content — so an `overflow-y-auto` deep
         * inside never clips, and the rows spill out and grow the document
         * instead. One missing min-h-0 anywhere in the chain breaks it.
         */}
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-rows-1 lg:grid-cols-[minmax(0,380px)_1fr]">
          <Card className="flex min-h-0 flex-col overflow-hidden">
            <div className="space-y-3 border-b border-[var(--border-subtle)] p-3">
              <SearchInput
                value={query}
                onChange={setQuery}
                placeholder="Search cases, refs and tags…"
                label="Search test cases"
                icon={<Search className="size-3.5" aria-hidden="true" />}
              />
              <Tabs
                className="border-b-0"
                value={filter}
                onChange={(v) => setFilter(v as Filter)}
                items={[
                  { id: 'all', label: 'All', count: counts.all },
                  { id: 'in_review', label: 'In review', count: counts.in_review },
                  { id: 'approved', label: 'Approved', count: counts.approved },
                ]}
              />
            </div>

            {filtered.length === 0 ? (
              <EmptyState
                icon={<FlaskConical className="size-5" aria-hidden="true" />}
                title="No cases match"
                description="Try a different search term or filter."
                action={
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setQuery('')
                      setFilter('all')
                    }}
                  >
                    Clear filters
                  </Button>
                }
              />
            ) : (
              // Fills whatever height the card has rather than a fixed 620px:
              // the hard cap left a tall blank area below the last row on a
              // large screen and forced its own scrollbar on a short one.
              <ul className="min-h-0 flex-1 divide-y divide-[var(--border-subtle)] overflow-y-auto">
                {filtered.map((c) => {
                  const active = c.id === selectedId
                  return (
                    <li key={c.id}>
                      <button
                        onClick={() =>
                          guard(() => {
                            setSelectedId(c.id)
                            setEditing(false)
                            setDraft(null)
                          })
                        }
                        aria-current={active ? 'true' : undefined}
                        className={cn(
                          'w-full cursor-pointer p-3.5 text-left transition-colors duration-200',
                          active ? 'bg-[var(--accent-subtle)]' : 'hover:bg-[var(--bg-hover)]',
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                            {c.ref}
                          </span>
                          <PriorityBadge priority={c.priority} />
                          {!c.automatable ? <Badge tone="asserted">Manual</Badge> : null}
                        </div>
                        <p className="mt-1 line-clamp-2 text-[13px] leading-snug font-medium text-[var(--text-primary)]">
                          {c.title}
                        </p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <ReviewStateBadge state={c.state} />
                          <span className="text-[11px] text-[var(--text-tertiary)]">
                            {TEST_LEVEL_LABEL[c.level]}
                          </span>
                          {/* The judge score in the row, so a weakly-scored
                              case is visible without opening all eight. */}
                          {c.rubric ? (
                            <span className="ml-auto">
                              <RubricScorePill rubric={c.rubric} />
                            </span>
                          ) : null}
                        </div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>

          {/* Scrolls inside the pinned pane. Without this the detail column —
              the taller of the two — would push the page past the viewport and
              take the fixed shell with it. */}
          <div className="min-h-0 min-w-0 overflow-y-auto lg:pr-1">
            {selected ? (
              editing && draft ? (
                <CaseEditor
                  draft={draft}
                  onChange={setDraft}
                  onCancel={cancelEdit}
                  onSave={save}
                  dirty={dirty}
                />
              ) : (
                <CaseDetail
                  testCase={selected}
                  nodeById={nodeById}
                  onEdit={startEdit}
                  onApprove={() => setState(selected.id, 'approved')}
                  onReject={() => setState(selected.id, 'rejected')}
                />
              )
            ) : (
              <Card>
                <EmptyState
                  icon={<FlaskConical className="size-5" aria-hidden="true" />}
                  title="Select a case"
                  description="Choose a test case from the list to review its steps and expected result."
                />
              </Card>
            )}
          </div>
        </div>
      </PageBody>

      <Modal
        open={discardOpen}
        onClose={() => setDiscardOpen(false)}
        title="Discard unsaved changes?"
        description="This case has edits that have not been saved. Leaving now loses them."
        footer={
          <>
            <Button variant="ghost" onClick={() => setDiscardOpen(false)}>
              Keep editing
            </Button>
            <Button
              variant="danger"
              icon={<Trash2 className="size-4" aria-hidden="true" />}
              onClick={() => {
                setDiscardOpen(false)
                setEditing(false)
                setDraft(null)
                pendingAction?.()
                setPendingAction(null)
              }}
            >
              Discard changes
            </Button>
          </>
        }
      >
        <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">
          Saving instead records the edit against your name and marks the case as human-edited,
          which is what lets a reviewer distinguish your judgement from the agent's proposal.
        </p>
      </Modal>

      <ReasonDialog
        open={reasonOpen}
        onClose={() => setReasonOpen(false)}
        onConfirm={(reason) => void commitSave(reason)}
        title="Record this edit"
        description="Test cases are governed records. The before and after values below are written to the audit chain with your reason."
        changes={pendingChanges}
        busy={saving}
      />

      <SuiteManager
        open={suitesOpen}
        onClose={() => setSuitesOpen(false)}
        cases={cases}
        suites={suites}
        onChanged={() => setSuiteNonce((n) => n + 1)}
      />
    </>
  )
}

/* ------------------------------------------------------------------ detail */

function CaseDetail({
  testCase: c,
  nodeById,
  onEdit,
  onApprove,
  onReject,
}: {
  testCase: TestCase
  nodeById: Map<string, GraphNode>
  onEdit: () => void
  onApprove: () => void
  onReject: () => void
}) {
  return (
    <Card>
      <CardHeader
        title={c.title}
        description={`${c.ref} · ${TEST_LEVEL_LABEL[c.level]} · ${TEST_TYPE_LABEL[c.type]}`}
        icon={<FlaskConical aria-hidden="true" />}
        actions={
          <Button
            variant="secondary"
            size="sm"
            icon={<Pencil className="size-3.5" aria-hidden="true" />}
            onClick={onEdit}
          >
            Edit
          </Button>
        }
      />

      <div className="space-y-5 p-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <ReviewStateBadge state={c.state} />
          <OriginBadge origin={c.origin} />
          <PriorityBadge priority={c.priority} />
          {c.automatable ? (
            <Badge tone="verified">Automatable</Badge>
          ) : (
            <Badge tone="asserted">Needs a human or agent</Badge>
          )}
        </div>

        {/* Rationale first: a reviewer needs to know why a case exists before
            deciding whether its steps are the right ones. */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3.5">
          <SectionLabel>Why this case was proposed</SectionLabel>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--text-secondary)]">
            {c.rationale}
          </p>
        </div>

        {/*
         * How well it was judged to have been done, directly under why it was
         * written. Opened by default when the verdict is not a clean accept:
         * a case the judge wants revised is one whose reasons a reviewer
         * should not have to go looking for.
         */}
        {c.rubric ? (
          <JudgeRubricPanel rubric={c.rubric} defaultOpen={c.rubric.verdict !== 'accept'} />
        ) : null}

        {c.preconditions.length > 0 ? (
          <div>
            <SectionLabel>Preconditions</SectionLabel>
            <ul className="mt-2 space-y-1.5">
              {c.preconditions.map((p) => (
                <li
                  key={p}
                  className="flex items-start gap-2 text-[13px] text-[var(--text-secondary)]"
                >
                  <span
                    className="mt-[7px] size-1.5 shrink-0 rounded-full bg-[var(--neutral-solid)]"
                    aria-hidden="true"
                  />
                  {p}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div>
          <SectionLabel>Steps</SectionLabel>
          <ol className="mt-2 space-y-2">
            {c.steps.map((s) => (
              <li
                key={s.id}
                className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3"
              >
                <div className="flex items-start gap-2.5">
                  <span className="numeral flex size-5 shrink-0 items-center justify-center rounded-full border border-[var(--border-default)] bg-[var(--bg-surface)] text-[10px] font-semibold text-[var(--text-secondary)]">
                    {s.index}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] leading-snug text-[var(--text-primary)]">
                      {s.action}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-[var(--text-tertiary)]">
                      <span className="font-medium">Expected — </span>
                      {s.expected}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="rounded-xl border border-[var(--ok-border)] bg-[var(--ok-subtle)] p-3.5">
          <SectionLabel>Expected result</SectionLabel>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--text-primary)]">
            {c.expectedResult}
          </p>
        </div>

        <dl className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
          <div>
            <dt className="text-[10px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Test data
            </dt>
            <dd className="mt-0.5 text-[13px] text-[var(--text-primary)]">{c.testData}</dd>
          </div>
          <div>
            <dt className="text-[10px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Estimated duration
            </dt>
            <dd className="tabular mt-0.5 text-[13px] text-[var(--text-primary)]">
              {c.estimatedDurationSeconds}s
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Author
            </dt>
            <dd className="mt-0.5 text-[13px] text-[var(--text-primary)]">{c.author}</dd>
          </div>
          <div>
            <dt className="text-[10px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Last updated
            </dt>
            <dd className="mt-0.5 text-[13px] text-[var(--text-primary)]">
              {relativeTime(c.updatedAt)}
            </dd>
          </div>
        </dl>

        <div>
          <SectionLabel>Graph nodes this case exercises</SectionLabel>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {c.coversNodeIds.map((id) => {
              const node = nodeById.get(id)
              const meta = node ? NODE_KIND_META[node.kind] : null
              return (
                <Badge
                  key={id}
                  tone="neutral"
                  icon={meta ? <meta.Icon className="size-3" aria-hidden="true" /> : undefined}
                >
                  {node?.label ?? id}
                </Badge>
              )
            })}
          </div>
        </div>

        {c.tags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {c.tags.map((t) => (
              <span
                key={t}
                className="rounded-md bg-[var(--bg-surface-2)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-tertiary)]"
              >
                {t}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {c.state !== 'approved' ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <p className="text-xs text-[var(--text-tertiary)]">
            An unreviewed case cannot be selected for execution.
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<XCircle className="size-3.5" aria-hidden="true" />}
              onClick={onReject}
            >
              Reject
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<CheckCircle2 className="size-3.5" aria-hidden="true" />}
              onClick={onApprove}
            >
              Approve case
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  )
}

/* ------------------------------------------------------------------ editor */

const FIELD =
  'w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-[13px] text-[var(--text-primary)] outline-none transition-colors duration-200 focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10'

function CaseEditor({
  draft,
  onChange,
  onCancel,
  onSave,
  dirty,
}: {
  draft: TestCase
  onChange: (c: TestCase) => void
  onCancel: () => void
  onSave: () => void
  dirty: boolean
}) {
  const set = <K extends keyof TestCase>(key: K, value: TestCase[K]) =>
    onChange({ ...draft, [key]: value })

  function setStep(id: string, patch: Partial<TestStep>) {
    set(
      'steps',
      draft.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    )
  }

  function addStep() {
    const next: TestStep = {
      id: `s-new-${draft.steps.length + 1}-${Math.random().toString(36).slice(2, 6)}`,
      index: draft.steps.length + 1,
      action: '',
      expected: '',
    }
    set('steps', [...draft.steps, next])
  }

  function removeStep(id: string) {
    set(
      'steps',
      draft.steps.filter((s) => s.id !== id).map((s, i) => ({ ...s, index: i + 1 })),
    )
  }

  const titleError = draft.title.trim().length < 10
  const expectedError = draft.expectedResult.trim().length < 10
  const stepErrors = draft.steps.some((s) => !s.action.trim() || !s.expected.trim())
  const invalid = titleError || expectedError || stepErrors

  return (
    <Card>
      <CardHeader
        title="Editing test case"
        description={`${draft.ref} — changes are attributed to you and recorded in the audit chain.`}
        icon={<Pencil aria-hidden="true" />}
        actions={
          dirty ? (
            <Badge tone="warn">Unsaved changes</Badge>
          ) : (
            <Badge tone="neutral">No changes</Badge>
          )
        }
      />

      <div className="space-y-4 p-4">
        <div>
          <label
            htmlFor="tc-title"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            Title
          </label>
          <input
            id="tc-title"
            value={draft.title}
            onChange={(e) => set('title', e.target.value)}
            aria-invalid={titleError}
            className={cn(FIELD, titleError && 'border-[var(--danger-border)]')}
          />
          {titleError ? (
            <p role="alert" className="mt-1.5 text-xs text-[var(--danger)]">
              A title needs at least 10 characters so the case is identifiable in a run report.
            </p>
          ) : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label
              htmlFor="tc-level"
              className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
            >
              Level
            </label>
            <select
              id="tc-level"
              value={draft.level}
              onChange={(e) => set('level', e.target.value as TestCase['level'])}
              className={cn(FIELD, 'h-9 cursor-pointer py-0')}
            >
              {Object.entries(TEST_LEVEL_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor="tc-type"
              className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
            >
              Type
            </label>
            <select
              id="tc-type"
              value={draft.type}
              onChange={(e) => set('type', e.target.value as TestCase['type'])}
              className={cn(FIELD, 'h-9 cursor-pointer py-0')}
            >
              {Object.entries(TEST_TYPE_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor="tc-priority"
              className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
            >
              Priority
            </label>
            <select
              id="tc-priority"
              value={draft.priority}
              onChange={(e) => set('priority', e.target.value as TestCase['priority'])}
              className={cn(FIELD, 'h-9 cursor-pointer py-0')}
            >
              {['critical', 'high', 'medium', 'low'].map((p) => (
                <option key={p} value={p}>
                  {p[0].toUpperCase() + p.slice(1)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <SectionLabel>Automation</SectionLabel>
          <div className="mt-2 flex items-center gap-3">
            <Segmented
              label="Automation"
              value={draft.automatable ? 'auto' : 'manual'}
              onChange={(v) => set('automatable', v === 'auto')}
              options={[
                { id: 'auto', label: 'Automatable' },
                { id: 'manual', label: 'Needs a human' },
              ]}
            />
            <p className="text-xs leading-snug text-[var(--text-tertiary)]">
              {draft.automatable
                ? 'Can produce verified evidence.'
                : 'Will only ever produce an asserted result, which cannot satisfy a sign-off gate.'}
            </p>
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <SectionLabel>Steps</SectionLabel>
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus className="size-3.5" aria-hidden="true" />}
              onClick={addStep}
            >
              Add step
            </Button>
          </div>
          <ol className="space-y-2">
            {draft.steps.map((s) => (
              <li
                key={s.id}
                className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3"
              >
                <div className="flex items-start gap-2.5">
                  <span className="numeral mt-1.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-[var(--border-default)] bg-[var(--bg-surface)] text-[10px] font-semibold text-[var(--text-secondary)]">
                    {s.index}
                  </span>
                  <div className="min-w-0 flex-1 space-y-2">
                    <input
                      value={s.action}
                      onChange={(e) => setStep(s.id, { action: e.target.value })}
                      placeholder="Action — what the tester or agent does"
                      aria-label={`Step ${s.index} action`}
                      className={cn(FIELD, !s.action.trim() && 'border-[var(--danger-border)]')}
                    />
                    <input
                      value={s.expected}
                      onChange={(e) => setStep(s.id, { expected: e.target.value })}
                      placeholder="Expected — what should be observed"
                      aria-label={`Step ${s.index} expected result`}
                      className={cn(FIELD, !s.expected.trim() && 'border-[var(--danger-border)]')}
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => removeStep(s.id)}
                    aria-label={`Remove step ${s.index}`}
                    disabled={draft.steps.length === 1}
                  >
                    <X className="size-4" aria-hidden="true" />
                  </Button>
                </div>
              </li>
            ))}
          </ol>
          {stepErrors ? (
            <p role="alert" className="mt-2 text-xs text-[var(--danger)]">
              Every step needs both an action and an expected observation — a step without an
              expectation cannot pass or fail.
            </p>
          ) : null}
        </div>

        <div>
          <label
            htmlFor="tc-expected"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            Expected result — the single assertion this case proves
          </label>
          <textarea
            id="tc-expected"
            rows={3}
            value={draft.expectedResult}
            onChange={(e) => set('expectedResult', e.target.value)}
            aria-invalid={expectedError}
            className={cn(FIELD, 'resize-y', expectedError && 'border-[var(--danger-border)]')}
          />
          {expectedError ? (
            <p role="alert" className="mt-1.5 text-xs text-[var(--danger)]">
              State the expected result — it is what the execution report compares the actual
              outcome against.
            </p>
          ) : null}
        </div>

        <div>
          <label
            htmlFor="tc-data"
            className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]"
          >
            Test data
          </label>
          <input
            id="tc-data"
            value={draft.testData}
            onChange={(e) => set('testData', e.target.value)}
            className={FIELD}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
        <p className="text-xs text-[var(--text-tertiary)]">
          {draft.origin === 'ai_generated'
            ? 'Saving marks this case as AI + human edits.'
            : 'Your edit will be attributed in the audit chain.'}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            icon={<RotateCcw className="size-3.5" aria-hidden="true" />}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Save className="size-3.5" aria-hidden="true" />}
            onClick={onSave}
            disabled={invalid || !dirty}
          >
            Save case
          </Button>
        </div>
      </div>

      {invalid ? (
        <div className="flex items-start gap-2 border-t border-[var(--border-subtle)] px-3 py-2.5">
          <AlertTriangle
            className="mt-px size-3.5 shrink-0 text-[var(--warn)]"
            aria-hidden="true"
          />
          <p className="text-xs text-[var(--text-tertiary)]">
            Fix the highlighted fields before saving.
          </p>
        </div>
      ) : null}
    </Card>
  )
}

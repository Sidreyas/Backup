import { useMemo, useState } from 'react'
import { Layers, Pencil, Plus, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge, Button, EmptyState } from '@/components/ui/primitives'
import { Modal, useToast } from '@/components/ui/overlays'
import { TEST_LEVEL_LABEL } from '@/components/domain/status'
import { api } from '@/lib/api'
import type { TestCase, TestSuite } from '@/lib/types'

/**
 * Create and manage saved test suites.
 *
 * A suite is a named selection of cases you intend to run together — a smoke
 * set, a regression pack, the cases an auditor asked about. It stores case ids
 * rather than copies, so a suite always runs the current version of a case.
 */
export function SuiteManager({
  open,
  onClose,
  cases,
  suites,
  onChanged,
}: {
  open: boolean
  onClose: () => void
  cases: TestCase[]
  suites: TestSuite[]
  onChanged: () => void
}) {
  const [mode, setMode] = useState<'list' | 'edit'>('list')
  const [editing, setEditing] = useState<TestSuite | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const { push } = useToast()

  const caseById = useMemo(() => new Map(cases.map((c) => [c.id, c])), [cases])

  function startNew() {
    setEditing(null)
    setName('')
    setDescription('')
    setPicked(new Set())
    setMode('edit')
  }

  function startEdit(suite: TestSuite) {
    setEditing(suite)
    setName(suite.name)
    setDescription(suite.description)
    setPicked(new Set(suite.caseIds))
    setMode('edit')
  }

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function save() {
    setSaving(true)
    try {
      if (editing) {
        await api.updateTestSuite(editing.id, { name, description, caseIds: [...picked] })
        push({ tone: 'ok', title: 'Suite updated', description: `${name} now holds ${picked.size} cases.` })
      } else {
        await api.createTestSuite({ name, description, caseIds: [...picked] })
        push({
          tone: 'ok',
          title: 'Suite created',
          description: `${name} is available when you launch a run.`,
        })
      }
      onChanged()
      setMode('list')
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: string) {
    await api.deleteTestSuite(id)
    setConfirmDelete(null)
    onChanged()
    push({
      tone: 'info',
      title: 'Suite deleted',
      // Says what survived: deleting a grouping should not read as deleting tests.
      description: 'The cases themselves are untouched — only the grouping is gone.',
    })
  }

  /* A suite of nothing cannot be run, so it cannot be saved. */
  const valid = name.trim().length > 1 && picked.size > 0

  /*
   * Approved cases are offered first. A suite is a thing you intend to run, and
   * an unapproved case cannot be executed — including them without comment
   * would build a suite that silently under-runs.
   */
  const sortedCases = useMemo(() => {
    const rank = (c: TestCase) => (c.state === 'approved' ? 0 : 1)
    return [...cases].sort((a, b) => rank(a) - rank(b) || a.ref.localeCompare(b.ref))
  }, [cases])

  const pickedUnapproved = [...picked].filter(
    (id) => caseById.get(id)?.state !== 'approved',
  ).length

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={mode === 'list' ? 'Test suites' : editing ? `Edit ${editing.ref}` : 'New test suite'}
      size="lg"
    >
      {mode === 'list' ? (
        <>
          <div className="mb-3 flex items-start justify-between gap-3">
            <p className="text-[12px] leading-relaxed text-[var(--text-secondary)]">
              A named set of cases you run together — a smoke set, a regression pack, the cases an
              auditor asked to see. Suites reference cases rather than copying them, so they always
              run the current version.
            </p>
            <Button
              variant="primary"
              size="sm"
              icon={<Plus className="size-4" aria-hidden="true" />}
              onClick={startNew}
            >
              New suite
            </Button>
          </div>

          {suites.length === 0 ? (
            <EmptyState
              icon={<Layers className="size-5" aria-hidden="true" />}
              title="No suites yet"
              description="Group the cases you run together so you do not rebuild the selection each time."
              action={
                <Button variant="secondary" onClick={startNew}>
                  Create the first suite
                </Button>
              }
            />
          ) : (
            <ul className="space-y-2">
              {suites.map((s) => {
                const known = s.caseIds.filter((id) => caseById.has(id))
                const runnable = known.filter((id) => caseById.get(id)?.state === 'approved')
                return (
                  <li
                    key={s.id}
                    className="rounded-xl border border-[var(--border-subtle)] p-3"
                  >
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="numeral text-[11px] text-[var(--text-tertiary)]">
                            {s.ref}
                          </span>
                          <span className="text-[13px] font-semibold text-[var(--text-primary)]">
                            {s.name}
                          </span>
                          {s.saved ? null : <Badge tone="neutral">Ad hoc</Badge>}
                        </div>
                        <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                          {s.description}
                        </p>
                        <p className="mt-1.5 text-[11px] text-[var(--text-tertiary)]">
                          {known.length} case{known.length === 1 ? '' : 's'}
                          {/*
                           * The runnable count is stated separately whenever it
                           * differs. A suite of 6 that only runs 4 is a fact
                           * worth knowing before launch, not after.
                           */}
                          {runnable.length !== known.length ? (
                            <span className="text-[var(--warn)]">
                              {' '}
                              · {runnable.length} approved and runnable
                            </span>
                          ) : null}
                          {' · '}
                          {s.createdBy}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Pencil className="size-3.5" aria-hidden="true" />}
                          onClick={() => startEdit(s)}
                          aria-label={`Edit ${s.name}`}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 className="size-3.5" aria-hidden="true" />}
                          onClick={() => setConfirmDelete(s.id)}
                          aria-label={`Delete ${s.name}`}
                        />
                      </div>
                    </div>

                    {confirmDelete === s.id ? (
                      <div className="mt-2.5 flex flex-wrap items-center gap-2 rounded-lg bg-[var(--bg-surface-2)] p-2">
                        <span className="text-[12px] text-[var(--text-secondary)]">
                          Delete this suite? The cases stay.
                        </span>
                        <Button variant="danger" size="sm" onClick={() => remove(s.id)}>
                          Delete
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(null)}>
                          Keep
                        </Button>
                      </div>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}
        </>
      ) : (
        <div className="space-y-3.5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="suite-name"
                className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
              >
                Suite name
              </label>
              <input
                id="suite-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Payroll regression"
                className="h-9 w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 text-[13px] text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10"
              />
            </div>
            <div>
              <label
                htmlFor="suite-desc"
                className="mb-1.5 block text-[12px] font-semibold text-[var(--text-primary)]"
              >
                What it is for
              </label>
              <input
                id="suite-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Run before every payroll-affecting release"
                className="h-9 w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 text-[13px] text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10"
              />
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="text-[12px] font-semibold text-[var(--text-primary)]">
                Cases in this suite
              </span>
              <span className="text-[11px] text-[var(--text-tertiary)]">
                {picked.size} of {cases.length} selected
              </span>
            </div>

            <ul className="max-h-[280px] divide-y divide-[var(--border-subtle)] overflow-y-auto rounded-lg border border-[var(--border-subtle)]">
              {sortedCases.map((c) => {
                const on = picked.has(c.id)
                return (
                  <li key={c.id}>
                    <label
                      className={cn(
                        'flex cursor-pointer items-start gap-2.5 p-2.5 transition-colors',
                        on ? 'bg-[var(--accent-subtle)]' : 'hover:bg-[var(--bg-hover)]',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => toggle(c.id)}
                        className="mt-0.5 size-3.5 shrink-0 accent-[var(--accent)]"
                        aria-label={`Include ${c.ref}`}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="numeral text-[11px] text-[var(--text-tertiary)]">
                            {c.ref}
                          </span>
                          <span className="text-[11px] text-[var(--text-tertiary)]">
                            {TEST_LEVEL_LABEL[c.level]}
                          </span>
                          {c.state !== 'approved' ? (
                            <Badge tone="warn">Not approved</Badge>
                          ) : null}
                          {!c.automatable ? <Badge tone="asserted">Manual</Badge> : null}
                        </span>
                        <span className="mt-0.5 block text-[12px] leading-snug text-[var(--text-primary)]">
                          {c.title}
                        </span>
                      </span>
                    </label>
                  </li>
                )
              })}
            </ul>

            {pickedUnapproved > 0 ? (
              <p className="mt-2 rounded-lg bg-[var(--warn-subtle)] px-2.5 py-2 text-[11px] leading-snug text-[var(--warn)]">
                {pickedUnapproved} selected case{pickedUnapproved === 1 ? ' is' : 's are'} not
                approved and will be skipped at launch. Included here so the suite is complete once
                they are — the run will say what it skipped.
              </p>
            ) : null}
          </div>
        </div>
      )}

      <div className="mt-4 flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] pt-3.5">
        <Button variant="ghost" onClick={() => (mode === 'edit' ? setMode('list') : onClose())}>
          {mode === 'edit' ? 'Back' : 'Close'}
        </Button>
        {mode === 'edit' ? (
          <Button variant="primary" disabled={!valid} loading={saving} onClick={save}>
            {editing ? 'Save changes' : 'Create suite'}
          </Button>
        ) : null}
      </div>
    </Modal>
  )
}

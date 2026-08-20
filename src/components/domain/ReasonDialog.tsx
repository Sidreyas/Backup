/**
 * Reason-for-change capture.
 *
 * 21 CFR Part 11 §11.10(e) requires the audit trail to record *why* a
 * governed record changed, not only what changed and who did it. Asking at the
 * moment of the edit is the only point at which the answer is reliable —
 * reconstructed rationales are written to justify a decision already made.
 *
 * The dialog shows the field-level diff above the input on purpose. A reviewer
 * who can see that an expected result was weakened writes a different reason
 * than one who was only told "you edited a test case".
 */
import { useEffect, useState } from 'react'
import { ArrowRight, PenLine } from 'lucide-react'
import { Modal } from '@/components/ui/overlays'
import { Button, SectionLabel } from '@/components/ui/primitives'
import type { FieldChange } from '@/lib/types'

export function ReasonDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  changes,
  /** Some actions may proceed without a stated reason; approvals may not. */
  required = true,
  confirmLabel = 'Save and record',
  busy = false,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  title: string
  description?: string
  changes: FieldChange[]
  required?: boolean
  confirmLabel?: string
  busy?: boolean
}) {
  const [reason, setReason] = useState('')

  /* Clear between openings so a prior rationale is never reused by accident. */
  useEffect(() => {
    if (open) setReason('')
  }, [open])

  const canConfirm = !busy && (!required || reason.trim().length >= 8)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={
        description ??
        'This change is written to the audit chain with its before and after values.'
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => onConfirm(reason.trim())}
            disabled={!canConfirm}
          >
            {busy ? 'Recording…' : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {changes.length > 0 ? (
          <div>
            <SectionLabel>What is changing</SectionLabel>
            <ul className="mt-2 space-y-2">
              {changes.map((c) => (
                <li
                  key={c.field}
                  className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3"
                >
                  <p className="text-xs font-medium text-[var(--text-primary)]">{c.label}</p>
                  <div className="mt-1.5 flex flex-col gap-1.5 sm:flex-row sm:items-start">
                    <p className="min-w-0 flex-1 rounded border border-[var(--danger-border)] bg-[var(--danger-subtle)] px-2 py-1 font-mono text-[11px] break-words text-[var(--text-secondary)]">
                      {c.before ?? '—'}
                    </p>
                    <ArrowRight
                      className="mt-1 hidden size-3 shrink-0 text-[var(--text-tertiary)] sm:block"
                      aria-hidden="true"
                    />
                    <p className="min-w-0 flex-1 rounded border border-[var(--ok-border)] bg-[var(--ok-subtle)] px-2 py-1 font-mono text-[11px] break-words text-[var(--text-primary)]">
                      {c.after ?? '—'}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div>
          <label
            htmlFor="reason-for-change"
            className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-primary)]"
          >
            <PenLine className="size-3.5" aria-hidden="true" />
            Reason for change{required ? '' : ' (optional)'}
          </label>
          <textarea
            id="reason-for-change"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder="Why is this change being made? An auditor will read this."
            className="mt-1.5 w-full resize-y rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)] focus-visible:border-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--accent-ring)]"
          />
          {required && reason.trim().length > 0 && reason.trim().length < 8 ? (
            <p className="mt-1 text-[11px] text-[var(--warn)]">
              Give enough detail that someone reading this in a year understands the decision.
            </p>
          ) : (
            <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
              Recorded against your name and cannot be edited once written.
            </p>
          )}
        </div>
      </div>
    </Modal>
  )
}

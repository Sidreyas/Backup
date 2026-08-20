import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { JudgeRubric, RubricDimensionId, RubricVerdict } from '@/lib/types'

const DIMENSION_LABEL: Record<RubricDimensionId, string> = {
  specificity: 'Specificity',
  traceability: 'Traceability',
  testability: 'Testability',
  risk_coverage: 'Risk coverage',
  evidence_grounding: 'Evidence grounding',
}

const VERDICT_LABEL: Record<RubricVerdict, string> = {
  accept: 'Accept',
  revise: 'Needs revision',
  reject: 'Reject',
}

/** Coarse bands — a 4.1 and a 4.3 are not different judgements. */
const band = (n: number) => (n >= 4 ? 'strong' : n >= 3 ? 'fair' : 'weak')

const DOT = {
  strong: 'bg-[var(--ok-solid)]',
  fair: 'bg-[var(--warn-solid)]',
  weak: 'bg-[var(--danger-solid)]',
} as const

const TEXT = {
  strong: 'text-[var(--ok)]',
  fair: 'text-[var(--warn)]',
  weak: 'text-[var(--danger)]',
} as const

/**
 * An LLM's assessment of a generated test case, kept deliberately short.
 *
 * One line: score, verdict, and the single dimension that scored worst — which
 * is the only part a reviewer acts on. Everything else is behind a toggle.
 *
 * Never a gate. The verdict is shown, but approval stays a human action.
 */
export function JudgeRubricPanel({
  rubric,
  defaultOpen = false,
}: {
  rubric: JudgeRubric
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const stale = rubric.supersededByEdit
  const b = band(rubric.overall)

  /* The weakest dimension, named only when it is actually weak. A "lowest
     score" callout on a case scoring 4.5 across the board is noise. */
  const weakest = [...rubric.scores].sort((a, x) => a.score - x.score)[0]
  const concern = weakest && weakest.score < 4 ? weakest : null

  return (
    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[12px]">
        <span
          className={cn('size-1.5 shrink-0 self-center rounded-full', stale ? 'bg-[var(--text-tertiary)]' : DOT[b])}
          aria-hidden="true"
        />
        <span className="font-medium text-[var(--text-primary)]">Judge rubric</span>
        <span className={cn('numeral font-semibold', stale ? 'text-[var(--text-tertiary)]' : TEXT[b])}>
          {rubric.overall.toFixed(1)}
          <span className="font-normal text-[var(--text-tertiary)]">/5</span>
        </span>
        <span className="text-[var(--text-tertiary)]">
          {stale ? 'superseded by your edit' : VERDICT_LABEL[rubric.verdict].toLowerCase()}
        </span>

        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="ml-auto cursor-pointer text-[11px] text-[var(--accent)] hover:underline"
        >
          {open ? 'Less' : 'Details'}
        </button>
      </div>

      {/* The one thing worth acting on, in the collapsed state. */}
      {concern && !open ? (
        <p className="mt-1.5 text-[11px] leading-snug text-[var(--text-secondary)]">
          <span className={cn('font-medium', TEXT[band(concern.score)])}>
            {DIMENSION_LABEL[concern.dimension]} {concern.score.toFixed(1)}
          </span>{' '}
          — {concern.rationale}
        </p>
      ) : null}

      {open ? (
        <div className="mt-2.5 space-y-2 border-t border-[var(--border-subtle)] pt-2.5">
          <p className="text-[11px] leading-relaxed text-[var(--text-secondary)]">
            {rubric.summary}
          </p>

          <dl className="space-y-1">
            {rubric.scores.map((s) => (
              <div key={s.dimension} className="flex items-baseline gap-2 text-[11px]">
                <dt className="w-[120px] shrink-0 text-[var(--text-tertiary)]">
                  {DIMENSION_LABEL[s.dimension]}
                </dt>
                <dd className={cn('numeral w-7 shrink-0 font-semibold', TEXT[band(s.score)])}>
                  {s.score.toFixed(1)}
                </dd>
                <dd className="min-w-0 flex-1 leading-snug text-[var(--text-secondary)]">
                  {s.rationale}
                </dd>
              </div>
            ))}
          </dl>

          {/* Provenance in one line. Without the inputs the score cannot be
              reproduced; without the disclaimer a green number beside an
              Approve button reads as permission to click it. */}
          <p className="text-[10px] leading-snug text-[var(--text-tertiary)]">
            {rubric.judgeModel} · judged against {rubric.inputs.join(', ')} · advisory only,
            approval is recorded against you
          </p>
        </div>
      ) : null}
    </div>
  )
}

/** Compact mark for list rows. */
export function RubricScorePill({ rubric }: { rubric: JudgeRubric }) {
  const stale = rubric.supersededByEdit
  const b = band(rubric.overall)
  return (
    <span
      className={cn(
        'numeral inline-flex items-center gap-1 text-[11px] font-medium',
        stale ? 'text-[var(--text-tertiary)]' : TEXT[b],
      )}
      title={
        stale
          ? `Judge rubric ${rubric.overall.toFixed(1)}/5, superseded by a human edit`
          : `Judge rubric ${rubric.overall.toFixed(1)}/5 — ${VERDICT_LABEL[rubric.verdict]}`
      }
    >
      <span
        className={cn(
          'size-1.5 rounded-full',
          stale ? 'border border-[var(--text-tertiary)]' : DOT[b],
        )}
        aria-hidden="true"
      />
      {rubric.overall.toFixed(1)}
      <span className="sr-only"> of 5, judge rubric</span>
    </span>
  )
}

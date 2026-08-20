import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, Download, FileText, Printer, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/primitives'
import { useFocusTrap } from '@/components/ui/overlays'

/**
 * Export preview.
 *
 * Exporting a governance document is a moment where the user needs to see what
 * they are about to circulate — a plan that leaves the building becomes the
 * record other people act on. So the download is offered *after* a preview
 * rather than as a blind button.
 *
 * The preview renders the document at page proportions on a neutral backdrop,
 * so what is on screen is recognisably what lands in the PDF.
 */
export function DocumentPreview({
  open,
  onClose,
  title,
  subtitle,
  filename,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  /** Suggested download name, shown so the user knows what they will get. */
  filename: string
  children: ReactNode
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'idle' | 'preparing' | 'done'>('idle')
  useFocusTrap(panelRef, open, onClose)

  // Reset between openings, so a second export does not open on "done".
  useEffect(() => {
    if (open) setState('idle')
  }, [open])

  useEffect(() => {
    if (state !== 'done') return
    const t = window.setTimeout(() => setState('idle'), 2400)
    return () => window.clearTimeout(t)
  }, [state])

  if (!open) return null

  async function download() {
    setState('preparing')
    // A real build would stream a rendered PDF; the delay stands in for it so
    // the button exercises its pending state rather than resolving instantly.
    await new Promise((r) => setTimeout(r, 900))
    setState('done')
  }

  return createPortal(
    <div
      className="animate-fade fixed inset-0 z-[var(--z-modal)] flex items-center justify-center bg-[var(--scrim)] p-4 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${title} — export preview`}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'animate-scale-in relative flex h-[88vh] max-h-[860px] w-full max-w-5xl shrink-0 basis-full',
          'flex-col overflow-hidden rounded-xl border border-[var(--border-default)]',
          'bg-[var(--bg-surface)] shadow-[var(--shadow-xl)]',
        )}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]"
              aria-hidden="true"
            >
              <FileText className="size-4" />
            </span>
            <div className="min-w-0">
              <p className="truncate text-[13px] font-semibold text-[var(--text-primary)]">
                {title}
              </p>
              <p className="truncate font-mono text-[11px] text-[var(--text-tertiary)]">
                {filename}
              </p>
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close preview">
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>

        {/* Paper. The inset backdrop is what makes this read as a document
            preview rather than another panel of the app. */}
        <div className="min-h-0 flex-1 overflow-y-auto bg-[var(--bg-inset)] p-4 sm:p-8">
          <article
            data-doc-preview
            className={cn(
              'mx-auto w-full max-w-[760px] rounded-lg border border-[var(--border-subtle)]',
              'bg-[var(--bg-surface)] px-8 py-9 shadow-[var(--shadow-md)] sm:px-12',
            )}
          >
            <header className="border-b border-[var(--border-subtle)] pb-5">
              <p className="text-[10px] font-bold tracking-[0.12em] text-[var(--text-tertiary)] uppercase">
                Meridian · Governed change record
              </p>
              <h1 className="mt-2 text-xl font-semibold tracking-tight text-[var(--text-primary)]">
                {title}
              </h1>
              {subtitle ? (
                <p className="mt-1 text-[13px] text-[var(--text-secondary)]">{subtitle}</p>
              ) : null}
            </header>
            <div className="pt-5">{children}</div>
          </article>
        </div>

        {/* Footer */}
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-4 py-3">
          <p className="text-[11px] leading-snug text-[var(--text-tertiary)]">
            The export carries the same evidence grades and declared gaps shown in the app. It is a
            snapshot, not a live document.
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Printer className="size-3.5" aria-hidden="true" />}
              onClick={() => window.print()}
            >
              Print
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={download}
              loading={state === 'preparing'}
              icon={
                state === 'done' ? (
                  <Check className="size-3.5" aria-hidden="true" />
                ) : state === 'preparing' ? undefined : (
                  <Download className="size-3.5" aria-hidden="true" />
                )
              }
            >
              {state === 'done'
                ? 'Downloaded'
                : state === 'preparing'
                  ? 'Preparing…'
                  : 'Download PDF'}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* ------------------------------------------------------- document blocks */

/** A titled section inside a previewed document. */
export function DocSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-6 last:mb-0">
      <h2 className="mb-2 text-[10px] font-bold tracking-[0.1em] text-[var(--text-tertiary)] uppercase">
        {title}
      </h2>
      {children}
    </section>
  )
}

/** Label/value pairs rendered as a definition grid. */
export function DocFacts({ facts }: { facts: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5">
      {facts.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-[11px] text-[var(--text-tertiary)]">{k}</dt>
          <dd className="mt-0.5 text-[13px] font-medium break-words text-[var(--text-primary)]">
            {v}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** Bulleted list in document typography. */
export function DocList({ items, tone }: { items: string[]; tone?: 'warn' }) {
  if (items.length === 0) {
    return <p className="text-[13px] text-[var(--text-tertiary)]">None recorded.</p>
  }
  return (
    <ul className="space-y-1.5">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-2">
          <span
            className={cn(
              'mt-[7px] size-1.5 shrink-0 rounded-full',
              tone === 'warn' ? 'bg-[var(--warn-solid)]' : 'bg-[var(--text-tertiary)]',
            )}
            aria-hidden="true"
          />
          <span className="text-[13px] leading-relaxed text-[var(--text-secondary)]">{t}</span>
        </li>
      ))}
    </ul>
  )
}

/** Criteria rendered with an explicit met / unmet / not-evaluated mark. */
export function DocCriteria({
  items,
}: {
  items: { id: string; text: string; met: boolean | null; detail?: string }[]
}) {
  return (
    <ul className="space-y-2">
      {items.map((c) => (
        <li key={c.id} className="flex items-start gap-2.5">
          <span
            className={cn(
              'mt-px flex size-4 shrink-0 items-center justify-center rounded-full text-[9px] font-bold',
              c.met === true && 'bg-[var(--ok-subtle)] text-[var(--ok)]',
              c.met === false && 'bg-[var(--danger-subtle)] text-[var(--danger)]',
              c.met === null && 'bg-[var(--bg-surface-3)] text-[var(--text-tertiary)]',
            )}
            aria-hidden="true"
          >
            {c.met === true ? '✓' : c.met === false ? '✕' : '–'}
          </span>
          <span className="min-w-0">
            <span className="block text-[13px] leading-snug text-[var(--text-primary)]">
              {c.text}
            </span>
            {c.detail ? (
              <span className="mt-0.5 block text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                {c.detail}
              </span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  )
}

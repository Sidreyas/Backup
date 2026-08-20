import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { CheckCircle2, Info, X, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from './primitives'

/* -------------------------------------------------------------- focus trap */

/**
 * Traps Tab focus inside `ref` while `active`, restores focus to whatever was
 * focused before on unmount, and calls `onEscape` on the Escape key.
 */
export function useFocusTrap(
  ref: React.RefObject<HTMLElement | null>,
  active: boolean,
  onEscape: () => void,
) {
  useEffect(() => {
    if (!active) return
    const previouslyFocused = document.activeElement as HTMLElement | null
    const node = ref.current
    if (!node) return

    const SELECTOR =
      'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'

    // Move focus in without stealing it from an element the panel autofocuses.
    const focusables = () => Array.from(node.querySelectorAll<HTMLElement>(SELECTOR))
    const timer = window.setTimeout(() => {
      if (!node.contains(document.activeElement)) focusables()[0]?.focus()
    }, 0)

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onEscape()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('keydown', onKeyDown, true)
      document.body.style.overflow = prevOverflow
      previouslyFocused?.focus?.()
    }
  }, [active, onEscape, ref])
}

/* -------------------------------------------------------------------- Modal */

export function Modal({
  open,
  onClose,
  title,
  description,
  icon,
  meta,
  headerNav,
  children,
  footer,
  size = 'md',
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  /** Rendered beside the title — a brand mark identifying what this is about. */
  icon?: ReactNode
  /** Rendered under the title: status and other at-a-glance facts. */
  meta?: ReactNode
  /** Rendered flush to the bottom of the header — a tab strip, typically. */
  headerNav?: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descId = useId()
  useFocusTrap(panelRef, open, onClose)

  if (!open) return null

  const widths = { sm: 'max-w-md', md: 'max-w-2xl', lg: 'max-w-4xl' }

  return createPortal(
    // The scrim is painted by the wrapper itself rather than an overlaid
    // sibling: backdrop-filter creates a stacking context, and a sibling scrim
    // ends up intercepting clicks meant for the panel. Click-outside is handled
    // here, and the panel stops propagation.
    <div
      className={cn(
        'animate-fade fixed inset-0 z-[var(--z-modal)] flex items-center justify-center p-4',
        'bg-[var(--scrim)] backdrop-blur-[2px]',
      )}
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          // basis-full + shrink-0 so the flex-centred panel keeps its width;
          // w-full alone lets the flex parent shrink it to its content box
          'animate-scale-in relative flex max-h-[85vh] w-full shrink-0 basis-full flex-col overflow-hidden rounded-xl',
          'border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-xl)]',
          widths[size],
        )}
      >
        {/* The header owns the bottom border only when no nav follows it —
            otherwise the tab strip's own underline would double up. */}
        <div className={cn(!headerNav && 'border-b border-[var(--border-subtle)]')}>
        <div className="flex items-start justify-between gap-4 px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            {/* Identity belongs beside the title, not repeated in the body. */}
            {icon ? <span className="shrink-0">{icon}</span> : null}
            <div className="min-w-0">
              <h2 id={titleId} className="text-base font-semibold text-[var(--text-primary)]">
                {title}
              </h2>
              {description ? (
                <p id={descId} className="mt-0.5 text-xs text-[var(--text-tertiary)]">
                  {description}
                </p>
              ) : null}
              {meta ? <div className="mt-1.5 flex flex-wrap items-center gap-2">{meta}</div> : null}
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close dialog">
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>
        {headerNav ? (
          <div className="border-b border-[var(--border-subtle)] px-5">{headerNav}</div>
        ) : null}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? (
          <div className="flex items-center justify-end gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}

/* ------------------------------------------------------------------- Drawer */

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = 'md',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
  width?: 'md' | 'lg'
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useFocusTrap(panelRef, open, onClose)

  if (!open) return null

  return createPortal(
    // Scrim painted by the wrapper — see the note on Modal for why.
    <div
      className="animate-fade fixed inset-0 z-[var(--z-drawer)] bg-[var(--scrim)]"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'animate-slide-in-right absolute inset-y-0 right-0 flex w-full flex-col',
          'border-l border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-xl)]',
          width === 'lg' ? 'sm:max-w-3xl' : 'sm:max-w-xl',
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-[var(--border-subtle)] px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-sm font-semibold text-[var(--text-primary)]">
              {title}
            </h2>
            {subtitle ? (
              <div className="mt-1 text-xs text-[var(--text-tertiary)]">{subtitle}</div>
            ) : null}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close panel">
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        {footer ? (
          <div className="flex items-center justify-end gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}

/* --------------------------------------------------------------------- Tabs */

export interface TabItem {
  id: string
  label: string
  count?: number
  icon?: ReactNode
}

export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem[]
  value: string
  onChange: (id: string) => void
  className?: string
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  // Arrow-key navigation is expected for a tablist.
  function onKeyDown(e: React.KeyboardEvent) {
    const idx = items.findIndex((i) => i.id === value)
    if (idx < 0) return
    let next = idx
    if (e.key === 'ArrowRight') next = (idx + 1) % items.length
    else if (e.key === 'ArrowLeft') next = (idx - 1 + items.length) % items.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    else return
    e.preventDefault()
    onChange(items[next].id)
    refs.current[items[next].id]?.focus()
  }

  return (
    <div
      role="tablist"
      onKeyDown={onKeyDown}
      /*
       * Tabs wrap; they never scroll. `overflow-x-auto` reserved a scrollbar
       * track even when every tab fitted, which showed as a stray gutter beside
       * the last tab. Scrolling would also be the wrong answer if they ever did
       * overflow — a tab hidden off-screen is a tab nobody finds.
       */
      className={cn(
        'flex flex-wrap items-center gap-0.5 border-b border-[var(--border-subtle)]',
        className,
      )}
    >
      {items.map((item) => {
        const active = item.id === value
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[item.id] = el
            }}
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.id)}
            className={cn(
              'relative inline-flex min-h-9 shrink-0 cursor-pointer items-center gap-1.5 px-3 py-2',
              'text-sm font-medium transition-colors duration-200',
              active
                ? 'text-[var(--accent-text)]'
                : 'text-[var(--text-tertiary)] hover:text-[var(--text-primary)]',
            )}
          >
            {item.icon}
            {item.label}
            {typeof item.count === 'number' ? (
              <span
                className={cn(
                  'tabular rounded px-1 py-px text-[10px] font-semibold',
                  active
                    ? 'bg-[var(--accent-subtle)] text-[var(--accent-text)]'
                    : 'bg-[var(--bg-surface-3)] text-[var(--text-tertiary)]',
                )}
              >
                {item.count}
              </span>
            ) : null}
            {active ? (
              <span
                aria-hidden="true"
                className="absolute inset-x-0 -bottom-px h-0.5 bg-[var(--accent)]"
              />
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

/* -------------------------------------------------------------------- Toast */

interface Toast {
  id: string
  title: string
  description?: string
  tone: 'ok' | 'danger' | 'info' | 'warn'
}

const ToastContext = createContext<{ push: (t: Omit<Toast, 'id'>) => void }>({
  push: () => {},
})

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).slice(2)
    setToasts((prev) => [...prev, { ...t, id }])
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id))
    }, 4500)
  }, [])

  const value = useMemo(() => ({ push }), [push])

  const ICONS = {
    ok: <CheckCircle2 className="size-4 text-[var(--ok)]" aria-hidden="true" />,
    danger: <AlertTriangle className="size-4 text-[var(--danger)]" aria-hidden="true" />,
    warn: <AlertTriangle className="size-4 text-[var(--warn)]" aria-hidden="true" />,
    info: <Info className="size-4 text-[var(--info)]" aria-hidden="true" />,
  }

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        // aria-live so screen readers announce without the toast stealing focus
        <div
          /*
           * left-4 + right-4 rather than w-[calc(100vw-2rem)]: 100vw counts the
           * vertical scrollbar, so the calc came out wider than the usable
           * viewport and forced a horizontal scrollbar on every page — which in
           * turn inflated documentElement.scrollHeight by the scrollbar's own
           * height and made the whole document appear scrollable.
           */
          className="pointer-events-none fixed right-4 bottom-4 left-4 z-[var(--z-toast)] ml-auto flex max-w-sm flex-col gap-2"
          aria-live="polite"
          aria-atomic="false"
        >
          {toasts.map((t) => (
            <div
              key={t.id}
              className="animate-in pointer-events-auto flex items-start gap-2.5 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-3 shadow-[var(--shadow-lg)]"
            >
              <span className="mt-px shrink-0">{ICONS[t.tone]}</span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-[var(--text-primary)]">{t.title}</p>
                {t.description ? (
                  <p className="mt-0.5 text-xs leading-snug text-[var(--text-tertiary)]">
                    {t.description}
                  </p>
                ) : null}
              </div>
              <button
                onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
                className="shrink-0 cursor-pointer rounded p-0.5 text-[var(--text-tertiary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                aria-label={`Dismiss: ${t.title}`}
              >
                <X className="size-3.5" aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}

/* ------------------------------------------------------------------ Tooltip */

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group/tip relative inline-flex">
      {children}
      {/*
       * `hidden` until hover, rather than opacity-0.
       *
       * An absolutely-positioned element still contributes to an ancestor's
       * scrollWidth even at opacity 0 or visibility:hidden. Inside the 68px
       * collapsed sidebar these labels are wider than the rail, which made it
       * genuinely scroll sideways by ~26px. display:none is the only hide that
       * removes them from layout; the trade-off is losing the fade-in, which
       * is not worth a scrollbar.
       */}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute bottom-full left-1/2 z-[var(--z-dropdown)] mb-1.5 -translate-x-1/2',
          'rounded border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 py-1',
          'text-[11px] whitespace-nowrap text-[var(--text-primary)] shadow-[var(--shadow-md)]',
          'hidden group-hover/tip:block group-focus-within/tip:block',
        )}
      >
        {label}
      </span>
    </span>
  )
}

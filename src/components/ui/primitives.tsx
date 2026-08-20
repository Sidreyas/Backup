import { type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode, forwardRef } from 'react'
import { ArrowDown, ArrowUp, Loader2, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'

/* -------------------------------------------------------------------- Button */

type ButtonVariant = 'primary' | 'emphasis' | 'secondary' | 'ghost' | 'danger' | 'subtle'
type ButtonSize = 'sm' | 'md' | 'lg' | 'icon'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-[var(--accent)] text-[var(--accent-on)] hover:bg-[var(--accent-hover)] border border-transparent shadow-[var(--shadow-sm)]',
  /*
   * The near-black "Add funds" button. Sits beside a blue primary without
   * competing for the same slot: blue is "start the main flow", emphasis is
   * "resolve the thing this card is about".
   */
  emphasis:
    'bg-[var(--emphasis)] text-[var(--emphasis-on)] hover:bg-[var(--emphasis-hover)] border border-transparent shadow-[var(--shadow-sm)]',
  secondary:
    'bg-[var(--bg-surface)] text-[var(--text-primary)] border border-[var(--border-default)] hover:bg-[var(--bg-hover)] shadow-[var(--shadow-sm)]',
  ghost:
    'bg-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] border border-transparent',
  danger:
    'bg-[var(--danger-solid)] text-white hover:brightness-110 border border-transparent shadow-[var(--shadow-sm)]',
  subtle:
    'bg-[var(--bg-surface-2)] text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
}

/*
 * Fully rounded, as in the reference. Height still steps 8 / 9 / 11 so the
 * pills line up against inputs and segmented controls on the same row.
 */
const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 min-h-8 px-3 text-xs gap-1.5 rounded-lg',
  md: 'h-9 min-h-9 px-3.5 text-[13px] gap-1.5 rounded-[10px]',
  lg: 'h-11 min-h-11 px-5 text-sm gap-2 rounded-xl',
  icon: 'h-9 w-9 min-h-9 min-w-9 rounded-[10px] justify-center',
}

/**
 * Button classes for elements that cannot be a `<button>`.
 *
 * A file download has to be an `<a download>` — a button would need a fetch, a
 * blob URL and a revoke for something the browser does natively. Exporting the
 * recipe keeps such links identical to real buttons: hand-written Tailwind
 * beside a real one drifts, and the first version of the download link used a
 * `--accent-solid` token that does not exist, rendering white text on a
 * transparent background.
 */
export function buttonClasses(
  variant: ButtonVariant = 'secondary',
  size: ButtonSize = 'md',
  className?: string,
): string {
  return cn(
    'inline-flex items-center font-medium whitespace-nowrap select-none',
    'transition-[background-color,border-color,color,box-shadow,opacity] duration-200',
    'cursor-pointer',
    BUTTON_VARIANTS[variant],
    BUTTON_SIZES[size],
    className,
  )
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'secondary', size = 'md', loading, icon, children, disabled, ...props },
  ref,
) {
  const isDisabled = disabled || loading
  return (
    <button
      ref={ref}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center font-medium whitespace-nowrap select-none',
        'transition-[background-color,border-color,color,box-shadow,opacity] duration-200',
        /*
         * Disabled buttons are desaturated as well as dimmed. Opacity alone
         * left a violet primary reading as pale violet — still obviously the
         * inviting action, which is wrong for a control that cannot be used.
         */
        'cursor-pointer disabled:cursor-not-allowed disabled:opacity-45 disabled:grayscale',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden="true" /> : icon}
      {children}
    </button>
  )
})

/* ---------------------------------------------------------------------- Card */

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        // A hairline plus the faintest shadow. The reference's cards are raised
        // off the canvas, not drawn on it — at this radius the border alone
        // read as a wireframe once the page background stopped being white.
        'rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]',
        'shadow-[var(--shadow-sm)]',
        className,
      )}
      {...props}
    />
  )
}

/**
 * Card header in the reference's idiom: a small bordered icon tile, the title,
 * and an optional trailing action or badge.
 */
export function CardHeader({
  title,
  description,
  actions,
  icon,
  tone,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  icon?: ReactNode
  tone?: TileTone
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-4 border-b border-[var(--border-subtle)] px-4 py-3',
        className,
      )}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        {icon ? <IconTile tone={tone}>{icon}</IconTile> : null}
        <div className="min-w-0 flex-1">
          {/* 15px semibold: the reference's card titles read as headings against
              their body text rather than as slightly-bolder labels. */}
          <h3 className="text-[15px] font-semibold text-balance text-[var(--text-primary)]">
            {title}
          </h3>
          {description ? (
            <p className="mt-0.5 text-xs leading-snug text-[var(--text-tertiary)]">{description}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/**
 * Tones for the soft-square icon tile that fronts every card in the reference.
 *
 * `plain` is the default and stays neutral. The coloured tones are for cards
 * whose subject has a fixed identity — a category, a lifecycle stage — and not
 * for status: a tile is decoration beside a title, and colouring it by health
 * would put a second, quieter status signal next to the badge that already
 * says so properly.
 */
export type TileTone = 'plain' | 'accent' | 'ok' | 'warn' | 'danger' | 'info' | 'purple'

const TILE_TONES: Record<TileTone, string> = {
  plain: 'border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]',
  accent: 'bg-[var(--cat-1)] text-white',
  ok: 'bg-[var(--cat-3)] text-white',
  warn: 'bg-[var(--cat-2)] text-white',
  danger: 'bg-[var(--danger-solid)] text-white',
  info: 'bg-[var(--info-solid)] text-white',
  purple: 'bg-[var(--cat-4)] text-white',
}

/** The small soft-square that fronts every card header in the reference. */
export function IconTile({
  children,
  className,
  tone = 'plain',
}: {
  children: ReactNode
  className?: string
  tone?: TileTone
}) {
  return (
    <span
      className={cn(
        // rounded-[10px] on a 28px tile is the reference's squircle proportion —
        // rounded-lg reads as a slightly-softened square at this size.
        'flex size-7 shrink-0 items-center justify-center rounded-[10px] [&>svg]:size-3.5',
        TILE_TONES[tone],
        className,
      )}
      aria-hidden="true"
    >
      {children}
    </span>
  )
}

/* --------------------------------------------------------------------- Delta */

/**
 * The circled arrow + percentage of the reference's KPI tiles.
 *
 * `good` is passed explicitly rather than inferred from the sign, because
 * direction and desirability are independent: cost falling is good, coverage
 * falling is not. The arrow follows the number; the colour follows the meaning.
 * A flat delta gets a dash in neutral — no arrow, since there is no direction.
 */
export function Delta({
  value,
  direction,
  good,
  className,
}: {
  value: string
  direction: 'up' | 'down' | 'flat'
  good?: boolean
  className?: string
}) {
  const tone =
    direction === 'flat'
      ? 'text-[var(--text-tertiary)]'
      : good
        ? 'text-[var(--ok)]'
        : 'text-[var(--danger)]'

  const Icon = direction === 'up' ? ArrowUp : direction === 'down' ? ArrowDown : Minus

  return (
    <span className={cn('inline-flex items-center gap-1 text-xs font-medium', tone, className)}>
      <span
        className={cn(
          'flex size-3.5 shrink-0 items-center justify-center rounded-full',
          direction === 'flat'
            ? 'bg-[var(--neutral-subtle)]'
            : good
              ? 'bg-[var(--ok-subtle)]'
              : 'bg-[var(--danger-subtle)]',
        )}
        aria-hidden="true"
      >
        <Icon className="size-2.5" strokeWidth={3} />
      </span>
      <span className="tabular">{value}</span>
    </span>
  )
}

/* --------------------------------------------------------------------- Badge */

export type BadgeTone =
  'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'info' | 'verified' | 'asserted'

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'bg-[var(--neutral-subtle)] text-[var(--neutral)] border-[var(--neutral-border)]',
  accent: 'bg-[var(--accent-subtle)] text-[var(--accent-text)] border-[var(--accent-border)]',
  ok: 'bg-[var(--ok-subtle)] text-[var(--ok)] border-[var(--ok-border)]',
  warn: 'bg-[var(--warn-subtle)] text-[var(--warn)] border-[var(--warn-border)]',
  danger: 'bg-[var(--danger-subtle)] text-[var(--danger)] border-[var(--danger-border)]',
  info: 'bg-[var(--info-subtle)] text-[var(--info)] border-[var(--info-border)]',
  verified: 'bg-[var(--verified-subtle)] text-[var(--verified)] border-[var(--verified-border)]',
  asserted: 'bg-[var(--asserted-subtle)] text-[var(--asserted)] border-[var(--asserted-border)]',
}

export function Badge({
  tone = 'neutral',
  icon,
  children,
  className,
  mono,
}: {
  tone?: BadgeTone
  icon?: ReactNode
  children: ReactNode
  className?: string
  mono?: boolean
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap',
        mono && 'font-mono',
        BADGE_TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  )
}

/* ---------------------------------------------------------------- CountBadge */

/**
 * The filled circular count of the reference's sidebar — "Messages 3".
 *
 * Distinct from Badge: this is a volume of waiting work, always a number, and
 * always the same shape regardless of tone. A pill that grows with its label
 * would make a row of them ragged down the rail.
 */
export function CountBadge({
  count,
  tone = 'accent',
  label,
  className,
}: {
  count: number
  tone?: 'accent' | 'danger' | 'neutral'
  /** Announced after the number, e.g. "3 unread". */
  label?: string
  className?: string
}) {
  const tones = {
    accent: 'bg-[var(--accent)] text-[var(--accent-on)]',
    danger: 'bg-[var(--danger-solid)] text-white',
    neutral: 'bg-[var(--bg-surface-3)] text-[var(--text-secondary)]',
  }
  return (
    <span
      className={cn(
        'inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1.5',
        'text-[11px] leading-none font-semibold tabular-nums',
        tones[tone],
        className,
      )}
    >
      {count > 99 ? '99+' : count}
      {label ? <span className="sr-only"> {label}</span> : null}
    </span>
  )
}

/* ----------------------------------------------------------------- Sparkline */

/**
 * Inline trend line for KPI tiles. Purely decorative reinforcement of the delta
 * that is already stated in text, so it carries aria-hidden.
 */
export function Sparkline({
  data,
  tone = 'ok',
  className,
}: {
  data: number[]
  tone?: 'ok' | 'danger' | 'neutral'
  className?: string
}) {
  const w = 120
  const h = 40
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const step = w / Math.max(1, data.length - 1)

  const points = data.map((v, i) => [i * step, h - ((v - min) / span) * (h - 6) - 3] as const)
  const line = points
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ')
  const area = `${line} L${w},${h} L0,${h} Z`

  const stroke =
    tone === 'ok'
      ? 'var(--ok-solid)'
      : tone === 'danger'
        ? 'var(--danger-solid)'
        : 'var(--neutral-solid)'
  const gradId = `spark-${tone}`

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      // Width comes from the caller: a fixed 120px inside a flex row that could
      // not shrink was what pushed the line over the card edge on mobile.
      className={cn('h-10 w-[120px] max-w-full overflow-visible', className)}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradId})`} />
      <path
        d={line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

/* ------------------------------------------------------------------ StatTile */

/**
 * KPI card in the reference's idiom: a titled header rule, a large numeral,
 * then a footer pairing the change against the baseline it is measured from.
 *
 * The baseline matters more than it looks. "2.7×" alone is a number nobody can
 * judge; "2.7×, down from 3.1×" is the same number carrying its own verdict,
 * and it removes the guesswork about what the delta is a delta *of*.
 */
export function StatTile({
  label,
  value,
  sublabel,
  tone = 'neutral',
  icon,
  tileTone,
  delta,
  baseline,
  spark,
}: {
  label: string
  value: ReactNode
  sublabel?: string
  tone?: BadgeTone
  icon?: ReactNode
  tileTone?: TileTone
  delta?: { value: string; good: boolean; direction?: 'up' | 'down' | 'flat' }
  /** What the delta is measured against, e.g. "vs 3.1×". */
  baseline?: string
  spark?: number[]
}) {
  return (
    // overflow-hidden so the body and footer bands are clipped by the card's
    // own radius instead of squaring off its corners.
    <Card className="flex flex-col overflow-hidden">
      {/*
       * Band 1 — white header. min-h keeps a row of tiles aligned when one
       * label wraps to two lines and its neighbours do not; without it the
       * numerals below start at different heights and the row reads as broken.
       */}
      <div className="flex min-h-[52px] items-center gap-2.5 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3">
        {icon ? <IconTile tone={tileTone}>{icon}</IconTile> : null}
        {/*
         * Wraps rather than truncates. Four tiles across a 375px screen leaves
         * ~110px of label, which turned every one of these into "Open requi…" —
         * a two-line label costs a few pixels of height and stays readable.
         */}
        <p className="min-w-0 flex-1 text-[15px] leading-snug font-semibold text-balance text-[var(--text-primary)]">
          {label}
        </p>
      </div>

      {/*
       * Band 2 — the grey well holding the number. The tonal step is what
       * makes the figure read as the card's payload rather than as the first
       * line of its body text, and it is the reference's most load-bearing
       * device: every KPI, table and list there sits in one of these.
       */}
      {/*
       * Two bands, not three. The old footer strip was a separate white band
       * under the grey well, which made every tile read as three stacked
       * segments — more dividing lines than content. Its text now lives inside
       * the well with the number it qualifies, which is where it belonged: the
       * sublabel is a caption on the figure, not a section of its own.
       */}
      <div className="flex flex-1 flex-col justify-end gap-2 bg-[var(--bg-surface-2)] px-4 py-3.5">
        <div className="flex items-end justify-between gap-3">
          {/*
           * The numeral owns the row and the sparkline takes what is left. Both
           * were previously fixed-width in a flex row that could not shrink, so
           * at narrow widths the line drew straight through the number and out
           * past the card edge.
           */}
          <p className="numeral shrink-0 text-[32px] leading-none font-semibold text-[var(--text-primary)]">
            {value}
          </p>
          {spark ? (
            <Sparkline
              className="min-w-0 flex-1"
              data={spark}
              tone={
                tone === 'danger'
                  ? 'danger'
                  : tone === 'ok' || tone === 'verified'
                    ? 'ok'
                    : 'neutral'
              }
            />
          ) : null}
        </div>

        {delta || sublabel || baseline ? (
          /*
           * flex-wrap, not truncate. The sublabel is the sentence that says
           * what the delta is measured against ("vs 6.8% org baseline"), and
           * clipping it mid-word left the number without its qualifier —
           * which is worse than the extra line it costs.
           */
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
              {delta ? (
                <Delta
                  value={delta.value}
                  good={delta.good}
                  direction={delta.direction ?? (delta.good ? 'up' : 'down')}
                />
              ) : null}
              {sublabel ? (
                <span className="min-w-0 text-xs leading-snug text-[var(--text-tertiary)]">
                  {sublabel}
                </span>
              ) : null}
            </div>
            {baseline ? (
              <span className="tabular shrink-0 text-xs text-[var(--text-tertiary)]">
                {baseline}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------- CardSection */

/**
 * The grey well used inside a card for its content area — the reference's
 * pattern of a white titled header over a tonally recessed body.
 *
 * Exists so pages stop hand-rolling `bg-[var(--bg-surface-2)]` wrappers and
 * drifting apart on padding.
 */
export function CardSection({
  children,
  className,
  inset = true,
}: {
  children: ReactNode
  className?: string
  /** Set false for a body that should stay white, e.g. behind a chart. */
  inset?: boolean
}) {
  return (
    <div className={cn(inset && 'bg-[var(--bg-surface-2)]', 'px-4 py-3.5', className)}>
      {children}
    </div>
  )
}

/* -------------------------------------------------------------- SectionTitle */

/**
 * A heading that sits on the canvas above a group of cards — the reference's
 * "Performance" and "Campaigns that need you".
 *
 * Deliberately not a CardHeader: it labels a *set* of boxes, and putting it
 * inside one of them would make the others look subordinate to the first.
 */
export function SectionTitle({
  children,
  actions,
  className,
}: {
  children: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-center justify-between gap-4 pt-1', className)}>
      <h2 className="text-[17px] font-semibold tracking-tight text-[var(--text-primary)]">
        {children}
      </h2>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/* ------------------------------------------------------------------- Skeleton */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-shimmer rounded-lg', className)} aria-hidden="true" />
}

export function TableSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="p-4" role="status" aria-label="Loading data">
      <div className="space-y-2.5">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-3">
            {Array.from({ length: cols }).map((_, c) => (
              <Skeleton key={c} className={cn('h-7', c === 0 ? 'w-[28%]' : 'flex-1')} />
            ))}
          </div>
        ))}
      </div>
      <span className="sr-only">Loading…</span>
    </div>
  )
}

/* ----------------------------------------------------------------- EmptyState */

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon ? (
        <div className="mb-3 flex size-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] text-[var(--text-tertiary)]">
          {icon}
        </div>
      ) : null}
      <p className="text-sm font-semibold text-[var(--text-primary)]">{title}</p>
      {description ? (
        <p className="mt-1 max-w-sm text-xs leading-relaxed text-[var(--text-tertiary)]">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

/* --------------------------------------------------------------- SectionLabel */

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[10px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
      {children}
    </p>
  )
}

/* --------------------------------------------------------------------- Meter */

export function Meter({
  value,
  tone = 'accent',
  label,
}: {
  value: number
  tone?: BadgeTone
  label?: string
}) {
  const fill: Record<BadgeTone, string> = {
    neutral: 'bg-[var(--neutral-solid)]',
    accent: 'bg-[var(--accent)]',
    ok: 'bg-[var(--ok-solid)]',
    warn: 'bg-[var(--warn-solid)]',
    danger: 'bg-[var(--danger-solid)]',
    info: 'bg-[var(--info-solid)]',
    verified: 'bg-[var(--verified)]',
    asserted: 'bg-[var(--asserted)]',
  }
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--chart-track)]"
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? 'Progress'}
    >
      <div
        className={cn('h-full rounded-full transition-[width] duration-300', fill[tone])}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  )
}

/* ---------------------------------------------------------------- Segmented */

/**
 * Pill segmented control — the Today / Yesterday / This week pattern. Uses
 * radiogroup semantics so it is announced as a single choice, not N buttons.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
  size = 'md',
  label,
}: {
  options: { id: T; label: string; /** Red dot marking a tab with items needing action. */ dot?: boolean }[]
  value: T
  onChange: (id: T) => void
  className?: string
  size?: 'sm' | 'md'
  /** Names the choice being made, e.g. "Filter campaigns". */
  label?: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      /*
       * An inset track holding the pills. Without it the options read as three
       * unrelated links rather than one choice — the reference's tabs get their
       * grouping from sitting inside a filter bar, which these do not have.
       */
      className={cn(
        'inline-flex items-center gap-0.5 rounded-xl bg-[var(--bg-surface-3)] p-1',
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.id === value
        return (
          <button
            key={opt.id}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.id)}
            className={cn(
              'inline-flex cursor-pointer items-center gap-1.5 rounded-[10px] font-medium whitespace-nowrap',
              'transition-colors duration-200',
              size === 'sm' ? 'h-6 px-2.5 text-[11px]' : 'h-7 px-3 text-[13px]',
              /*
               * Active is a raised white pill on the bare canvas, as in the
               * reference — not a filled accent. These tabs filter a view; the
               * accent is reserved for controls that commit to something, and
               * a blue "All campaigns" outranked the actual page CTA beside it.
               */
              active
                ? 'bg-[var(--bg-surface)] font-semibold text-[var(--text-primary)] shadow-[var(--shadow-sm)] ring-1 ring-[var(--border-subtle)]'
                : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
            )}
          >
            {opt.label}
            {opt.dot ? (
              <span
                className="size-1.5 shrink-0 rounded-full bg-[var(--danger-solid)]"
                aria-hidden="true"
              />
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------- Toolbar */

/** Search input styled to match the reference's rounded, inset fields. */
export function SearchInput({
  value,
  onChange,
  placeholder,
  label,
  icon,
  className,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  label: string
  icon?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('relative', className)}>
      {icon ? (
        <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-[var(--text-tertiary)]">
          {icon}
        </span>
      ) : null}
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={label}
        className={cn(
          'h-9 w-full rounded-[10px] border border-[var(--border-default)] bg-[var(--bg-surface)]',
          'pr-3 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]',
          'transition-colors duration-200 outline-none',
          'focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/15',
          icon ? 'pl-8' : 'pl-3',
        )}
      />
    </div>
  )
}

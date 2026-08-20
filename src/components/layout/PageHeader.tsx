import { useEffect, useRef, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { IconTile, type TileTone } from '@/components/ui/primitives'

export function PageHeader({
  title,
  description,
  actions,
  meta,
  className,
  greeting,
  eyebrow,
  subject,
  titleSuffix,
  icon,
  tone,
  below,
  sticky = true,
}: {
  title: string
  description?: string
  actions?: ReactNode
  meta?: ReactNode
  className?: string
  /** Renders the title at display size, as on the reference's overview page. */
  greeting?: boolean
  /**
   * The tile beside the title, as on the reference's "Overview" header. Gives
   * each page a fixed visual identity that matches its icon in the sidebar, so
   * arriving somewhere confirms where you clicked.
   */
  icon?: ReactNode
  tone?: TileTone
  /**
   * Keeps the title and its actions pinned while the page body scrolls. On by
   * default: the primary action for a screen should not be something you have
   * to scroll back up to reach.
   */
  sticky?: boolean
  /**
   * Small label above the title, for pages whose title is a record name rather
   * than the name of the screen — it says what you are looking at when the
   * title only says which one.
   */
  eyebrow?: string
  /**
   * The record this screen is about, rendered after the title as
   * "Test plan / Auto-approve overtime under 4 hours per week". Use when the
   * title names the screen but not which instance of it you are looking at.
   */
  subject?: string
  /**
   * Rendered inline after the title — for a record's own identifier, which
   * belongs beside the name it identifies rather than down in `meta` among
   * status chips. It is part of what the thing is called, not a property of it.
   */
  titleSuffix?: ReactNode
  /**
   * Full-width content below the title row, inside the sticky region — for the
   * STLC stepper, which is wayfinding for a multi-step journey and so has to
   * stay on screen while the body scrolls.
   *
   * Outside the title column rather than in `meta`: it spans the header's whole
   * width, and nesting it beside the title would squeeze it against the
   * actions on the right.
   */
  below?: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)

  /*
   * Publish the header's real height so `PageBody fill` can size itself
   * against it. Observed rather than measured once: the header grows when the
   * title wraps, which happens on narrow viewports and long record names.
   *
   * Written to the scroll container rather than :root so two headers can never
   * fight over one global value.
   */
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const target = el.closest('main') ?? document.documentElement
    // offsetHeight, not contentRect: the header's vertical padding is part of
    // the space the body has to subtract, and contentRect excludes it.
    const ro = new ResizeObserver(() => {
      target.style.setProperty('--page-header-h', `${el.offsetHeight}px`)
    })
    ro.observe(el)
    return () => {
      ro.disconnect()
      target.style.removeProperty('--page-header-h')
    }
  }, [])

  return (
    /*
     * No extra top padding on mobile any more: the nav trigger moved into the
     * shell's top bar, so nothing floats over this and the old pt-16 was
     * reserving space for a button that is no longer there.
     */
    <div
      ref={ref}
      className={cn(
        // pb-3, not pb-4: without a rule under it the header is separated from
        // the body by space alone, and the old padding pair left a gap wide
        // enough to read as a missing element.
        'px-4 pt-5 pb-3 sm:px-6',
        /*
         * Sticky needs an opaque background, otherwise the body scrolls
         * visibly underneath the title.
         *
         * No bottom rule. This used to be the page's top edge, but the shell
         * now draws its own header line directly above — two rules a title's
         * height apart read as a stray empty band rather than a separator.
         */
        sticky && 'sticky top-0 z-[var(--z-sticky)] bg-[var(--bg-base)]',
        className,
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-2.5">
          {icon ? <IconTile tone={tone} className="mt-0.5 size-8">{icon}</IconTile> : null}
          <div className="min-w-0">
          {eyebrow ? (
            <p className="mb-1 text-[11px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              {eyebrow}
            </p>
          ) : null}
          <h1
            className={cn(
              // inline-flex with baseline alignment so a suffix chip sits on
              // the title's baseline rather than centred against its line box.
              'flex flex-wrap items-baseline gap-x-2 font-semibold tracking-tight text-[var(--text-primary)]',
              greeting ? 'text-[22px]' : 'text-[20px]',
            )}
          >
            <span className="min-w-0">{title}</span>
            {titleSuffix ? <span className="shrink-0">{titleSuffix}</span> : null}
            {/*
             * The subject the screen is about, shown after the screen's own
             * name: "Test plan / Auto-approve overtime…". Kept lighter than the
             * title so it reads as a qualifier rather than a second heading.
             */}
            {subject ? (
              <>
                {/*
                 * Real spaces around the slash, not margin. Margin separates it
                 * visually but leaves the accessible name as
                 * "Test plan/Auto-approve…" — one run-on token to a screen
                 * reader and to anything reading textContent.
                 */}
                <span className="font-normal text-[var(--text-tertiary)]">{' / '}</span>
                <span className="font-medium text-[var(--text-secondary)]">{subject}</span>
              </>
            ) : null}
          </h1>
          {description ? (
            <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-[var(--text-secondary)]">
              {description}
            </p>
          ) : null}
          {meta ? <div className="mt-3 flex flex-wrap items-center gap-2">{meta}</div> : null}
          </div>
        </div>
        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
      {/*
       * The gap is a margin on the child, not padding on a wrapper: `below` is
       * a truthy element even when the component inside it renders null, so a
       * wrapper with `mt-4` would leave 16px of empty space behind.
       */}
      {below ? <div className="empty:hidden [&>*]:mt-4">{below}</div> : null}
    </div>
  )
}

export function PageBody({
  children,
  className,
  fill,
}: {
  children: ReactNode
  className?: string
  /**
   * Makes the body occupy exactly the space left under the sticky header,
   * instead of growing with its content — for master-detail screens whose
   * columns scroll independently.
   *
   * `100dvh` minus the header's real height, read from a CSS variable the
   * header sets on itself. A hand-measured constant was wrong as soon as the
   * title wrapped to two lines, which is exactly what happens on a narrow
   * laptop with a long requirement name in the subject.
   */
  fill?: boolean
}) {
  return (
    <div
      className={cn(
        'px-4 pt-4 pb-6 sm:px-6',
        /*
         * max-h rather than h: the box still shrinks for short content, and
         * capping it means the vertical padding is absorbed inside the limit
         * instead of adding to it. With `h-` the pb-6 pushed 24px past the
         * viewport and the document scrolled by exactly that much.
         */
        fill &&
          'box-border flex h-[calc(100dvh-var(--page-header-h,0px))] min-h-0 flex-col overflow-hidden',
        className,
      )}
    >
      {children}
    </div>
  )
}

/**
 * The filter row that sits between a page header and its content — the
 * reference's "Last 30 days · All campaigns · Active · Needs action" strip.
 *
 * Separate from PageHeader because filters scroll away with the content they
 * filter, while the title and its actions stay pinned. Sticking both would
 * cost a third of the viewport on a laptop.
 */
export function PageFilters({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        // pt-3 matches the header's own bottom padding, so the filter strip
        // sits the same distance below the title as the body would.
        'flex flex-wrap items-center gap-2 px-4 pt-3 sm:px-6',
        className,
      )}
    >
      {children}
    </div>
  )
}

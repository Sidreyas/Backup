import { useMemo, useState, type ReactNode } from 'react'
import { ChevronsUpDown, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Column<T> {
  id: string
  header: ReactNode
  /** Value used for sorting; omit to make the column unsortable. */
  sortValue?: (row: T) => string | number
  cell: (row: T) => ReactNode
  /** Tailwind width/alignment classes for both th and td. */
  className?: string
  align?: 'left' | 'right' | 'center'
  /**
   * Hide below `lg`. A seven-column table at 390px is unreadable, so secondary
   * columns drop out rather than being squeezed into two characters each.
   * The card layout below `md` shows them again as labelled rows, so nothing
   * is actually lost — only deferred.
   */
  secondary?: boolean
  /** Marks the column that titles a row in the stacked card layout. */
  primary?: boolean
}

type SortDir = 'asc' | 'desc'

export function DataTable<T>({
  rows,
  columns,
  getRowId,
  onRowClick,
  selectedId,
  emptyState,
  initialSort,
  stickyHeader = true,
  selectable = false,
}: {
  rows: T[]
  columns: Column<T>[]
  getRowId: (row: T) => string
  onRowClick?: (row: T) => void
  selectedId?: string | null
  emptyState?: ReactNode
  initialSort?: { columnId: string; dir: SortDir }
  stickyHeader?: boolean
  /** Adds a leading checkbox column, as in the reference's SLA table. */
  selectable?: boolean
}) {
  const [sort, setSort] = useState<{ columnId: string; dir: SortDir } | null>(initialSort ?? null)
  const [checked, setChecked] = useState<Set<string>>(new Set())

  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.id === sort.columnId)
    if (!col?.sortValue) return rows
    const get = col.sortValue
    return [...rows].sort((a, b) => {
      const av = get(a)
      const bv = get(b)
      if (av === bv) return 0
      const cmp = av < bv ? -1 : 1
      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [rows, columns, sort])

  function toggleSort(col: Column<T>) {
    if (!col.sortValue) return
    setSort((prev) =>
      prev?.columnId === col.id
        ? { columnId: col.id, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { columnId: col.id, dir: 'asc' },
    )
  }

  function toggleRow(id: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const allChecked = sorted.length > 0 && sorted.every((r) => checked.has(getRowId(r)))

  if (rows.length === 0 && emptyState) {
    return <>{emptyState}</>
  }

  const alignClass = (align?: Column<T>['align']) =>
    align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'

  const checkboxClass =
    'size-4 cursor-pointer rounded border-[var(--border-strong)] accent-[var(--accent)]'

  const primaryCol = columns.find((c) => c.primary) ?? columns[0]

  return (
    <>
      {/*
       * Table layout from `md` up.
       *
       * No overflow-x wrapper: it reserved a scrollbar gutter on every table
       * even though none of them overflowed, and a table you scroll sideways
       * is a table you cannot read. Columns marked `secondary` drop out on
       * narrow viewports instead, and below `md` the whole thing becomes cards.
       */}
      <div className="hidden md:block">
        <table className="w-full border-collapse text-[13px]">
          <thead
            className={cn(
              /*
               * A grey band, as in the reference: the tonal step is what marks
               * the column names as chrome rather than as a first data row.
               *
               * This works here only because the toolbar above it is white —
               * two filled bars stacked would read as competing, with the
               * column names lost between them. If a filled toolbar is ever
               * added above a table, this band has to go back to white.
               */
              'bg-[var(--bg-surface-2)]',
              stickyHeader && 'sticky top-0 z-[var(--z-base)]',
            )}
          >
            <tr>
              {selectable ? (
                <th scope="col" className="w-10 border-b border-[var(--border-default)] px-3 py-2">
                  <input
                    type="checkbox"
                    className={checkboxClass}
                    checked={allChecked}
                    onChange={() =>
                      setChecked(allChecked ? new Set() : new Set(sorted.map(getRowId)))
                    }
                    aria-label={allChecked ? 'Deselect all rows' : 'Select all rows'}
                  />
                </th>
              ) : null}
              {columns.map((col) => {
                const isSorted = sort?.columnId === col.id
                const ariaSort = isSorted
                  ? sort.dir === 'asc'
                    ? 'ascending'
                    : 'descending'
                  : 'none'
                return (
                  <th
                    key={col.id}
                    scope="col"
                    aria-sort={col.sortValue ? ariaSort : undefined}
                    className={cn(
                      'border-b border-[var(--border-default)] px-3 py-2',
                      'text-[11px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase',
                      'whitespace-nowrap',
                      alignClass(col.align),
                      col.secondary && 'hidden lg:table-cell',
                      col.className,
                    )}
                  >
                    {col.sortValue ? (
                      <button
                        onClick={() => toggleSort(col)}
                        className={cn(
                          'group/sort inline-flex cursor-pointer items-center gap-1 rounded',
                          'transition-colors duration-200 hover:text-[var(--text-primary)]',
                          col.align === 'right' && 'flex-row-reverse',
                          isSorted && 'text-[var(--text-primary)]',
                        )}
                      >
                        {col.header}
                        {/*
                         * The sort arrow appears on hover or when the column is
                         * sorted. A permanent double-chevron on every heading
                         * put seven pieces of chrome above the data and made the
                         * one column that IS sorted harder to pick out.
                         */}
                        <span
                          className={cn(
                            'transition-opacity duration-200',
                            isSorted
                              ? 'opacity-100'
                              : 'opacity-0 group-hover/sort:opacity-60 group-focus-visible/sort:opacity-60',
                          )}
                          aria-hidden="true"
                        >
                          {isSorted ? (
                            sort.dir === 'asc' ? (
                              <ChevronUp className="size-3" />
                            ) : (
                              <ChevronDown className="size-3" />
                            )
                          ) : (
                            <ChevronsUpDown className="size-3" />
                          )}
                        </span>
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const id = getRowId(row)
              const selected = selectedId === id
              const isChecked = checked.has(id)
              const clickable = Boolean(onRowClick)
              return (
                <tr
                  key={id}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            onRowClick(row)
                          }
                        }
                      : undefined
                  }
                  tabIndex={clickable ? 0 : undefined}
                  role={clickable ? 'button' : undefined}
                  aria-current={selected || undefined}
                  className={cn(
                    'group/row border-b border-[var(--border-subtle)] last:border-b-0',
                    'transition-colors duration-150',
                    clickable &&
                      'cursor-pointer hover:bg-[var(--bg-hover)] focus-visible:bg-[var(--bg-hover)] focus-visible:outline-none',
                    /*
                     * Selection is an accent edge plus a tint, not a grey fill.
                     * The old --bg-surface-2 fill was within a shade of hover,
                     * so a selected row and a hovered row looked identical.
                     */
                    (selected || isChecked) &&
                      'bg-[var(--accent-subtle)] shadow-[inset_2px_0_0_0_var(--accent)]',
                  )}
                >
                  {selectable ? (
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        className={checkboxClass}
                        checked={isChecked}
                        onChange={() => toggleRow(id)}
                        aria-label={`Select row ${id}`}
                      />
                    </td>
                  ) : null}
                  {columns.map((col) => (
                    <td
                      key={col.id}
                      className={cn(
                        'px-3 py-2.5 align-middle text-[var(--text-secondary)]',
                        alignClass(col.align),
                        col.secondary && 'hidden lg:table-cell',
                        col.className,
                      )}
                    >
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/*
       * Stacked cards below `md`.
       *
       * A table squeezed into 390px forces a horizontal scroll that hides the
       * columns which decide whether a row matters. Each row becomes a card
       * titled by its primary column, with the rest as labelled pairs — the
       * same information, in an order a narrow screen can actually present.
       */}
      <ul className="divide-y divide-[var(--border-subtle)] md:hidden">
        {sorted.map((row) => {
          const id = getRowId(row)
          const selected = selectedId === id
          const clickable = Boolean(onRowClick)
          const rest = columns.filter((c) => c.id !== primaryCol?.id)
          return (
            <li key={id}>
              <div
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          onRowClick(row)
                        }
                      }
                    : undefined
                }
                tabIndex={clickable ? 0 : undefined}
                role={clickable ? 'button' : undefined}
                aria-current={selected || undefined}
                className={cn(
                  'block w-full p-3.5 text-left transition-colors duration-150',
                  clickable && 'cursor-pointer hover:bg-[var(--bg-hover)]',
                  selected && 'bg-[var(--accent-subtle)] shadow-[inset_2px_0_0_0_var(--accent)]',
                )}
              >
                {primaryCol ? (
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">
                    {primaryCol.cell(row)}
                  </div>
                ) : null}
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {rest.map((col) => (
                    <div key={col.id} className="min-w-0">
                      <dt className="text-[10px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
                        {col.header}
                      </dt>
                      <dd className="mt-0.5 truncate text-xs text-[var(--text-secondary)]">
                        {col.cell(row)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </li>
          )
        })}
      </ul>
    </>
  )
}

/** Circular initials avatar used in assignee/owner cells. */
export function Avatar({ name, className }: { name: string; className?: string }) {
  const initials = name
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')

  return (
    <span
      className={cn(
        'flex size-6 shrink-0 items-center justify-center rounded-full',
        'border border-[var(--border-subtle)] bg-[var(--bg-surface-3)]',
        'text-[10px] font-semibold text-[var(--text-secondary)]',
        className,
      )}
      aria-hidden="true"
    >
      {initials}
    </span>
  )
}

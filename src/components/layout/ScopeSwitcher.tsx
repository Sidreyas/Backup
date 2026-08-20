import { useEffect, useRef, useState } from 'react'
import { Building2, Check, ChevronsUpDown, FolderKanban, Pencil, Plus } from 'lucide-react'
import { cn, humanize } from '@/lib/utils'
import { useScope } from '@/lib/workspace'
import { Badge } from '@/components/ui/primitives'
import type { ProjectStatus } from '@/lib/types'

/**
 * Inline name editor for a menu row.
 *
 * Editing happens in place rather than in a dialog: the name is right there,
 * and a modal to change one field would put a scrim over the list you are
 * using to decide which name to change.
 *
 * Enter commits, Escape reverts, and blur commits — blur-cancels loses work
 * for anyone who clicks away expecting a save, which is the more common habit.
 */
function NameEditor({
  value,
  onCommit,
  onCancel,
  label,
}: {
  value: string
  onCommit: (next: string) => void
  onCancel: () => void
  label: string
}) {
  const [draft, setDraft] = useState(value)
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // Select the whole name: renaming usually means replacing, and starting
    // with a caret at the end makes you clear it by hand first.
    ref.current?.focus()
    ref.current?.select()
  }, [])

  const commit = () => {
    const next = draft.trim()
    if (next && next !== value) onCommit(next)
    onCancel()
  }

  return (
    <input
      ref={ref}
      value={draft}
      aria-label={label}
      onChange={(e) => setDraft(e.target.value)}
      // The row behind this is a menuitem; without stopPropagation a click to
      // place the caret would select the row and close the menu.
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Enter') {
          e.preventDefault()
          commit()
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
      onBlur={commit}
      className={cn(
        'w-full rounded-md border border-[var(--accent)] bg-[var(--bg-surface)] px-1.5 py-0.5',
        'text-[13px] font-semibold text-[var(--text-primary)] outline-none',
        'ring-2 ring-[var(--accent)]/15',
      )}
    />
  )
}

const STATUS_TONE: Record<ProjectStatus, 'ok' | 'info' | 'warn' | 'neutral'> = {
  active: 'ok',
  planning: 'info',
  paused: 'warn',
  archived: 'neutral',
}

/**
 * Combined workspace + project switcher. Both live in one popover because the
 * pair is a single mental unit — "where am I working" — and because a project
 * id is only meaningful within its workspace.
 */
/** Preferred height; the menu shrinks below this when space is tight. */
const MENU_MAX_HEIGHT = 420
/** Breathing room kept between the menu and the viewport edge. */
const VIEWPORT_MARGIN = 16

export function ScopeSwitcher({
  collapsed,
  variant = 'rail',
}: {
  collapsed?: boolean
  /**
   * `rail` is the full-width sidebar block. `bar` is the compact form for the
   * top bar, where the control sits in a row of its own height and must not
   * stretch to fill the space beside it.
   */
  variant?: 'rail' | 'bar'
}) {
  const { workspaces, workspace, projects, project, setWorkspace, setProject, renameWorkspace, renameProject } =
    useScope()
  const [open, setOpen] = useState(false)
  /** Id of the row being renamed, or null. One at a time, by construction. */
  const [editingId, setEditingId] = useState<string | null>(null)
  const [placement, setPlacement] = useState<{ dropUp: boolean; maxHeight: number }>({
    dropUp: false,
    maxHeight: MENU_MAX_HEIGHT,
  })
  const rootRef = useRef<HTMLDivElement>(null)

  /*
   * Decide direction AND height from the space actually available at open
   * time. A fixed direction was what put the menu above a trigger that now
   * sits near the top of the sidebar; a CSS-only height cap could not account
   * for the trigger's offset, so the menu still overran the bottom edge on a
   * short viewport.
   */
  useEffect(() => {
    if (!open) return
    const trigger = rootRef.current?.querySelector('button')
    if (!trigger) return

    const measure = () => {
      const rect = trigger.getBoundingClientRect()
      const below = window.innerHeight - rect.bottom - VIEWPORT_MARGIN
      const above = rect.top - VIEWPORT_MARGIN
      const dropUp = below < MENU_MAX_HEIGHT && above > below
      setPlacement({
        dropUp,
        maxHeight: Math.max(180, Math.min(MENU_MAX_HEIGHT, dropUp ? above : below)),
      })
    }

    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [open])

  // Never leave an editor mounted behind a closed menu: reopening would
  // otherwise land straight back in a half-finished rename.
  useEffect(() => {
    if (!open) setEditingId(null)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      // While renaming, Escape belongs to the editor — it cancels the edit and
      // stops there. Closing the whole menu would discard the edit and the
      // menu in one keystroke, when only the first was asked for. The editor
      // stops propagation, so this only runs when nothing is being edited.
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (collapsed) {
    return (
      <div className="flex justify-center" ref={rootRef}>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex size-9 cursor-pointer items-center justify-center rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface-2)] text-[11px] font-semibold text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-hover)]"
          aria-label={`Workspace ${workspace.name}, project ${project?.name ?? 'none'}. Change scope`}
        >
          {project?.key.slice(0, 2) ?? 'W'}
        </button>
      </div>
    )
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        // Names the action, not just the current value — otherwise the control
        // announces "Workday HCM" without saying it can be changed.
        aria-label={`Workspace ${workspace.name}, project ${project?.name ?? 'none'}. Change scope`}
        className={cn(
          'flex cursor-pointer items-center text-left transition-colors',
          /*
           * In the bar the control is sized by its content and carries no fill
           * — a bordered box here would read as a second search field beside
           * the real one. In the rail it stays the full-width tile.
           */
          variant === 'bar'
            ? cn(
                'max-w-[280px] gap-2 rounded-lg px-2 py-1.5 hover:bg-[var(--bg-hover)]',
                open && 'bg-[var(--bg-hover)]',
              )
            : cn(
                'w-full gap-2.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-2',
                'hover:bg-[var(--bg-hover)]',
                open && 'border-[var(--border-strong)]',
              ),
        )}
      >
        {/* --brand rather than --accent: the tile identifies the workspace,
            it is not a selected or actionable thing. */}
        <span
          className={cn(
            'flex shrink-0 items-center justify-center bg-[var(--brand)] font-semibold text-[var(--brand-on)]',
            variant === 'bar'
              ? 'size-6 rounded-md text-[10px]'
              : 'size-8 rounded-lg text-[11px]',
          )}
          aria-hidden="true"
        >
          {project?.key.slice(0, 2) ?? 'W'}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              'block truncate font-bold text-[var(--text-primary)]',
              variant === 'bar' ? 'text-[13px] leading-tight' : 'text-[13px]',
            )}
          >
            {project?.name ?? 'No project'}
          </span>
          {/* The workspace line is the second half of "where am I working".
              In the bar it stays, but at a size that keeps the control one
              row tall rather than two. */}
          <span
            className={cn(
              'block truncate font-medium text-[var(--text-tertiary)]',
              variant === 'bar' ? 'text-[10px] leading-tight' : 'text-[11px]',
            )}
          >
            {workspace.name}
          </span>
        </span>
        <ChevronsUpDown
          className="size-3.5 shrink-0 text-[var(--text-tertiary)]"
          aria-hidden="true"
        />
      </button>

      {open ? (
        <div
          role="menu"
          // Height is measured, not guessed: a long project list scrolls inside
          // the menu instead of running off the edge of the screen.
          style={{ maxHeight: placement.maxHeight }}
          className={cn(
            'animate-scale-in absolute left-0 z-[var(--z-dropdown)] w-[268px]',
            'overflow-y-auto rounded-xl border border-[var(--border-default)]',
            'bg-[var(--bg-surface)] shadow-[var(--shadow-lg)]',
            // The switcher sits near the top of the sidebar, so the menu drops
            // downward. It flips up only when there genuinely is not room below
            // — and never in the top bar, where "above" is off-screen.
            placement.dropUp && variant !== 'bar' ? 'bottom-full mb-2' : 'top-full mt-2',
          )}
        >
          {/* Workspaces */}
          <div className="border-b border-[var(--border-subtle)] p-1.5">
            <p className="px-2 py-1.5 text-[10px] font-bold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Workspace
            </p>
            {workspaces.map((ws) => {
              const active = ws.id === workspace.id
              const editing = editingId === ws.id
              return (
                /*
                 * A row, not a button: the rename control is itself a button
                 * and a button may not contain another. The selecting element
                 * inside carries the menuitemradio role, so the semantics are
                 * unchanged from the outside.
                 */
                <div
                  key={ws.id}
                  className={cn(
                    'group flex items-center gap-2 rounded-lg px-2 py-1.5',
                    !editing && 'transition-colors hover:bg-[var(--bg-hover)]',
                  )}
                >
                  <Building2
                    className="size-3.5 shrink-0 text-[var(--text-tertiary)]"
                    aria-hidden="true"
                  />

                  {editing ? (
                    <div className="min-w-0 flex-1">
                      <NameEditor
                        value={ws.name}
                        label={`Rename workspace ${ws.name}`}
                        onCommit={(next) => renameWorkspace(ws.id, next)}
                        onCancel={() => setEditingId(null)}
                      />
                    </div>
                  ) : (
                    <>
                      <button
                        role="menuitemradio"
                        aria-checked={active}
                        onClick={() => setWorkspace(ws.id)}
                        className="min-w-0 flex-1 cursor-pointer text-left"
                      >
                        <span className="block truncate text-[13px] font-semibold text-[var(--text-primary)]">
                          {ws.name}
                        </span>
                        <span className="block truncate text-[10px] text-[var(--text-tertiary)]">
                          {ws.compliance.length ? ws.compliance.join(' · ') : 'No compliance regime'}{' '}
                          · {ws.memberCount} members
                        </span>
                      </button>

                      {/*
                       * Visible on hover and whenever focused, so the control is
                       * reachable by keyboard — hover-only would hide it from
                       * anyone tabbing through the menu.
                       */}
                      <button
                        onClick={() => setEditingId(ws.id)}
                        aria-label={`Rename ${ws.name}`}
                        className={cn(
                          'shrink-0 cursor-pointer rounded p-1 text-[var(--text-tertiary)] opacity-0',
                          'transition-[opacity,color] group-hover:opacity-100 focus-visible:opacity-100',
                          'hover:bg-[var(--bg-active)] hover:text-[var(--text-primary)]',
                        )}
                      >
                        <Pencil className="size-3" aria-hidden="true" />
                      </button>

                      {active ? (
                        <Check
                          className="size-3.5 shrink-0 text-[var(--text-primary)]"
                          aria-hidden="true"
                        />
                      ) : null}
                    </>
                  )}
                </div>
              )
            })}
          </div>

          {/* Projects in the active workspace */}
          <div className="p-1.5">
            <p className="px-2 py-1.5 text-[10px] font-bold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Projects in {workspace.name}
            </p>
            {projects.length === 0 ? (
              <p className="px-2 py-2 text-xs text-[var(--text-tertiary)]">
                No projects yet in this workspace.
              </p>
            ) : (
              projects.map((pj) => {
                const active = pj.id === project?.id
                const editing = editingId === pj.id
                return (
                  <div
                    key={pj.id}
                    className={cn(
                      'group flex items-center gap-2 rounded-lg px-2 py-1.5',
                      !editing && 'transition-colors hover:bg-[var(--bg-hover)]',
                      active && 'bg-[var(--accent-subtle)]',
                    )}
                  >
                    <FolderKanban
                      className="size-3.5 shrink-0 text-[var(--text-tertiary)]"
                      aria-hidden="true"
                    />

                    {editing ? (
                      <div className="min-w-0 flex-1">
                        <NameEditor
                          value={pj.name}
                          label={`Rename project ${pj.name}`}
                          onCommit={(next) => renameProject(pj.id, next)}
                          onCancel={() => setEditingId(null)}
                        />
                      </div>
                    ) : (
                      <>
                        <button
                          role="menuitemradio"
                          aria-checked={active}
                          onClick={() => {
                            setProject(pj.id)
                            setOpen(false)
                          }}
                          className="min-w-0 flex-1 cursor-pointer text-left"
                        >
                          <span className="block truncate text-[13px] font-semibold text-[var(--text-primary)]">
                            {pj.name}
                          </span>
                          <span className="block truncate text-[10px] text-[var(--text-tertiary)]">
                            {pj.platform}
                          </span>
                        </button>

                        <button
                          onClick={() => setEditingId(pj.id)}
                          aria-label={`Rename ${pj.name}`}
                          className={cn(
                            'shrink-0 cursor-pointer rounded p-1 text-[var(--text-tertiary)] opacity-0',
                            'transition-[opacity,color] group-hover:opacity-100 focus-visible:opacity-100',
                            'hover:bg-[var(--bg-active)] hover:text-[var(--text-primary)]',
                          )}
                        >
                          <Pencil className="size-3" aria-hidden="true" />
                        </button>

                        <Badge tone={STATUS_TONE[pj.status]} className="shrink-0">
                          {humanize(pj.status)}
                        </Badge>
                      </>
                    )}
                  </div>
                )
              })
            )}
          </div>

          <div className="border-t border-[var(--border-subtle)] p-1.5">
            <button
              role="menuitem"
              className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              <Plus className="size-3.5 shrink-0" aria-hidden="true" />
              New project
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

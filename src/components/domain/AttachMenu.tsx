import { useEffect, useRef, useState } from 'react'
import { FileUp, GitBranch, Link2, Paperclip, Plus, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BrandIcon } from '@/components/domain/BrandIcon'

/** Something pulled into the conversation as grounding. */
export interface Attachment {
  id: string
  kind: 'file' | 'repo' | 'url'
  label: string
  /** Where it came from, shown so provenance is never guessed at. */
  source: string
}

const GIT_PROVIDERS = [
  { id: 'github', name: 'GitHub', hint: 'Repositories, pull requests and CI results' },
  { id: 'gitlab', name: 'GitLab', hint: 'Projects, merge requests and pipelines' },
  { id: 'azure-devops', name: 'Azure DevOps', hint: 'Repos, work items and build results' },
] as const

/**
 * The "+" control in the composer.
 *
 * Attaching something changes what the assistant is grounded in, so each
 * attachment stays visible as a removable chip rather than disappearing into
 * the transcript. An answer that silently drew on a file you forgot you
 * attached is an answer you cannot audit.
 */
export function AttachMenu({
  attachments,
  onAdd,
  disabled,
}: {
  /** Used only to mint stable ids; removal lives on the chips. */
  attachments: Attachment[]
  onAdd: (a: Attachment) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function addRepo(provider: (typeof GIT_PROVIDERS)[number]) {
    onAdd({
      id: `att-${provider.id}-${attachments.length}`,
      kind: 'repo',
      label: 'acme/integration-services',
      source: provider.name,
    })
    setOpen(false)
  }

  return (
    <div className="relative" ref={rootRef}>
      <input
        ref={fileRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          files.forEach((f, i) =>
            onAdd({
              id: `att-file-${Date.now()}-${i}`,
              kind: 'file',
              label: f.name,
              // Named "Uploaded" rather than a path: a local path means nothing
              // to anyone else reading the audit trail later.
              source: 'Uploaded',
            }),
          )
          // Reset so re-picking the same file fires change again.
          e.target.value = ''
          setOpen(false)
        }}
      />

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Attach a file or connect a repository"
        className={cn(
          'flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-lg',
          'text-[var(--text-tertiary)] transition-colors',
          'hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
          'disabled:cursor-not-allowed disabled:opacity-40',
          open && 'bg-[var(--bg-hover)] text-[var(--text-primary)]',
        )}
      >
        <Plus
          className={cn('size-4 transition-transform duration-200', open && 'rotate-45')}
          aria-hidden="true"
        />
      </button>

      {open ? (
        <div
          role="menu"
          className={cn(
            'animate-scale-in absolute bottom-full left-0 z-[var(--z-dropdown)] mb-2 w-[268px]',
            'overflow-hidden rounded-xl border border-[var(--border-default)]',
            'bg-[var(--bg-surface)] shadow-[var(--shadow-lg)]',
          )}
        >
          <div className="p-1.5">
            <button
              role="menuitem"
              onClick={() => fileRef.current?.click()}
              className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-[var(--bg-hover)]"
            >
              <FileUp
                className="size-4 shrink-0 text-[var(--text-tertiary)]"
                aria-hidden="true"
              />
              <span className="min-w-0">
                <span className="block text-[13px] font-medium text-[var(--text-primary)]">
                  Upload files
                </span>
                <span className="block text-[11px] text-[var(--text-tertiary)]">
                  Specs, exports, screenshots
                </span>
              </span>
            </button>

            <button
              role="menuitem"
              onClick={() => {
                onAdd({
                  id: `att-url-${Date.now()}`,
                  kind: 'url',
                  label: 'Confluence — HR Transformation',
                  source: 'Link',
                })
                setOpen(false)
              }}
              className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-[var(--bg-hover)]"
            >
              <Link2 className="size-4 shrink-0 text-[var(--text-tertiary)]" aria-hidden="true" />
              <span className="min-w-0">
                <span className="block text-[13px] font-medium text-[var(--text-primary)]">
                  Paste a link
                </span>
                <span className="block text-[11px] text-[var(--text-tertiary)]">
                  A page from a connected source
                </span>
              </span>
            </button>
          </div>

          <div className="border-t border-[var(--border-subtle)] p-1.5">
            <p className="px-2 py-1 text-[10px] font-semibold tracking-[0.04em] text-[var(--text-tertiary)] uppercase">
              Connect a repository
            </p>
            {GIT_PROVIDERS.map((p) => (
              <button
                key={p.id}
                role="menuitem"
                onClick={() => addRepo(p)}
                className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-[var(--bg-hover)]"
              >
                <BrandIcon name={p.name} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium text-[var(--text-primary)]">
                    {p.name}
                  </span>
                  <span className="block truncate text-[11px] text-[var(--text-tertiary)]">
                    {p.hint}
                  </span>
                </span>
              </button>
            ))}
          </div>

          <div className="border-t border-[var(--border-subtle)] px-3 py-2">
            {/* Says where attachments end up. Grounding that appears in an
                answer without a trail is the thing this product exists to
                prevent, so the composer says so at the point of attaching. */}
            <p className="text-[10px] leading-snug text-[var(--text-tertiary)]">
              Anything attached is recorded as grounding for this thread and cited in the answers
              that use it.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  )
}

/** The chips shown above the composer for whatever is currently attached. */
export function AttachmentChips({
  attachments,
  onRemove,
}: {
  attachments: Attachment[]
  onRemove: (id: string) => void
}) {
  if (attachments.length === 0) return null

  return (
    <ul className="mb-2 flex flex-wrap gap-1.5">
      {attachments.map((a) => (
        <li key={a.id}>
          <span
            className={cn(
              'flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)]',
              'bg-[var(--bg-surface-2)] py-1 pr-1 pl-2 text-[11px]',
            )}
          >
            {a.kind === 'repo' ? (
              <GitBranch
                className="size-3 shrink-0 text-[var(--text-tertiary)]"
                aria-hidden="true"
              />
            ) : (
              <Paperclip
                className="size-3 shrink-0 text-[var(--text-tertiary)]"
                aria-hidden="true"
              />
            )}
            <span className="max-w-[180px] truncate text-[var(--text-primary)]">{a.label}</span>
            <span className="shrink-0 text-[var(--text-tertiary)]">{a.source}</span>
            <button
              onClick={() => onRemove(a.id)}
              aria-label={`Remove ${a.label}`}
              className="flex size-4 shrink-0 cursor-pointer items-center justify-center rounded text-[var(--text-tertiary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          </span>
        </li>
      ))}
    </ul>
  )
}

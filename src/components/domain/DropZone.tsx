import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge, Button, Card, IconTile } from '@/components/ui/primitives'
import type { DocKind } from '@/lib/types'

/**
 * Document kinds Meridian can parse, as shown on the drop target.
 *
 * Defined here rather than in `status.tsx`: this is the only place the labels
 * are rendered, and they describe what may be dropped rather than the state of
 * anything already ingested.
 */
const DOC_KIND_LABEL: Record<DocKind, string> = {
  srs: 'SRS',
  brd: 'BRD',
  frd: 'FRD',
  prd: 'PRD',
  architecture: 'Architecture',
  contract: 'Contract',
  other: 'Other',
}

/** A file the user offered, described well enough to show a pending row for. */
export interface DroppedFile {
  name: string
  sizeLabel: string
}

/**
 * Drop target for ingesting documents.
 *
 * Lives in `domain/` rather than inside a page because the ingestion page it
 * came from was removed — adding data is now something you do from Knowledge
 * Sources, beside the sources it produces.
 */
export function DropZone({ onFiles }: { onFiles: (f: DroppedFile[]) => void }) {
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const toDescriptor = (f: File): DroppedFile => ({
    name: f.name,
    sizeLabel:
      f.size > 1_048_576
        ? `${(f.size / 1_048_576).toFixed(1)} MB`
        : `${Math.max(1, Math.round(f.size / 1024))} KB`,
  })

  return (
    <Card
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        const files = Array.from(e.dataTransfer.files).map(toDescriptor)
        if (files.length) onFiles(files)
      }}
      className={cn(
        'border-dashed transition-colors duration-200',
        over ? 'border-[var(--accent)] bg-[var(--accent-subtle)]' : 'border-[var(--border-default)]',
      )}
    >
      {/*
       * Shorter than the original: on the ingestion page this was the whole
       * screen, but here it sits above a table that is the actual subject of
       * the page, and a full-height target pushed the sources below the fold.
       */}
      <div className="flex flex-col items-center px-6 py-6 text-center">
        <IconTile className="size-9 [&>svg]:size-4">
          <Upload aria-hidden="true" />
        </IconTile>
        <p className="mt-2.5 text-sm font-semibold text-[var(--text-primary)]">
          Drop files here, or browse
        </p>
        <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--text-tertiary)]">
          SRS, BRD, FRD, PRD, architecture notes, contracts and exports. PDF, DOCX, MD, XLSX and CSV
          up to 200 MB each. Meridian records what it could not read rather than failing silently.
        </p>

        <input
          ref={inputRef}
          type="file"
          multiple
          className="sr-only"
          aria-label="Choose files to upload"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []).map(toDescriptor)
            if (files.length) onFiles(files)
            e.target.value = ''
          }}
        />

        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          <Button variant="primary" size="sm" onClick={() => inputRef.current?.click()}>
            Browse files
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              onFiles([
                { name: 'PRD-Absence-2026.pdf', sizeLabel: '2.1 MB' },
                { name: 'FRD-Approval-Routing.docx', sizeLabel: '640 KB' },
              ])
            }
          >
            Use sample documents
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
          {(['srs', 'brd', 'frd', 'prd', 'architecture', 'contract'] as DocKind[]).map((k) => (
            <Badge key={k} tone="neutral">
              {DOC_KIND_LABEL[k]}
            </Badge>
          ))}
        </div>
      </div>
    </Card>
  )
}

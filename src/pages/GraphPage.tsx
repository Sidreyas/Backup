import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Focus,
  GitFork,
  Maximize2,
  Minimize2,
  Minus,
  Plus,
  Search,
  X,
} from 'lucide-react'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SearchInput,
  SectionLabel,
  Skeleton,
} from '@/components/ui/primitives'
import { Drawer, Modal, Tooltip, useToast } from '@/components/ui/overlays'
import { ConfidenceBadge, NODE_KIND_META, NodeKindBadge } from '@/components/domain/status'
import { api } from '@/lib/api'
import { useAsync } from '@/lib/useAsync'
import { useForceLayout, usePanZoom } from '@/lib/useForceLayout'
import { cn, humanize, relativeTime } from '@/lib/utils'
import type { GraphEdge, GraphNode, LinkConfidence, NodeKind } from '@/lib/types'

const VIEW_W = 1100
const VIEW_H = 640

/** Edge styling encodes confidence with BOTH colour and dash pattern. */
const EDGE_STYLE: Record<LinkConfidence, { stroke: string; dash: string; width: number }> = {
  confirmed: { stroke: 'var(--ok-solid)', dash: '0', width: 1.75 },
  high: { stroke: 'var(--info-solid)', dash: '7 3', width: 1.5 },
  medium: { stroke: 'var(--warn-solid)', dash: '4 4', width: 1.5 },
  low: { stroke: 'var(--danger-solid)', dash: '2 4', width: 1.25 },
}

/**
 * The graph canvas and its supporting panels, without a page header. Rendered
 * inside the Knowledge Sources page as one of its two views.
 */
export function GraphView({
  onRegisterFullscreen,
}: {
  onRegisterFullscreen?: (fn: () => void) => void
}) {
  const { data, loading } = useAsync(() => api.getGraph(), [])
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [kindFilter, setKindFilter] = useState<NodeKind | 'all'>('all')
  const [confirmedOnly, setConfirmedOnly] = useState(false)
  const [attentionOpen, setAttentionOpen] = useState(false)
  const svgRef = useRef<SVGSVGElement>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const { transform, reset, zoomBy } = usePanZoom(svgRef)

  /**
   * Expanded rather than fullscreened: the native Fullscreen API always takes
   * over the whole monitor, which is not what is wanted here. A fixed overlay
   * pinned to the viewport fills the browser window instead, so the tab strip
   * and chrome stay visible.
   */
  const toggleFullscreen = useCallback(() => setIsFullscreen((v) => !v), [])

  // Escape exits, matching the affordance a real fullscreen would have had.
  useEffect(() => {
    if (!isFullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsFullscreen(false)
    }
    document.addEventListener('keydown', onKey)
    // The page behind must not scroll while the canvas covers it.
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [isFullscreen])

  // Let the host page drive fullscreen from its own header button
  useEffect(() => {
    onRegisterFullscreen?.(toggleFullscreen)
  }, [onRegisterFullscreen, toggleFullscreen])

  const nodes = useMemo(() => data?.nodes ?? [], [data])
  const edges = useMemo(() => data?.edges ?? [], [data])

  const visibleNodes = useMemo(() => {
    const q = query.trim().toLowerCase()
    return nodes.filter((n) => {
      if (kindFilter !== 'all' && n.kind !== kindFilter) return false
      if (q && !n.label.toLowerCase().includes(q) && !n.provenance.toLowerCase().includes(q))
        return false
      return true
    })
  }, [nodes, query, kindFilter])

  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes])

  const visibleEdges = useMemo(
    () =>
      edges.filter((e) => {
        if (!visibleIds.has(e.from) || !visibleIds.has(e.to)) return false
        if (confirmedOnly && e.confidence !== 'confirmed') return false
        return true
      }),
    [edges, visibleIds, confirmedOnly],
  )

  // Layout runs on the visible subgraph so filtering re-settles the view
  const layout = useForceLayout(visibleNodes, visibleEdges, {
    width: VIEW_W,
    height: VIEW_H,
  })

  const unconfirmedCount = edges.filter((e) => e.confidence !== 'confirmed').length
  const focusId = hovered ?? selected?.id ?? null

  const neighbours = useMemo(() => {
    if (!focusId) return new Set<string>()
    const set = new Set<string>()
    visibleEdges.forEach((e) => {
      if (e.from === focusId) set.add(e.to)
      if (e.to === focusId) set.add(e.from)
    })
    return set
  }, [focusId, visibleEdges])

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  const kindCounts = useMemo(() => {
    const m = new Map<NodeKind, number>()
    nodes.forEach((n) => m.set(n.kind, (m.get(n.kind) ?? 0) + 1))
    return m
  }, [nodes])

  const hasFilters = query.trim() !== '' || kindFilter !== 'all' || confirmedOnly

  return (
    <>
      <div className="space-y-4">
        {/* Canvas */}
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-3 border-b border-[var(--border-subtle)] p-3 lg:flex-row lg:items-center">
            <SearchInput
              className="lg:w-64"
              value={query}
              onChange={setQuery}
              placeholder="Search nodes and provenance…"
              label="Search graph nodes"
              icon={<Search className="size-3.5" aria-hidden="true" />}
            />

            <div className="flex flex-1 flex-wrap items-center gap-2">
              <label className="sr-only" htmlFor="kind-filter">
                Filter by node type
              </label>
              <select
                id="kind-filter"
                value={kindFilter}
                onChange={(e) => setKindFilter(e.target.value as NodeKind | 'all')}
                className="h-9 cursor-pointer rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 text-[13px] text-[var(--text-primary)] outline-none transition-colors duration-200 focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--accent)]/10"
              >
                <option value="all">All node types ({nodes.length})</option>
                {[...kindCounts.entries()].map(([kind, count]) => (
                  <option key={kind} value={kind}>
                    {NODE_KIND_META[kind].label} ({count})
                  </option>
                ))}
              </select>

              <label className="flex cursor-pointer items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={confirmedOnly}
                  onChange={(e) => setConfirmedOnly(e.target.checked)}
                  className="size-4 cursor-pointer accent-[var(--accent)]"
                />
                <span className="text-[13px] text-[var(--text-secondary)]">
                  Confirmed links only
                </span>
              </label>

              {hasFilters ? (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<X className="size-3.5" aria-hidden="true" />}
                  onClick={() => {
                    setQuery('')
                    setKindFilter('all')
                    setConfirmedOnly(false)
                  }}
                >
                  Clear
                </Button>
              ) : null}
            </div>

            <div className="flex items-center gap-1">
              {/* Unconfirmed links are the graph's outstanding human work, so the
                  count sits on the button rather than in a passive stat tile. */}
              <Button
                variant={unconfirmedCount > 0 ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setAttentionOpen(true)}
                icon={
                  unconfirmedCount > 0 ? (
                    <AlertTriangle className="size-3.5 text-[var(--warn)]" aria-hidden="true" />
                  ) : (
                    <CheckCircle2 className="size-3.5 text-[var(--ok)]" aria-hidden="true" />
                  )
                }
              >
                Needs attention
                {unconfirmedCount > 0 ? (
                  <Badge tone="warn" className="ml-1.5">
                    {unconfirmedCount}
                  </Badge>
                ) : null}
              </Button>
              <span className="mx-1 h-5 w-px bg-[var(--border-subtle)]" aria-hidden="true" />
              <Tooltip label="Zoom out">
                <Button
                  variant="secondary"
                  size="icon"
                  onClick={() => zoomBy(0.85)}
                  aria-label="Zoom out"
                >
                  <Minus className="size-3.5" aria-hidden="true" />
                </Button>
              </Tooltip>
              <span className="tabular w-11 text-center text-[11px] text-[var(--text-tertiary)]">
                {Math.round(transform.k * 100)}%
              </span>
              <Tooltip label="Zoom in">
                <Button
                  variant="secondary"
                  size="icon"
                  onClick={() => zoomBy(1.18)}
                  aria-label="Zoom in"
                >
                  <Plus className="size-3.5" aria-hidden="true" />
                </Button>
              </Tooltip>
              <Tooltip label="Reset view">
                <Button variant="secondary" size="icon" onClick={reset} aria-label="Reset view">
                  <Focus className="size-3.5" aria-hidden="true" />
                </Button>
              </Tooltip>
              <Tooltip label={isFullscreen ? 'Exit expanded view' : 'Expand to fill window'}>
                <Button
                  variant="secondary"
                  size="icon"
                  onClick={toggleFullscreen}
                  aria-label={isFullscreen ? 'Exit expanded view' : 'Expand graph to fill window'}
                >
                  {isFullscreen ? (
                    <Minimize2 className="size-3.5" aria-hidden="true" />
                  ) : (
                    <Maximize2 className="size-3.5" aria-hidden="true" />
                  )}
                </Button>
              </Tooltip>
            </div>
          </div>

          {loading ? (
            <div className="p-4">
              <Skeleton className="h-[560px] w-full rounded-xl" />
            </div>
          ) : visibleNodes.length === 0 ? (
            <EmptyState
              icon={<GitFork className="size-5" aria-hidden="true" />}
              title={nodes.length === 0 ? 'No graph yet' : 'No nodes match these filters'}
              description={
                nodes.length === 0
                  ? 'Ingest repositories, requirement documents and platform tenants, then Meridian will assemble the graph from them.'
                  : 'Widen the node type filter or clear the search to see the graph again.'
              }
              action={
                nodes.length === 0 ? (
                  <Link to="/sources">
                    <Button variant="primary">Add data</Button>
                  </Link>
                ) : (
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setQuery('')
                      setKindFilter('all')
                      setConfirmedOnly(false)
                    }}
                  >
                    Clear filters
                  </Button>
                )
              }
            />
          ) : (
            <div
              className={cn(
                'relative bg-[var(--bg-inset)]',
                // Fixed to the viewport, not the monitor: fills the browser
                // window and leaves the browser's own chrome in place.
                isFullscreen &&
                  'animate-fade fixed inset-0 z-[var(--z-modal)] flex flex-col rounded-none',
              )}
            >
              <svg
                ref={svgRef}
                viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
                className={cn(
                  'w-full cursor-grab touch-none active:cursor-grabbing',
                  isFullscreen ? 'h-full min-h-0 flex-1' : 'h-[560px]',
                )}
                preserveAspectRatio="xMidYMid meet"
                role="img"
                aria-label={`Knowledge graph: ${visibleNodes.length} nodes and ${visibleEdges.length} links between requirements, configuration objects, code and reports.`}
              >
                <defs>
                  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
                    <circle cx="1" cy="1" r="1" fill="var(--border-default)" opacity="0.5" />
                  </pattern>
                  <marker
                    id="arrow"
                    viewBox="0 0 10 10"
                    refX="26"
                    refY="5"
                    markerWidth="5"
                    markerHeight="5"
                    orient="auto-start-reverse"
                  >
                    <path d="M0 0 L10 5 L0 10 z" fill="var(--border-strong)" />
                  </marker>
                </defs>
                <rect width={VIEW_W} height={VIEW_H} fill="url(#grid)" />

                <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
                  {visibleEdges.map((edge) => {
                    const from = layout.get(edge.from)
                    const to = layout.get(edge.to)
                    if (!from || !to) return null
                    const style = EDGE_STYLE[edge.confidence]
                    const dim = focusId && edge.from !== focusId && edge.to !== focusId
                    const mx = (from.x + to.x) / 2
                    const my = (from.y + to.y) / 2
                    return (
                      <g
                        key={edge.id}
                        opacity={dim ? 0.1 : 1}
                        className="transition-opacity duration-200"
                      >
                        <line
                          x1={from.x}
                          y1={from.y}
                          x2={to.x}
                          y2={to.y}
                          stroke={style.stroke}
                          strokeWidth={style.width}
                          strokeDasharray={style.dash}
                          markerEnd="url(#arrow)"
                        />
                        {!dim ? (
                          <text
                            x={mx}
                            y={my - 6}
                            textAnchor="middle"
                            className="pointer-events-none fill-[var(--text-tertiary)]"
                            style={{
                              fontSize: 10,
                              paintOrder: 'stroke',
                              stroke: 'var(--bg-inset)',
                              strokeWidth: 3,
                              strokeLinejoin: 'round',
                            }}
                          >
                            {edge.label}
                          </text>
                        ) : null}
                      </g>
                    )
                  })}

                  {visibleNodes.map((node) => {
                    const pos = layout.get(node.id)
                    if (!pos) return null
                    const meta = NODE_KIND_META[node.kind]
                    const isFocus = focusId === node.id
                    const isNeighbour = neighbours.has(node.id)
                    const dim = focusId && !isFocus && !isNeighbour
                    return (
                      <g
                        key={node.id}
                        transform={`translate(${pos.x} ${pos.y})`}
                        opacity={dim ? 0.22 : 1}
                        className="cursor-pointer transition-opacity duration-200"
                        onMouseEnter={() => setHovered(node.id)}
                        onMouseLeave={() => setHovered(null)}
                        onClick={() => setSelected(node)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            setSelected(node)
                          }
                        }}
                        tabIndex={0}
                        role="button"
                        aria-label={`${meta.label}: ${node.label}. ${node.criticality} criticality. Press Enter for details.`}
                      >
                        {isFocus ? <circle r={30} fill={meta.color} opacity={0.12} /> : null}
                        <circle
                          r={20}
                          fill="var(--bg-surface)"
                          stroke={meta.color}
                          strokeWidth={node.criticality === 'critical' ? 2.5 : 1.5}
                        />
                        {/* Criticality is also a ring, never colour alone */}
                        {node.criticality === 'critical' ? (
                          <circle
                            r={24.5}
                            fill="none"
                            stroke={meta.color}
                            strokeWidth={1}
                            strokeDasharray="3 3"
                            opacity={0.6}
                          />
                        ) : null}
                        <foreignObject
                          x={-9}
                          y={-9}
                          width={18}
                          height={18}
                          className="pointer-events-none"
                        >
                          <div
                            className="flex size-[18px] items-center justify-center"
                            style={{ color: meta.color }}
                          >
                            <meta.Icon className="size-[15px]" aria-hidden="true" />
                          </div>
                        </foreignObject>
                        {/* paint-order stroke gives the label a halo so it stays
                            legible where edges pass behind it */}
                        <text
                          y={36}
                          textAnchor="middle"
                          className="pointer-events-none fill-[var(--text-primary)]"
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            paintOrder: 'stroke',
                            stroke: 'var(--bg-inset)',
                            strokeWidth: 3.5,
                            strokeLinejoin: 'round',
                          }}
                        >
                          {node.label.length > 24 ? `${node.label.slice(0, 22)}…` : node.label}
                        </text>
                      </g>
                    )
                  })}
                </g>
              </svg>

              {/* Expanded, the card toolbar is covered, so the canvas carries
                  its own controls — otherwise Escape is the only way out,
                  which is not discoverable. */}
              {isFullscreen ? (
                // z-10: the SVG is a flex sibling that paints after this cluster,
                // so without an explicit stacking order its background rect
                // swallows clicks aimed at these buttons.
                <div
                  data-graph-overlay-controls
                  className="absolute top-3 right-3 z-10 flex items-center gap-1"
                >
                  <Button
                    variant="secondary"
                    size="icon"
                    onClick={() => zoomBy(0.85)}
                    aria-label="Zoom out"
                  >
                    <Minus className="size-3.5" aria-hidden="true" />
                  </Button>
                  <Button
                    variant="secondary"
                    size="icon"
                    onClick={() => zoomBy(1.18)}
                    aria-label="Zoom in"
                  >
                    <Plus className="size-3.5" aria-hidden="true" />
                  </Button>
                  <Button variant="secondary" size="icon" onClick={reset} aria-label="Reset view">
                    <Focus className="size-3.5" aria-hidden="true" />
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={toggleFullscreen}
                    aria-label="Exit expanded view"
                    icon={<Minimize2 className="size-3.5" aria-hidden="true" />}
                  >
                    Exit
                  </Button>
                </div>
              ) : null}

              {/* Legend floats over the canvas */}
              <div className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/95 p-2.5 backdrop-blur">
                <SectionLabel>Link confidence</SectionLabel>
                <div className="mt-1.5 flex flex-col gap-1">
                  {(['confirmed', 'high', 'medium', 'low'] as LinkConfidence[]).map((c) => (
                    <span
                      key={c}
                      className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]"
                    >
                      <svg width="20" height="6" aria-hidden="true">
                        <line
                          x1="0"
                          y1="3"
                          x2="20"
                          y2="3"
                          stroke={EDGE_STYLE[c].stroke}
                          strokeWidth={EDGE_STYLE[c].width}
                          strokeDasharray={EDGE_STYLE[c].dash}
                        />
                      </svg>
                      {humanize(c)}
                    </span>
                  ))}
                </div>
              </div>

              <p className="pointer-events-none absolute right-3 bottom-3 z-10 text-[11px] text-[var(--text-tertiary)]">
                Scroll to zoom · drag to pan · click a node for detail
              </p>
            </div>
          )}
        </Card>
      </div>

      <Modal
        open={attentionOpen}
        onClose={() => setAttentionOpen(false)}
        title="Links awaiting human confirmation"
        description="Cross-artefact links are scored hypotheses until a human confirms them. Confirming a link teaches the graph and improves every later impact analysis."
        footer={
          <Button variant="secondary" onClick={() => setAttentionOpen(false)}>
            Close
          </Button>
        }
      >
        <UnconfirmedLinks edges={edges} nodeById={nodeById} loading={loading} />
      </Modal>

      <NodeDrawer
        node={selected}
        edges={edges}
        nodeById={nodeById}
        onClose={() => setSelected(null)}
      />
    </>
  )
}

function UnconfirmedLinks({
  edges,
  nodeById,
  loading,
}: {
  edges: GraphEdge[]
  nodeById: Map<string, GraphNode>
  loading: boolean
}) {
  const { push } = useToast()
  const [resolved, setResolved] = useState<Set<string>>(new Set())
  const pending = edges.filter((e) => e.confidence !== 'confirmed' && !resolved.has(e.id))

  if (loading)
    return (
      <div className="space-y-2 p-4">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    )

  if (pending.length === 0) {
    return (
      <EmptyState
        icon={<CheckCircle2 className="size-5" aria-hidden="true" />}
        title="Every link is confirmed"
        description="No hypotheses are outstanding. New links appear here after the next ingestion run."
      />
    )
  }

  return (
    <ul className="divide-y divide-[var(--border-subtle)]">
      {pending.map((edge) => {
        const from = nodeById.get(edge.from)
        const to = nodeById.get(edge.to)
        return (
          <li key={edge.id} className="p-4">
            <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
              <span className="font-semibold text-[var(--text-primary)]">{from?.label}</span>
              <span className="text-[var(--text-tertiary)]">— {edge.label} →</span>
              <span className="font-semibold text-[var(--text-primary)]">{to?.label}</span>
              <ConfidenceBadge confidence={edge.confidence} />
            </div>
            <p className="mt-1 text-xs leading-relaxed text-[var(--text-tertiary)]">
              {edge.rationale}
            </p>
            <div className="mt-2.5 flex items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                icon={<CheckCircle2 className="size-3.5" aria-hidden="true" />}
                onClick={() => {
                  setResolved((s) => new Set(s).add(edge.id))
                  push({
                    tone: 'ok',
                    title: 'Link confirmed',
                    description: 'Recorded in the audit chain and used in future analyses.',
                  })
                }}
              >
                Confirm
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setResolved((s) => new Set(s).add(edge.id))
                  push({
                    tone: 'info',
                    title: 'Link rejected',
                    description: 'It will not be used in impact analysis.',
                  })
                }}
              >
                Reject
              </Button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function NodeDrawer({
  node,
  edges,
  nodeById,
  onClose,
}: {
  node: GraphNode | null
  edges: GraphEdge[]
  nodeById: Map<string, GraphNode>
  onClose: () => void
}) {
  if (!node) return null
  const related = edges.filter((e) => e.from === node.id || e.to === node.id)

  return (
    <Drawer
      open={Boolean(node)}
      onClose={onClose}
      title={node.label}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <NodeKindBadge kind={node.kind} />
          <Badge
            tone={
              node.criticality === 'critical'
                ? 'danger'
                : node.criticality === 'high'
                  ? 'warn'
                  : 'neutral'
            }
          >
            {humanize(node.criticality)} criticality
          </Badge>
        </div>
      }
      footer={
        <Button variant="secondary" icon={<ExternalLink className="size-4" aria-hidden="true" />}>
          Open in source system
        </Button>
      }
    >
      <div className="space-y-5 p-5">
        <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">
          {node.description}
        </p>

        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
          <SectionLabel>Provenance</SectionLabel>
          <p className="mt-1.5 font-mono text-xs break-all text-[var(--text-primary)]">
            {node.provenance}
          </p>
          <p className="mt-1 font-mono text-[11px] break-all text-[var(--text-tertiary)]">
            {node.sourceRef}
          </p>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          <div>
            <dt className="text-[10px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Owner
            </dt>
            <dd className="mt-0.5 text-[13px] text-[var(--text-primary)]">{node.owner}</dd>
          </div>
          <div>
            <dt className="text-[10px] font-semibold tracking-[0.08em] text-[var(--text-tertiary)] uppercase">
              Last verified
            </dt>
            <dd className="mt-0.5 text-[13px] text-[var(--text-primary)]">
              {relativeTime(node.lastVerifiedAt)}
            </dd>
          </div>
        </dl>

        <div>
          <SectionLabel>Connected nodes ({related.length})</SectionLabel>
          <ul className="mt-2 space-y-2">
            {related.map((edge) => {
              const isOutgoing = edge.from === node.id
              const other = nodeById.get(isOutgoing ? edge.to : edge.from)
              if (!other) return null
              return (
                <li
                  key={edge.id}
                  className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-2.5"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-[var(--text-tertiary)]">
                      {isOutgoing ? '→' : '←'} {edge.label}
                    </span>
                    <span className="text-[13px] font-medium text-[var(--text-primary)]">
                      {other.label}
                    </span>
                    <ConfidenceBadge confidence={edge.confidence} />
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                    {edge.rationale}
                  </p>
                  {edge.confirmedBy ? (
                    <p className="mt-1 text-[11px] text-[var(--ok)]">
                      Confirmed by {edge.confirmedBy} · {relativeTime(edge.confirmedAt)}
                    </p>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </Drawer>
  )
}

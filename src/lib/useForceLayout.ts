import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphEdge, GraphNode } from './types'

export interface PositionedNode {
  id: string
  x: number
  y: number
}

interface Body {
  id: string
  x: number
  y: number
  vx: number
  vy: number
  /** Heavier nodes (more connections) move less, so hubs stay put */
  mass: number
}

/**
 * Minimal force-directed layout: repulsion between every pair, spring
 * attraction along edges, and a weak pull to the centre.
 *
 * Written by hand rather than pulled from d3-force because we only need a
 * static settle for a few dozen nodes — the whole simulation runs once on
 * mount and the result is memoised. For thousands of nodes this should be
 * replaced with d3-force in a worker.
 */
export function useForceLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  opts: { width: number; height: number; iterations?: number } = { width: 1000, height: 620 },
): Map<string, PositionedNode> {
  const { width, height, iterations = 320 } = opts

  return useMemo(() => {
    const result = new Map<string, PositionedNode>()
    if (nodes.length === 0) return result

    const degree = new Map<string, number>()
    edges.forEach((e) => {
      degree.set(e.from, (degree.get(e.from) ?? 0) + 1)
      degree.set(e.to, (degree.get(e.to) ?? 0) + 1)
    })

    // Deterministic starting ring — no Math.random, so layout is reproducible
    const bodies: Body[] = nodes.map((n, i) => {
      const angle = (i / nodes.length) * Math.PI * 2
      const radius = Math.min(width, height) * 0.32
      return {
        id: n.id,
        x: width / 2 + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        mass: 1 + (degree.get(n.id) ?? 0) * 0.6,
      }
    })

    const index = new Map(bodies.map((b, i) => [b.id, i]))
    const links = edges
      .map((e) => ({ a: index.get(e.from), b: index.get(e.to) }))
      .filter((l): l is { a: number; b: number } => l.a !== undefined && l.b !== undefined)

    const REPULSION = 14000
    const SPRING = 0.012
    const REST_LENGTH = 150
    const CENTER_PULL = 0.006
    const DAMPING = 0.86

    for (let step = 0; step < iterations; step++) {
      // Pairwise repulsion
      for (let i = 0; i < bodies.length; i++) {
        for (let j = i + 1; j < bodies.length; j++) {
          const a = bodies[i]
          const b = bodies[j]
          let dx = b.x - a.x
          let dy = b.y - a.y
          let distSq = dx * dx + dy * dy
          if (distSq < 1) {
            // Deterministic nudge so coincident nodes separate
            dx = (i - j) * 0.5 || 0.5
            dy = (j - i) * 0.5 || 0.5
            distSq = dx * dx + dy * dy
          }
          const dist = Math.sqrt(distSq)
          const force = REPULSION / distSq
          const fx = (dx / dist) * force
          const fy = (dy / dist) * force
          a.vx -= fx / a.mass
          a.vy -= fy / a.mass
          b.vx += fx / b.mass
          b.vy += fy / b.mass
        }
      }

      // Spring attraction along edges
      for (const l of links) {
        const a = bodies[l.a]
        const b = bodies[l.b]
        const dx = b.x - a.x
        const dy = b.y - a.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (dist - REST_LENGTH) * SPRING
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        a.vx += fx / a.mass
        a.vy += fy / a.mass
        b.vx -= fx / b.mass
        b.vy -= fy / b.mass
      }

      // Gentle centring + integrate
      for (const b of bodies) {
        b.vx += (width / 2 - b.x) * CENTER_PULL
        b.vy += (height / 2 - b.y) * CENTER_PULL
        b.vx *= DAMPING
        b.vy *= DAMPING
        b.x += b.vx
        b.y += b.vy
      }
    }

    // Fit to viewport with padding
    const pad = 60
    const xs = bodies.map((b) => b.x)
    const ys = bodies.map((b) => b.y)
    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)
    const spanX = maxX - minX || 1
    const spanY = maxY - minY || 1
    const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY)

    for (const b of bodies) {
      result.set(b.id, {
        id: b.id,
        x: pad + (b.x - minX) * scale + (width - pad * 2 - spanX * scale) / 2,
        y: pad + (b.y - minY) * scale + (height - pad * 2 - spanY * scale) / 2,
      })
    }
    return result
  }, [nodes, edges, width, height, iterations])
}

/** Pan + zoom state for an SVG canvas, driven by wheel and pointer drag. */
export function usePanZoom(ref: React.RefObject<SVGSVGElement | null>) {
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const dragging = useRef<{ x: number; y: number } | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    function onWheel(e: WheelEvent) {
      e.preventDefault()
      setTransform((t) => {
        const k = Math.min(3, Math.max(0.4, t.k * (e.deltaY < 0 ? 1.12 : 0.89)))
        return { ...t, k }
      })
    }
    function onDown(e: PointerEvent) {
      if (e.button !== 0) return
      dragging.current = { x: e.clientX, y: e.clientY }
      el!.setPointerCapture(e.pointerId)
    }
    function onMove(e: PointerEvent) {
      if (!dragging.current) return
      const dx = e.clientX - dragging.current.x
      const dy = e.clientY - dragging.current.y
      dragging.current = { x: e.clientX, y: e.clientY }
      setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }))
    }
    function onUp(e: PointerEvent) {
      dragging.current = null
      if (el!.hasPointerCapture(e.pointerId)) el!.releasePointerCapture(e.pointerId)
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
    }
  }, [ref])

  const reset = () => setTransform({ x: 0, y: 0, k: 1 })
  const zoomBy = (factor: number) =>
    setTransform((t) => ({ ...t, k: Math.min(3, Math.max(0.4, t.k * factor)) }))

  return { transform, reset, zoomBy }
}

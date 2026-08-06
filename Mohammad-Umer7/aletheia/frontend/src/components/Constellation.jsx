// The Constellation: Aletheia's entire memory as a living force-directed sky.
// Node lifecycle (entering / pulsing / dying) is drawn per-frame in canvas —
// react-force-graph re-renders continuously, so reading the clock inside
// nodeCanvasObject animates without any React state churn.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

const HUES = ['#7C6CFF', '#C86CFF', '#5FD4E8', '#FFB454']
const STRUCTURAL = '#4A4468'
const RETRACTION = '#FF4D5E'
const PULSE = '#6CFFA8'

const ENTER_MS = 600
const ENTER_STAGGER_MS = 8
const DIE_MS = 1600
const PULSE_MS = 3000

const easeOut = (t) => 1 - Math.pow(1 - t, 3)

export default function Constellation({ graph, sources, controlRef, reducedMotion }) {
  const fgRef = useRef(null)
  const wrapRef = useRef(null)
  const lifecycle = useRef(new Map()) // id -> {status, t0, stagger, pulseUntil}
  const dataRef = useRef({ nodes: [], links: [] })
  const [graphData, setGraphData] = useState(dataRef.current)
  const [hover, setHover] = useState(null)
  const mouse = useRef({ x: 0, y: 0 })
  const [size, setSize] = useState({ w: 800, h: 600 })
  const didFit = useRef(false)

  const colorBySource = useMemo(() => {
    const map = new Map()
    for (const s of sources) map.set(s.id, HUES[s.color_index % HUES.length])
    return map
  }, [sources])

  const degree = useMemo(() => {
    const d = new Map()
    for (const l of graphData.links) {
      const s = typeof l.source === 'object' ? l.source.id : l.source
      const t = typeof l.target === 'object' ? l.target.id : l.target
      d.set(s, (d.get(s) || 0) + 1)
      d.set(t, (d.get(t) || 0) + 1)
    }
    return d
  }, [graphData])

  // --- keep canvas sized to its container ---------------------------------
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ w: width, h: height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // --- merge server graph into the living data ------------------------------
  useEffect(() => {
    const now = performance.now()
    const cur = dataRef.current
    const curById = new Map(cur.nodes.map((n) => [n.id, n]))
    const serverIds = new Set(graph.nodes.map((n) => n.id))

    const merged = []
    for (const n of cur.nodes) {
      const lc = lifecycle.current.get(n.id)
      if (serverIds.has(n.id) || lc?.status === 'dying') merged.push(n)
    }
    let stagger = 0
    for (const sn of graph.nodes) {
      const existing = curById.get(sn.id)
      if (existing) {
        Object.assign(existing, {
          label: sn.label,
          type: sn.type,
          description: sn.description,
          source_id: sn.source_id,
          trust: sn.trust,
        })
      } else {
        merged.push({ ...sn })
        lifecycle.current.set(sn.id, {
          status: 'entering',
          t0: now,
          stagger: reducedMotion ? 0 : stagger * ENTER_STAGGER_MS,
        })
        stagger += 1
      }
    }

    const mergedIds = new Set(merged.map((n) => n.id))
    const links = graph.links
      .filter((l) => mergedIds.has(l.source) && mergedIds.has(l.target))
      .map((l) => ({ ...l }))

    dataRef.current = { nodes: merged, links }
    setGraphData(dataRef.current)
  }, [graph, reducedMotion])

  // --- imperative controls for App (retract + answer pulse) -----------------
  useEffect(() => {
    controlRef.current = {
      killNodes(ids) {
        const now = performance.now()
        const idSet = new Set(ids)
        for (const id of ids) {
          lifecycle.current.set(id, { status: 'dying', t0: now })
        }
        const finish = () => {
          const cur = dataRef.current
          const nodes = cur.nodes.filter((n) => !idSet.has(n.id))
          const keep = new Set(nodes.map((n) => n.id))
          const links = cur.links.filter((l) => {
            const s = typeof l.source === 'object' ? l.source.id : l.source
            const t = typeof l.target === 'object' ? l.target.id : l.target
            return keep.has(s) && keep.has(t)
          })
          for (const id of idSet) lifecycle.current.delete(id)
          dataRef.current = { nodes, links }
          setGraphData(dataRef.current)
          fgRef.current?.d3ReheatSimulation()
        }
        if (reducedMotion) finish()
        else setTimeout(finish, DIE_MS + 60)
        return reducedMotion ? 0 : DIE_MS
      },
      pulseNodes(ids, color) {
        if (reducedMotion) return
        // answer pulses run the full glow; per-source receipt pulses run 2s
        const until = performance.now() + (color ? 2000 : PULSE_MS)
        for (const id of ids) {
          const lc = lifecycle.current.get(id) || { status: 'alive' }
          lifecycle.current.set(id, { ...lc, pulseUntil: until, pulseColor: color || null })
        }
      },
    }
    return () => {
      controlRef.current = null
    }
  }, [controlRef, reducedMotion])

  // --- drawing ----------------------------------------------------------------
  const nodeCanvasObject = useCallback(
    (node, ctx) => {
      const now = performance.now()
      const lc = lifecycle.current.get(node.id)
      const deg = degree.get(node.id) || 1
      let r = Math.max(3, Math.min(9, 2.4 + deg * 0.9))
      let alpha = 1

      if (lc?.status === 'entering') {
        const t = (now - lc.t0 - lc.stagger) / ENTER_MS
        if (t >= 1) {
          lifecycle.current.set(node.id, { ...lc, status: 'alive' })
        } else if (t <= 0) {
          return
        } else {
          const e = easeOut(t)
          r *= e
          alpha = e
        }
      }

      let dying = false
      if (lc?.status === 'dying') {
        dying = true
        const t = Math.min(1, (now - lc.t0) / DIE_MS)
        alpha = Math.pow(1 - t, 1.4)
        r *= 1 - 0.85 * easeOut(t)
        if (alpha <= 0.02) return
      }

      const structural = !node.source_id
      const base = structural ? STRUCTURAL : colorBySource.get(node.source_id) || STRUCTURAL
      const color = dying ? RETRACTION : base
      if (structural) r *= 0.85 // plumbing recedes; knowledge shines

      const pulsing = !dying && lc?.pulseUntil && now < lc.pulseUntil
      ctx.save()
      ctx.globalAlpha = alpha

      if (pulsing) {
        const pulseColor = lc.pulseColor || PULSE
        const wave = 0.5 + 0.5 * Math.sin((now - (lc.pulseUntil - PULSE_MS)) / 150)
        ctx.shadowColor = pulseColor
        ctx.shadowBlur = 14 + 10 * wave
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 2.5 + wave * 1.5, 0, 2 * Math.PI)
        ctx.strokeStyle = pulseColor
        ctx.globalAlpha = alpha * (0.35 + 0.4 * wave)
        ctx.lineWidth = 1.2
        ctx.stroke()
        ctx.globalAlpha = alpha
      } else {
        ctx.shadowColor = color
        ctx.shadowBlur = dying ? 22 : 9
      }

      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()

      // tiny bright core gives the "star" read (structural nodes stay matte)
      ctx.shadowBlur = 0
      ctx.beginPath()
      ctx.arc(node.x, node.y, Math.max(0.7, r * (structural ? 0.22 : 0.32)), 0, 2 * Math.PI)
      ctx.fillStyle = structural ? 'rgba(237,234,247,0.35)' : 'rgba(237,234,247,0.9)'
      ctx.fill()
      ctx.restore()
    },
    [degree, colorBySource],
  )

  const linkColor = useCallback((l) => {
    const s = typeof l.source === 'object' ? l.source.id : l.source
    const t = typeof l.target === 'object' ? l.target.id : l.target
    const sd = lifecycle.current.get(s)?.status === 'dying'
    const td = lifecycle.current.get(t)?.status === 'dying'
    return sd || td ? 'rgba(255,77,94,0.4)' : 'rgba(139,132,168,0.2)'
  }, [])

  // fit once when the first real data lands
  useEffect(() => {
    if (!didFit.current && graphData.nodes.length > 0) {
      didFit.current = true
      setTimeout(() => fgRef.current?.zoomToFit(600, 90), 450)
    }
  }, [graphData])

  return (
    <div
      ref={wrapRef}
      className="constellation-layer"
      onMouseMove={(e) => {
        mouse.current = { x: e.clientX, y: e.clientY }
      }}
    >
      <ForceGraph2D
        ref={fgRef}
        width={size.w}
        height={size.h}
        graphData={graphData}
        backgroundColor="rgba(0,0,0,0)"
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={(node, color, ctx) => {
          ctx.fillStyle = color
          ctx.beginPath()
          ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI)
          ctx.fill()
        }}
        onNodeHover={(node) => setHover(node || null)}
        linkColor={linkColor}
        linkWidth={1}
        d3VelocityDecay={0.28}
        cooldownTime={4000}
        warmupTicks={30}
      />
      {hover && (
        <div
          className="node-tooltip mono"
          style={{ left: mouse.current.x + 14, top: mouse.current.y + 14 }}
        >
          <div className="tt-name">{hover.label || '(unnamed)'}</div>
          <div className="tt-row">
            <span>Type</span> {hover.type}
          </div>
          <div className="tt-row">
            <span>ID</span> {String(hover.id).slice(0, 13)}
          </div>
          {hover.description ? <div className="tt-desc">{hover.description}</div> : null}
        </div>
      )}
    </div>
  )
}

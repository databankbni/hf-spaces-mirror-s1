// Aletheia's client data layer: sources / graph / changelog state with
// busy-aware polling. Polls fast while the backend is ingesting or seeding,
// slow when idle; consumers trigger explicit refreshes after mutations.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

const FAST_MS = 3500
const IDLE_MS = 15000

export function useAletheia() {
  const [sources, setSources] = useState([])
  const [graph, setGraph] = useState({ nodes: [], links: [] })
  const [entries, setEntries] = useState([])
  const [busy, setBusy] = useState([])
  const [connected, setConnected] = useState(true)
  const graphListeners = useRef(new Set())

  const refreshSources = useCallback(async () => {
    const body = await api.sources()
    setSources(body.sources)
    return body.sources
  }, [])

  const refreshGraph = useCallback(async () => {
    const body = await api.graph()
    setGraph(body)
    graphListeners.current.forEach((fn) => fn(body))
    return body
  }, [])

  const refreshChangelog = useCallback(async () => {
    const body = await api.changelog()
    setEntries(body.entries)
    return body.entries
  }, [])

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshSources(), refreshGraph(), refreshChangelog()])
  }, [refreshSources, refreshGraph, refreshChangelog])

  // Busy-aware poll loop. While ingestion/seeding runs, sources flip status and
  // the graph grows — keep everything in sync without user action.
  useEffect(() => {
    let alive = true
    let timer
    const tick = async () => {
      let delay = IDLE_MS
      try {
        const status = await api.status()
        if (!alive) return
        setBusy(status.busy)
        setConnected(true)
        const anyIngesting = (s) => s.status === 'ingesting'
        const before = await refreshSources()
        if (status.busy.length > 0 || before.some(anyIngesting)) {
          delay = FAST_MS
          await Promise.all([refreshGraph(), refreshChangelog()])
        }
      } catch {
        if (!alive) return
        setConnected(false)
      }
      timer = setTimeout(tick, delay)
    }
    refreshAll().catch(() => setConnected(false))
    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [refreshAll, refreshSources, refreshGraph, refreshChangelog])

  // Constellation subscribes to graph refreshes to diff and animate arrivals.
  const onGraphUpdate = useCallback((fn) => {
    graphListeners.current.add(fn)
    return () => graphListeners.current.delete(fn)
  }, [])

  return {
    sources,
    graph,
    entries,
    busy,
    connected,
    refreshSources,
    refreshGraph,
    refreshChangelog,
    refreshAll,
    onGraphUpdate,
  }
}

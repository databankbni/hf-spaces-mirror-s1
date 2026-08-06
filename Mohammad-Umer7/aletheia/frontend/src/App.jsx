// Aletheia — an AI research assistant that can change its mind.
// Layout: the constellation owns the viewport; glass panels float over it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { HelpCircle, Sparkles } from 'lucide-react'

import AskPanel from './components/AskPanel'
import Constellation from './components/Constellation'
import FlightSpotlight from './components/FlightSpotlight'
import GuidedFlight, { FLIGHT_STEPS } from './components/GuidedFlight'
import LedgerPanel from './components/LedgerPanel'
import Onboarding from './components/Onboarding'
import RetractModal from './components/RetractModal'
import RetractTicker from './components/RetractTicker'
import SourcesPanel from './components/SourcesPanel'
import { Toasts, useToasts } from './components/Toasts'
import { api } from './lib/api'
import { useAletheia } from './lib/useAletheia'

const SOURCE_HUES = ['#7C6CFF', '#C86CFF', '#5FD4E8', '#FFB454']

export default function App() {
  const {
    sources,
    graph,
    entries,
    busy,
    connected,
    refreshSources,
    refreshGraph,
    refreshChangelog,
  } = useAletheia()
  const constellation = useRef(null)
  const { toasts, push, dismiss } = useToasts()
  const [thread, setThread] = useState([])
  const [asking, setAsking] = useState(false)
  const [retractTarget, setRetractTarget] = useState(null) // {source, reason}
  const [ticker, setTicker] = useState(null) // {nodes, links, duration}
  const [reaskPending, setReaskPending] = useState(false) // offer the same question again after a retraction

  // Deliberately NOT persisted: every visit starts with the story from the top —
  // onboarding first, then the guided flight (dismissing lasts for the session only).
  const [onboardingOpen, setOnboardingOpen] = useState(true)
  const [flightVisible, setFlightVisible] = useState(true)

  const reducedMotion = useMemo(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  )

  const seeding = busy.some((b) => b.startsWith('seed'))
  const isEmpty = sources.length === 0 && graph.nodes.length === 0 && !seeding

  // While ANY ingestion is running, recall is unreliable (and the demo beat is
  // wrong anyway) — asking stays locked until Aletheia finishes reading.
  // Background re-enrichment after a retraction does NOT block asking.
  const reading =
    seeding ||
    busy.some((b) => b.startsWith('ingest')) ||
    sources.some((s) => s.status === 'ingesting')
  const canAsk =
    !reading && sources.some((s) => s.trust === 'trusted' && s.status === 'ready')

  // Flight progress is strictly what happened THIS session — never inferred from
  // leftover backend state, so a refresh always restarts the story at step 1.
  const [flightActions, setFlightActions] = useState({
    seed: false,
    notice: false,
    retract: false,
  })
  const answers = thread.filter((m) => m.role === 'aletheia').length
  const trustedReady = sources.filter((s) => s.trust === 'trusted' && s.status === 'ready').length
  const flightProgress = {
    // seed ticks when all three demo sources are actually read — step 2 (ask)
    // must not invite a question while Aletheia is still ingesting
    seed: flightActions.seed && trustedReady >= 3 && !seeding,
    ask: answers >= 1,
    notice: flightActions.notice,
    retract: flightActions.retract,
    reask: flightActions.retract && answers >= 2,
  }
  const flightComplete = Object.values(flightProgress).every(Boolean)

  // The spotlight steps aside while Aletheia works — and during the retraction
  // animation, so the dimmer can never mute the money shot.
  const [spotlightHold, setSpotlightHold] = useState(false)
  const activeStep = FLIGHT_STEPS.find((s) => !flightProgress[s.key])
  const spotlightPaused =
    !flightVisible ||
    onboardingOpen ||
    flightComplete ||
    spotlightHold ||
    asking ||
    busy.length > 0 ||
    !activeStep

  useEffect(() => {
    if (flightComplete && flightVisible) {
      const id = setTimeout(() => setFlightVisible(false), 9000)
      return () => clearTimeout(id)
    }
  }, [flightComplete, flightVisible])

  function closeOnboarding() {
    setOnboardingOpen(false)
  }

  function startFlight() {
    setFlightVisible(true)
  }

  async function handleAsk(question) {
    setReaskPending(false)
    setThread((t) => [...t, { role: 'user', text: question }])
    setAsking(true)
    try {
      const res = await api.ask(question)
      setThread((t) => [
        ...t,
        {
          role: 'aletheia',
          text: res.answer ?? 'I have no trusted sources to draw on yet — feed me something to read.',
          cited: res.cited_sources,
          stateless: res.stateless_answer,
        },
      ])
      if (res.highlight_node_ids?.length) {
        constellation.current?.pulseNodes(res.highlight_node_ids)
      }
    } catch (e) {
      push({ tone: 'error', text: `Ask failed — ${e.message}` })
      setThread((t) => t.slice(0, -1))
    } finally {
      setAsking(false)
    }
  }

  // Sequenced for weight: modal confirm -> red bleed + live ticker count-up ->
  // ledger entry types in as the ticker lands -> graph re-settles.
  async function handleRetract(source, reason) {
    setRetractTarget(null)
    try {
      setSpotlightHold(true)
      setTimeout(() => setSpotlightHold(false), 5200) // let the sky finish mourning
      const res = await api.retract(source.id, reason)
      setFlightActions((f) => ({ ...f, retract: true }))
      if (thread.some((m) => m.role === 'user')) setReaskPending(true)
      const dieMs = constellation.current?.killNodes(res.removed_node_ids) ?? 0
      const duration = reducedMotion ? 1 : dieMs || 1600
      setTicker({
        nodes: res.nodes_removed,
        links: res.links_removed ?? 0,
        duration,
      })
      refreshSources()
      // reconcile with the server only after the constellation finishes mourning
      setTimeout(() => refreshGraph(), duration + 300)
      setTimeout(() => setTicker(null), duration + 3000)
    } catch (e) {
      push({ tone: 'error', text: `Retract failed — ${e.message}` })
    }
  }

  // The ledger entry types in exactly when the ticker lands on its numbers.
  const handleTickerDone = useCallback(() => {
    refreshChangelog()
  }, [refreshChangelog])

  // Receipts on demand: clicking a citation chip pulses that source's memories
  // in the constellation with the source's own hue.
  function handleCite(cited) {
    const source = sources.find((s) => s.id === cited.id)
    if (source?.node_ids?.length) {
      constellation.current?.pulseNodes(
        source.node_ids,
        SOURCE_HUES[source.color_index % SOURCE_HUES.length],
      )
    }
  }

  async function handleAddSource(payload) {
    try {
      await api.addSource(payload)
      push({ tone: 'busy', text: `Reading “${payload.title}” — ~60s`, ttl: 6000 })
    } catch (e) {
      push({ tone: 'error', text: `Add failed — ${e.message}` })
    }
  }

  async function handleSeed() {
    try {
      await api.seedDemo()
      setFlightActions({ seed: true, notice: false, retract: false }) // fresh worldview, fresh story
      setThread([])
      push({ tone: 'busy', text: 'Loading demo scenario — three sources, ~3 min', ttl: 8000 })
    } catch (e) {
      push({ tone: 'error', text: `Seed failed — ${e.message}` })
    }
  }

  async function handleIngestRetraction() {
    try {
      await api.ingestRetraction()
      setFlightActions((f) => ({ ...f, notice: true }))
      push({ tone: 'busy', text: 'A retraction notice arrives — Aletheia is reading it', ttl: 6000 })
    } catch (e) {
      push({ tone: 'error', text: `Ingest failed — ${e.message}` })
    }
  }

  return (
    <div className="shell">
      <Constellation
        graph={graph}
        sources={sources}
        controlRef={constellation}
        reducedMotion={reducedMotion}
      />

      {isEmpty && (
        <div className="empty-state">
          <div>
            <svg className="sketch" width="180" height="90" viewBox="0 0 180 90">
              {[
                [20, 60], [55, 25], [90, 55], [125, 20], [160, 50], [70, 75], [140, 75],
              ].map(([x, y], i) => (
                <circle key={i} cx={x} cy={y} r="2.5" fill="#8B84A8" />
              ))}
              <path
                d="M20 60 L55 25 L90 55 L125 20 L160 50 M55 25 L70 75 M125 20 L140 75"
                stroke="#8B84A8"
                strokeWidth="0.6"
                fill="none"
                opacity="0.5"
              />
            </svg>
            <p>Aletheia hasn’t read anything yet. Load the demo scenario or add a source.</p>
            <motion.button
              whileTap={{ scale: 0.98 }}
              className="btn cta"
              onClick={handleSeed}
            >
              <Sparkles size={14} /> Load demo scenario
            </motion.button>
          </div>
        </div>
      )}

      <div className="ui-layer">
        <header className="header">
          <div className="wordmark">
            <span className="mark">✦</span>
            <span className="name">ALETHEIA</span>
            <span className="tagline">the un-forgetting</span>
          </div>
          <div className="header-right">
            <div className="stats">
              {connected ? (
                <>
                  {graph.nodes.length} memories · {graph.links.length} links
                </>
              ) : (
                <span className="disconnected">backend unreachable — is uvicorn running on :8000?</span>
              )}
            </div>
            <button
              className="btn ghost icon-btn"
              onClick={() => setOnboardingOpen(true)}
              title="What is Aletheia?"
              aria-label="Open the introduction"
            >
              <HelpCircle size={14} />
            </button>
          </div>
        </header>

        <div className="columns">
          <div className="column">
            <SourcesPanel
              sources={sources}
              seeding={seeding}
              onRequestRetract={(source, reason) => setRetractTarget({ source, reason })}
              onAdd={handleAddSource}
              onSeed={handleSeed}
              onIngestRetraction={handleIngestRetraction}
            />
            <AnimatePresence>
              {ticker && (
                <RetractTicker
                  nodes={ticker.nodes}
                  links={ticker.links}
                  duration={ticker.duration}
                  onDone={handleTickerDone}
                />
              )}
            </AnimatePresence>
            <LedgerPanel entries={entries} reducedMotion={reducedMotion} />
          </div>
          <div className="column" />
          <div className="column">
            <AskPanel
              thread={thread}
              asking={asking}
              onAsk={handleAsk}
              onCite={handleCite}
              hasSources={canAsk}
              reading={reading}
              reaskQuestion={
                reaskPending && canAsk
                  ? [...thread].reverse().find((m) => m.role === 'user')?.text ?? null
                  : null
              }
            />
          </div>
        </div>
      </div>

      <FlightSpotlight
        selectors={activeStep?.spot ?? []}
        hint={activeStep?.action ?? ''}
        paused={spotlightPaused}
        reducedMotion={reducedMotion}
        forceHintBelow={activeStep?.hintPlacement === 'below'}
      />

      <AnimatePresence>
        {flightVisible && !onboardingOpen && (
          <GuidedFlight
            progress={flightProgress}
            onDismiss={() => setFlightVisible(false)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {retractTarget && (
          <RetractModal
            source={retractTarget.source}
            defaultReason={retractTarget.reason}
            onConfirm={(reason) => handleRetract(retractTarget.source, reason)}
            onCancel={() => setRetractTarget(null)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {onboardingOpen && (
          <Onboarding open onClose={closeOnboarding} onStartFlight={startFlight} />
        )}
      </AnimatePresence>

      <Toasts toasts={toasts} dismiss={dismiss} />
    </div>
  )
}

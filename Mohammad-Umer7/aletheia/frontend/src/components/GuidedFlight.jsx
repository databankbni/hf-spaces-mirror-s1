// The Guided Flight: five demo beats that check themselves off from real app
// state. The onboarding literally is the demo script.
import { AnimatePresence, motion } from 'framer-motion'
import { Check, X } from 'lucide-react'

export const FLIGHT_STEPS = [
  {
    key: 'seed',
    label: 'Load the demo scenario',
    hint: 'Sources panel, top left — Aletheia reads three sources (~3 min).',
    spot: ['[data-flight="seed-primary"]', '[data-flight="seed"]'],
    action: 'Start here — Aletheia reads three sources',
  },
  {
    key: 'ask',
    label: 'Ask the suggested question',
    hint: 'Right panel — click the quoted question.',
    spot: ['[data-flight="ask"]', '[data-flight="askbox"]'],
    action: 'Click the quoted question',
  },
  {
    key: 'notice',
    label: 'Let the retraction notice arrive',
    hint: 'Sources panel — “A retraction notice arrives…”.',
    spot: ['[data-flight="notice"]'],
    action: 'Bad news for that study — let it in',
    hintPlacement: 'below', // the row above the button must stay readable
  },
  {
    key: 'retract',
    label: 'Confirm the retraction Aletheia proposes',
    hint: 'Aletheia noticed the conflict itself — confirm on the amber card. Watch the sky.',
    spot: ['[data-flight="conflict-retract"]', '[data-flight="retract"]'],
    action: 'Aletheia found the conflict — you confirm',
    hintPlacement: 'below', // the target sits at a card's bottom edge — never cover the card
  },
  {
    key: 'reask',
    label: 'Ask again — watch it change its mind',
    hint: 'Same question. Different answer, different sources.',
    spot: ['[data-flight="reask"]', '[data-flight="askbox"]'],
    action: 'Same question again — new worldview',
  },
]

const STEPS = FLIGHT_STEPS

export default function GuidedFlight({ progress, onDismiss }) {
  const doneCount = STEPS.filter((s) => progress[s.key]).length
  const activeIdx = STEPS.findIndex((s) => !progress[s.key])
  const complete = doneCount === STEPS.length

  return (
    <motion.aside
      className="flight"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 14 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      aria-label="Guided flight"
    >
      <div className="flight-head">
        <span className="panel-title">Guided flight</span>
        <span className="mono flight-count">{doneCount}/{STEPS.length}</span>
        <button className="flight-close" onClick={onDismiss} aria-label="Dismiss guide">
          <X size={13} />
        </button>
      </div>

      {complete ? (
        <motion.div className="flight-done" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          Aletheia changed its mind — and you watched it happen.
          <br />
          <span className="muted">That’s the whole point. The sky is yours now.</span>
        </motion.div>
      ) : (
        <ol className="flight-steps">
          {STEPS.map((s, idx) => {
            const done = !!progress[s.key]
            const active = idx === activeIdx
            return (
              <li key={s.key} className={`flight-step ${done ? 'done' : ''} ${active ? 'active' : ''}`}>
                <span className="flight-marker">
                  {done ? <Check size={11} /> : <span className="flight-idx mono">{idx + 1}</span>}
                </span>
                <span className="flight-label">
                  {s.label}
                  <AnimatePresence>
                    {active && (
                      <motion.span
                        className="flight-hint"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                      >
                        {s.hint}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </motion.aside>
  )
}

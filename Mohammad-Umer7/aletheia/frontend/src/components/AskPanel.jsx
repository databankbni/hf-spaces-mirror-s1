// Ask Aletheia: the chat thread. Answers cite their sources as hue chips; the
// thinking indicator is a tiny constellation, not dots. Each answer carries a
// segmented toggle to the stateless-LLM baseline — same question, no memory.
import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Send } from 'lucide-react'

const HUE_VAR = ['var(--hue-0)', 'var(--hue-1)', 'var(--hue-2)', 'var(--hue-3)']
const SUGGESTED = 'Does Mnemosyne-7 improve memory? What actually works?'

function Thinking() {
  return (
    <div className="msg aletheia thinking" aria-label="Aletheia is thinking">
      <svg width="46" height="22" viewBox="0 0 46 22">
        <line x1="8" y1="11" x2="23" y2="6" className="think-link l1" />
        <line x1="23" y1="6" x2="38" y2="13" className="think-link l2" />
        <circle cx="8" cy="11" r="3" className="think-node n1" />
        <circle cx="23" cy="6" r="3" className="think-node n2" />
        <circle cx="38" cy="13" r="3" className="think-node n3" />
      </svg>
      <span className="thinking-copy">Aletheia is thinking…</span>
    </div>
  )
}

// One Aletheia answer: memory-grounded text with clickable receipt chips, plus
// an instant (no refetch) toggle to what a memoryless LLM said to the same question.
function AnswerMsg({ msg, onCite }) {
  const [view, setView] = useState('aletheia')
  const showToggle = typeof msg.stateless === 'string' && msg.stateless.trim()
  return (
    <motion.div
      className="msg aletheia"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
    >
      {showToggle && (
        <div className="segmented" role="tablist" aria-label="Answer source">
          <button
            role="tab"
            aria-selected={view === 'aletheia'}
            className={`seg ${view === 'aletheia' ? 'active' : ''}`}
            onClick={() => setView('aletheia')}
          >
            Aletheia
          </button>
          <button
            role="tab"
            aria-selected={view === 'stateless'}
            className={`seg ${view === 'stateless' ? 'active' : ''}`}
            onClick={() => setView('stateless')}
          >
            Stateless LLM
          </button>
        </div>
      )}
      {view === 'aletheia' ? (
        <>
          <div className="msg-text">{msg.text}</div>
          {msg.cited?.length > 0 && (
            <div className="citations">
              <span className="based-on">Based on:</span>
              {msg.cited.map((c) => (
                <button
                  className="chip"
                  key={c.id}
                  onClick={() => onCite?.(c)}
                  title="Show this source's memories"
                >
                  <span
                    className="hue-dot"
                    style={{ background: HUE_VAR[c.color_index % 4] }}
                  />
                  {c.title}
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="msg-text">{msg.stateless}</div>
          <div className="stateless-note mono">no memory, no sources</div>
        </>
      )}
    </motion.div>
  )
}

export default function AskPanel({ thread, asking, onAsk, hasSources, onCite, reading, reaskQuestion }) {
  const [question, setQuestion] = useState('')
  const bodyRef = useRef(null)

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [thread, asking])

  const submit = () => {
    const q = question.trim()
    if (!q || asking || !hasSources) return // no trusted memories yet — nothing to answer from
    setQuestion('')
    onAsk(q)
  }

  return (
    <section className="panel ask-panel" aria-label="Ask Aletheia">
      <div className="panel-header">
        <span className="panel-title">Ask Aletheia</span>
      </div>
      <div className="panel-body ask-body" ref={bodyRef}>
        {thread.length === 0 && !asking && (
          <div className="ask-empty">
            <p>Ask anything — every answer comes from Aletheia’s memory, and says which sources it stands on.</p>
            {hasSources && (
              <button className="suggestion mono" onClick={() => onAsk(SUGGESTED)} data-flight="ask">
                “{SUGGESTED}”
              </button>
            )}
          </div>
        )}
        {thread.map((m, i) =>
          m.role === 'aletheia' ? (
            <AnswerMsg key={i} msg={m} onCite={onCite} />
          ) : (
            <motion.div
              key={i}
              className="msg user"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
            >
              <div className="msg-text">{m.text}</div>
            </motion.div>
          ),
        )}
        {asking && <Thinking />}
        {reaskQuestion && !asking && (
          <div className="reask">
            <span className="reask-copy">Aletheia's memory changed — same question, new worldview?</span>
            <button
              className="suggestion mono"
              onClick={() => onAsk(reaskQuestion)}
              data-flight="reask"
            >
              “{reaskQuestion}”
            </button>
          </div>
        )}
      </div>
      <div className="ask-input" data-flight="askbox">
        <textarea
          className="field"
          rows={2}
          placeholder={
            hasSources
              ? 'Ask Aletheia…'
              : reading
                ? 'Aletheia is reading — asking unlocks when it finishes…'
                : 'Add sources first — Aletheia answers only from memory.'
          }
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <motion.button
          whileTap={{ scale: 0.98 }}
          className="btn ask-btn"
          onClick={submit}
          disabled={asking || !question.trim() || !hasSources}
          aria-label="Ask"
        >
          <Send size={14} /> Ask
        </motion.button>
      </div>
    </section>
  )
}

// The Mind-Change Log, made scannable: one line per belief change — marker,
// short title, signed memory count. Newest entry still types itself in.
import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'

const REST_COUNT = 3

function timeShort(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortTitle(title, max = 34) {
  return title.length > max ? title.slice(0, max - 1) + '…' : title
}

function line(e) {
  const verb = e.type === 'retraction' ? 'Retracted' : 'Learned'
  return `${verb} ${shortTitle(e.title)}`
}

function fullText(e) {
  if (e.type === 'retraction') {
    const links = e.links_removed != null ? ` · ${e.links_removed} links severed` : ''
    return `${timeShort(e.ts)} — Retracted “${e.title}” — ${e.nodes_removed} memories removed${links} — answers re-derived`
  }
  return `${timeShort(e.ts)} — Learned “${e.title}” — ${e.nodes_added} memories added`
}

function TypeIn({ text, reducedMotion }) {
  const [n, setN] = useState(reducedMotion ? text.length : 0)
  useEffect(() => {
    if (reducedMotion) return
    setN(0)
    const step = Math.max(1, Math.round(text.length / 30))
    const id = setInterval(() => {
      setN((cur) => {
        if (cur >= text.length) {
          clearInterval(id)
          return cur
        }
        return Math.min(text.length, cur + step)
      })
    }, 16)
    return () => clearInterval(id)
  }, [text, reducedMotion])
  return <>{text.slice(0, n)}</>
}

export default function LedgerPanel({ entries, reducedMotion }) {
  const [showAll, setShowAll] = useState(false)
  const newestTs = entries[0]?.ts
  const prevNewest = useRef(newestTs)
  const [flashTs, setFlashTs] = useState(null)

  useEffect(() => {
    if (newestTs && newestTs !== prevNewest.current) {
      prevNewest.current = newestTs
      setFlashTs(newestTs)
      const id = setTimeout(() => setFlashTs(null), 2400)
      return () => clearTimeout(id)
    }
  }, [newestTs])

  const visible = showAll ? entries : entries.slice(0, REST_COUNT)
  const hidden = entries.length - REST_COUNT

  return (
    <section className="panel ledger-panel" aria-label="Mind-change log">
      <div className="panel-header">
        <span className="panel-title">Mind-Change Log</span>
        <span className="mono ledger-count">{entries.length}</span>
      </div>
      <div className="panel-body ledger-body mono">
        {entries.length === 0 && (
          <div className="ledger-empty">
            Every time Aletheia learns — or un-learns — it gets a line here.
          </div>
        )}
        {visible.map((e) => {
          const isFlash = e.ts === flashTs
          const delta = e.type === 'retraction' ? `−${e.nodes_removed}` : `+${e.nodes_added}`
          return (
            <motion.div
              key={e.ts}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.25 }}
              className={`ledger-line ${e.type} ${isFlash ? 'flash' : ''}`}
              title={fullText(e)}
            >
              <span className="ledger-mark" aria-hidden="true" />
              <span className="ledger-what">
                {isFlash ? <TypeIn text={line(e)} reducedMotion={reducedMotion} /> : line(e)}
              </span>
              <span className={`ledger-delta ${e.type}`}>{delta}</span>
            </motion.div>
          )
        })}
        {hidden > 0 && (
          <button className="ledger-toggle" onClick={() => setShowAll((s) => !s)}>
            {showAll ? 'Show recent' : `Show all (${entries.length})`}
          </button>
        )}
      </div>
    </section>
  )
}

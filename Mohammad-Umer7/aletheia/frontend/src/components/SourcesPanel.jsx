// Sources: calm rows — hue dot, title, one badge. Everything else (kind, date,
// memory count, the Retract action) lives behind a click, one card at a time.
// Only status that can't wait (reading progress, errors) stays inline.
import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  FileX2,
  FlaskConical,
  Newspaper,
  Plus,
  Sparkles,
  StickyNote,
  X,
} from 'lucide-react'

const KIND_ICON = {
  study: FlaskConical,
  news: Newspaper,
  retraction: FileX2,
  'meta-analysis': BarChart3,
  note: StickyNote,
}

const HUE_VAR = ['var(--hue-0)', 'var(--hue-1)', 'var(--hue-2)', 'var(--hue-3)']

function timeShort(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function SourceRow({ source, expanded, onToggle, onRequestRetract, spotTarget }) {
  const Icon = KIND_ICON[source.kind] || StickyNote
  const retracted = source.trust === 'retracted'
  const ingesting = source.status === 'ingesting'
  const failed = source.status === 'error'

  return (
    <motion.div
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className={`source-item ${retracted ? 'retracted' : ''} ${expanded ? 'open' : ''}`}
      data-flight={spotTarget ? 'retract' : undefined}
    >
      <button className="source-rowline" onClick={onToggle} aria-expanded={expanded}>
        <span
          className="hue-dot"
          style={{ background: retracted ? 'var(--structural)' : HUE_VAR[source.color_index % 4] }}
        />
        <span className="source-title">{source.title}</span>
        {ingesting ? (
          <span className="badge ingesting">reading…</span>
        ) : failed ? (
          <span className="badge error">failed</span>
        ) : retracted ? (
          <span className="badge retracted-badge">retracted</span>
        ) : (
          <span className="badge trusted">trusted</span>
        )}
        <ChevronDown size={13} className="row-chevron" />
      </button>

      {ingesting && (
        <div className="ingest-progress">
          <div className="scan-bar" />
          <span>Aletheia is reading this source, ~60s</span>
        </div>
      )}
      {failed && <div className="ingest-error mono">{source.error}</div>}

      <AnimatePresence initial={false}>
        {expanded && !ingesting && (
          <motion.div
            className="source-detail"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <div className="source-meta mono">
              <Icon size={12} />
              <span className="kind">{source.kind}</span>
              <span className="dot">·</span>
              <span>{timeShort(source.added_at)}</span>
              <span className="dot">·</span>
              <span>{source.node_ids.length} memories</span>
            </div>

            {retracted && source.reason && (
              <div className="retract-reason mono">“{source.reason}”</div>
            )}

            {!retracted && !failed && (
              <div className="card-actions">
                <motion.button
                  whileTap={{ scale: 0.98 }}
                  className="btn ghost small"
                  onClick={() =>
                    onRequestRetract(
                      source,
                      source.id === 'helios_study' || source.id === 'meridian_post'
                        ? 'Journal retraction: fabricated data'
                        : '',
                    )
                  }
                >
                  Retract source
                </motion.button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// Aletheia noticed a new source disputes something it trusts — the human only
// confirms. The single most important card in the app.
function ConflictCard({ conflict, onRequestRetract, onDismiss }) {
  const { newSource, disputed, reason } = conflict
  return (
    <motion.div
      className="conflict-card"
      initial={{ opacity: 0, y: -14, height: 0 }}
      animate={{ opacity: 1, y: 0, height: 'auto' }}
      exit={{ opacity: 0, y: -8, height: 0 }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      role="alert"
    >
      <div className="conflict-head">
        <AlertTriangle size={14} />
        <span className="conflict-title">Conflict detected</span>
        <button
          className="conflict-dismiss"
          onClick={onDismiss}
          aria-label="Dismiss conflict"
          title="Dismiss"
        >
          <X size={13} />
        </button>
      </div>
      <p className="conflict-body">
        “{newSource.title}” disputes “{disputed.title}”: {reason}
      </p>
      <motion.button
        whileTap={{ scale: 0.98 }}
        className="btn conflict-retract"
        onClick={() => onRequestRetract(disputed, reason)}
        data-flight="conflict-retract"
      >
        Retract “{shortTitle(disputed.title)}”
      </motion.button>
    </motion.div>
  )
}

function shortTitle(title, max = 38) {
  return title.length > max ? `${title.slice(0, max - 1)}…` : title
}

function AddSourceForm({ onAdd, onClose }) {
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState('note')
  const [text, setText] = useState('')
  return (
    <motion.form
      className="add-form"
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.2 }}
      onSubmit={(e) => {
        e.preventDefault()
        onAdd({ title: title.trim(), kind, text: text.trim() })
        onClose()
      }}
    >
      <input
        className="field"
        placeholder="Source title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />
      <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="study">study</option>
        <option value="news">news</option>
        <option value="retraction">retraction</option>
        <option value="meta-analysis">meta-analysis</option>
        <option value="note">note</option>
      </select>
      <textarea
        className="field"
        rows={4}
        placeholder="Paste the source text — Aletheia will read it into memory."
        value={text}
        onChange={(e) => setText(e.target.value)}
        required
      />
      <div className="confirm-actions">
        <motion.button whileTap={{ scale: 0.98 }} className="btn" type="submit">
          Add source
        </motion.button>
        <motion.button whileTap={{ scale: 0.98 }} className="btn ghost" type="button" onClick={onClose}>
          Cancel
        </motion.button>
      </div>
    </motion.form>
  )
}

export default function SourcesPanel({
  sources,
  seeding,
  onRequestRetract,
  onAdd,
  onSeed,
  onIngestRetraction,
}) {
  const [adding, setAdding] = useState(false)
  const [expandedId, setExpandedId] = useState(null)
  const [dismissedConflicts, setDismissedConflicts] = useState(() => new Set())
  const hasJch = sources.some((s) => s.id === 'jch_retraction')
  const anyTrusted = sources.some((s) => s.trust === 'trusted')

  // A conflict is live while the disputed source is still trusted and the card
  // hasn't been waved away. Retracting or dismissing clears it naturally.
  const conflicts = []
  for (const s of sources) {
    if (s.status !== 'ready') continue
    for (const c of s.conflicts ?? []) {
      const disputed = sources.find((x) => x.id === c.disputed_source_id)
      const key = `${s.id}:${c.disputed_source_id}`
      if (disputed?.trust === 'trusted' && !dismissedConflicts.has(key)) {
        conflicts.push({ key, newSource: s, disputed, reason: c.reason })
      }
    }
  }

  return (
    <section className="panel sources-panel" aria-label="Sources">
      <div className="panel-header">
        <span className="panel-title">
          Sources{sources.length > 0 && <span className="mono title-count"> {sources.length}</span>}
        </span>
        <div className="header-actions">
          <motion.button
            whileTap={{ scale: 0.98 }}
            className="btn ghost icon-btn"
            onClick={onSeed}
            disabled={seeding}
            title="Load demo scenario — resets memory and reads three demo sources"
            aria-label="Load demo scenario"
            data-flight="seed"
          >
            <Sparkles size={14} />
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.98 }}
            className="btn ghost icon-btn"
            onClick={() => setAdding((a) => !a)}
            title="Add a source"
            aria-label="Add a source"
          >
            <Plus size={14} />
          </motion.button>
        </div>
      </div>
      <div className="panel-body">
        <AnimatePresence initial={false}>
          {conflicts.map((c) => (
            <ConflictCard
              key={c.key}
              conflict={c}
              onRequestRetract={onRequestRetract}
              onDismiss={() =>
                setDismissedConflicts((prev) => new Set(prev).add(c.key))
              }
            />
          ))}
        </AnimatePresence>

        <AnimatePresence>{adding && <AddSourceForm onAdd={onAdd} onClose={() => setAdding(false)} />}</AnimatePresence>

        {sources.length === 0 && !seeding && (
          <div className="sources-empty">
            <p>Nothing read yet.</p>
            <motion.button
              whileTap={{ scale: 0.98 }}
              className="btn"
              onClick={onSeed}
              data-flight="seed-primary"
            >
              <Sparkles size={13} /> Load demo scenario
            </motion.button>
          </div>
        )}
        {seeding && sources.length < 3 && (
          <div className="skeleton-stack">
            {[0, 1, 2].map((i) => (
              <div className="skeleton-card" key={i} style={{ animationDelay: `${i * 120}ms` }} />
            ))}
          </div>
        )}

        <AnimatePresence>
          {sources.map((s, i) => {
            const firstRetractable =
              s.trust === 'trusted' &&
              s.status === 'ready' &&
              sources.findIndex((x) => x.trust === 'trusted' && x.status === 'ready') === i
            return (
              <SourceRow
                key={s.id}
                source={s}
                spotTarget={firstRetractable}
                expanded={expandedId === s.id}
                onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
                onRequestRetract={onRequestRetract}
              />
            )
          })}
        </AnimatePresence>

        {anyTrusted && !hasJch && !seeding && (
          <motion.button
            whileTap={{ scale: 0.98 }}
            className="btn ghost retraction-arrives"
            onClick={onIngestRetraction}
            data-flight="notice"
          >
            <FileX2 size={13} /> A retraction notice arrives…
          </motion.button>
        )}
      </div>
    </section>
  )
}

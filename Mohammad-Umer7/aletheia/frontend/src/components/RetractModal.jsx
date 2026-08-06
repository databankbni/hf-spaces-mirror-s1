// The retraction confirm: a centered glass modal that makes un-learning feel
// like the deliberate, recorded act it is.
import { useState } from 'react'
import { motion } from 'framer-motion'
import { FileX2 } from 'lucide-react'

export default function RetractModal({ source, defaultReason, onConfirm, onCancel }) {
  const [reason, setReason] = useState(defaultReason || '')
  return (
    <motion.div
      className="modal-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.16 }}
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
      aria-label={`Retract ${source.title}`}
    >
      <motion.div
        className="modal retract-modal"
        initial={{ opacity: 0, scale: 0.96, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 6 }}
        transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-title">
          <FileX2 size={15} />
          Retract “{source.title}”?
        </div>
        <p className="modal-body">
          Aletheia will unlearn everything derived from this source. This action
          is recorded in the Mind-Change Log.
        </p>
        <input
          className="field"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason for retraction"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter' && reason.trim()) onConfirm(reason.trim())
            if (e.key === 'Escape') onCancel()
          }}
        />
        <div className="modal-actions">
          <motion.button whileTap={{ scale: 0.98 }} className="btn ghost" onClick={onCancel}>
            Cancel
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.98 }}
            className="btn danger"
            disabled={!reason.trim()}
            onClick={() => onConfirm(reason.trim())}
          >
            Retract source
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  )
}

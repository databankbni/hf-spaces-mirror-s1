// Glass toasts, bottom-right, verb-first copy. One hook, one renderer.
import { useCallback, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, FileX2, Loader2 } from 'lucide-react'

const ICONS = {
  ok: CheckCircle2,
  retract: FileX2,
  error: AlertTriangle,
  busy: Loader2,
}

export function useToasts() {
  const [toasts, setToasts] = useState([])
  const nextId = useRef(1)

  const push = useCallback((toast) => {
    const id = nextId.current++
    setToasts((t) => [...t, { id, tone: 'ok', ...toast }])
    const ttl = toast.ttl ?? 4500
    if (ttl > 0) {
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ttl)
    }
    return id
  }, [])

  const dismiss = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id))
  }, [])

  return { toasts, push, dismiss }
}

export function Toasts({ toasts, dismiss }) {
  return (
    <div className="toasts">
      <AnimatePresence>
        {toasts.map((t) => {
          const Icon = ICONS[t.tone] || CheckCircle2
          return (
            <motion.button
              key={t.id}
              className={`toast tone-${t.tone}`}
              onClick={() => dismiss(t.id)}
              initial={{ opacity: 0, y: 16, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.97 }}
              transition={{ duration: 0.22, ease: 'easeOut' }}
            >
              <Icon size={15} className={t.tone === 'busy' ? 'spin' : ''} />
              <span>{t.text}</span>
            </motion.button>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

// The live retraction ticker: counts up beside the ledger while the sky bleeds
// red, landing exactly on the real numbers the backend measured.
import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'

const easeOut = (t) => 1 - Math.pow(1 - t, 3)

export default function RetractTicker({ nodes, links, duration, onDone }) {
  const [shown, setShown] = useState({ nodes: 0, links: 0 })
  const [done, setDone] = useState(false)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    let raf
    const t0 = performance.now()
    const frame = (now) => {
      const t = Math.min(1, (now - t0) / Math.max(1, duration))
      const e = easeOut(t)
      setShown({ nodes: Math.round(nodes * e), links: Math.round(links * e) })
      if (t < 1) {
        raf = requestAnimationFrame(frame)
      } else {
        setDone(true)
        onDoneRef.current?.()
      }
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [nodes, links, duration])

  return (
    <motion.div
      className={`retract-ticker mono ${done ? 'done' : ''}`}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.18 }}
      aria-live="polite"
    >
      <span className="tick-num">{shown.nodes}</span> memories removed
      <span className="tick-sep">·</span>
      <span className="tick-num">{shown.links}</span> links severed
    </motion.div>
  )
}

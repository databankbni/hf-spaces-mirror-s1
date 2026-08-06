// The spotlight: dims the whole stage except a rounded cutout that glides to
// the control the active flight step needs. Purely visual — pointer-events
// pass straight through, so it guides without ever getting in the way.
import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

const PAD = 9
const SPRING = { type: 'spring', stiffness: 210, damping: 26, mass: 0.9 }

function measure(selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel)
    if (el) {
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.height > 0) {
        return {
          x: r.left - PAD,
          y: r.top - PAD,
          w: r.width + PAD * 2,
          h: r.height + PAD * 2,
        }
      }
    }
  }
  return null
}

export default function FlightSpotlight({ selectors, hint, paused, reducedMotion, forceHintBelow }) {
  const [rect, setRect] = useState(null)

  useEffect(() => {
    if (paused) {
      setRect(null)
      return
    }
    let alive = true
    const update = () => {
      if (!alive) return
      setRect(measure(selectors))
    }
    update()
    const id = setInterval(update, 280) // targets move (panels scroll, cards expand)
    window.addEventListener('resize', update)
    return () => {
      alive = false
      clearInterval(id)
      window.removeEventListener('resize', update)
    }
  }, [selectors, paused])

  const show = !paused && rect
  const hintBelow = rect ? forceHintBelow || rect.y < 130 : false

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="spotlight"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reducedMotion ? 0 : 0.35 }}
        >
          <svg className="spotlight-svg" width="100%" height="100%">
            <defs>
              <mask id="spotlight-mask">
                <rect width="100%" height="100%" fill="white" />
                <motion.rect
                  fill="black"
                  rx={12}
                  initial={false}
                  animate={{ x: rect.x, y: rect.y, width: rect.w, height: rect.h }}
                  transition={reducedMotion ? { duration: 0 } : SPRING}
                />
              </mask>
            </defs>
            <rect
              width="100%"
              height="100%"
              fill="rgba(8, 5, 20, 0.62)"
              mask="url(#spotlight-mask)"
            />
            <motion.rect
              className={`spotlight-ring ${reducedMotion ? '' : 'breathing'}`}
              fill="none"
              rx={12}
              initial={false}
              animate={{ x: rect.x, y: rect.y, width: rect.w, height: rect.h }}
              transition={reducedMotion ? { duration: 0 } : SPRING}
            />
          </svg>

          <motion.div
            className="spotlight-hint mono"
            initial={false}
            animate={{
              x: Math.min(Math.max(rect.x + rect.w / 2, 150), window.innerWidth - 150),
              y: hintBelow ? rect.y + rect.h + 14 : rect.y - 14,
            }}
            transition={reducedMotion ? { duration: 0 } : SPRING}
            style={{ translateX: '-50%', translateY: hintBelow ? '0%' : '-100%' }}
          >
            {hint}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

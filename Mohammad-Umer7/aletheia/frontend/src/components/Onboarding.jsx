// First-run onboarding: three slides, one idea each, in Aletheia's voice.
// Shows on every visit (nothing persisted) and is re-openable from the header.
import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight, Sparkles } from 'lucide-react'

const SLIDES = [
  {
    key: 'what',
    visual: (
      <svg width="120" height="64" viewBox="0 0 120 64">
        <path d="M14 44 L40 18 L64 40 L92 14 L108 34" stroke="#7C6CFF" strokeWidth="1" fill="none" opacity="0.55" />
        {[[14, 44], [40, 18], [64, 40], [92, 14], [108, 34]].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="3.4" fill="#7C6CFF">
            <animate attributeName="opacity" values="0.4;1;0.4" dur="2.4s" begin={`${i * 0.3}s`} repeatCount="indefinite" />
          </circle>
        ))}
      </svg>
    ),
    title: 'This is Aletheia.',
    body:
      'A research assistant that answers only from sources you feed it — and tells you, every time, exactly which sources an answer stands on.',
  },
  {
    key: 'stars',
    visual: (
      <svg width="120" height="64" viewBox="0 0 120 64">
        {[
          [24, 30, '#7C6CFF'], [44, 16, '#7C6CFF'], [40, 46, '#7C6CFF'],
          [70, 24, '#C86CFF'], [86, 40, '#C86CFF'],
          [102, 18, '#5FD4E8'], [60, 52, '#5FD4E8'],
        ].map(([x, y, c], i) => (
          <g key={i}>
            <circle cx={x} cy={y} r="4" fill={c} opacity="0.9" />
            <circle cx={x} cy={y} r="1.3" fill="#EDEAF7" />
          </g>
        ))}
        <path d="M24 30 L44 16 M24 30 L40 46 M70 24 L86 40 M44 16 L70 24 M40 46 L60 52" stroke="#8B84A8" strokeWidth="0.7" opacity="0.4" fill="none" />
      </svg>
    ),
    title: 'Every star is something it knows.',
    body:
      'The constellation is its real memory, drawn live from a knowledge graph on your machine. Stars wear the color of the source that taught them — hover any star to read it.',
  },
  {
    key: 'forget',
    visual: (
      <svg width="120" height="64" viewBox="0 0 120 64">
        {[[30, 22], [52, 40], [42, 54]].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="4" fill="#FF4D5E">
            <animate attributeName="r" values="4;1.6;4" dur="2.6s" begin={`${i * 0.4}s`} repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.9;0.15;0.9" dur="2.6s" begin={`${i * 0.4}s`} repeatCount="indefinite" />
          </circle>
        ))}
        {[[84, 20, '#5FD4E8'], [100, 38, '#5FD4E8'], [88, 52, '#FFB454']].map(([x, y, c], i) => (
          <g key={i}>
            <circle cx={x} cy={y} r="4" fill={c} opacity="0.95" />
            <circle cx={x} cy={y} r="1.3" fill="#EDEAF7" />
          </g>
        ))}
      </svg>
    ),
    title: 'And it can take knowledge back.',
    body:
      'When a source turns out to be wrong, retract it. Its stars die on screen, the discredited claims become unreachable, and the next answer is re-derived from what still holds.',
  },
]

export default function Onboarding({ open, onClose, onStartFlight }) {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (open) setI(0)
  }, [open])
  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight' && i < SLIDES.length - 1) setI(i + 1)
      if (e.key === 'ArrowLeft' && i > 0) setI(i - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, i, onClose])

  if (!open) return null
  const slide = SLIDES[i]
  const last = i === SLIDES.length - 1

  return (
    <motion.div
      className="onboarding-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <motion.div
        className="onboarding-card"
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.28, ease: 'easeOut' }}
      >
        <div className="ob-brand mono">✦ ALETHEIA · the un-forgetting</div>
        <AnimatePresence mode="wait">
          <motion.div
            key={slide.key}
            className="ob-slide"
            initial={{ opacity: 0, x: 26 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -26 }}
            transition={{ duration: 0.22, ease: 'easeOut' }}
          >
            <div className="ob-visual">{slide.visual}</div>
            <h2 className="ob-title">{slide.title}</h2>
            <p className="ob-body">{slide.body}</p>
          </motion.div>
        </AnimatePresence>

        <div className="ob-footer">
          <div className="ob-dots">
            {SLIDES.map((s, d) => (
              <button
                key={s.key}
                className={`ob-dot ${d === i ? 'active' : ''}`}
                onClick={() => setI(d)}
                aria-label={`slide ${d + 1}`}
              />
            ))}
          </div>
          <div className="ob-actions">
            <button className="btn ghost" onClick={onClose}>
              {last ? 'Explore on my own' : 'Skip'}
            </button>
            {last ? (
              <motion.button
                whileTap={{ scale: 0.98 }}
                className="btn"
                onClick={() => {
                  onStartFlight()
                  onClose()
                }}
              >
                <Sparkles size={14} /> Start the guided flight
              </motion.button>
            ) : (
              <motion.button whileTap={{ scale: 0.98 }} className="btn" onClick={() => setI(i + 1)}>
                Next <ArrowRight size={14} />
              </motion.button>
            )}
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

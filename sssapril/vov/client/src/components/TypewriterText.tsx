/** 打字机效果组件
 *  逐字显示文字，模拟"写信"的流式输出
 *  当 pacing 不是 typewriter 时，立即显示全文
 */

import { useEffect, useState } from 'react'

interface TypewriterTextProps {
  text: string
  speed?: number        // 每个字的间隔（ms），默认 60
  enabled?: boolean     // 是否启用打字机效果；false 时立即显示
  className?: string
  onDone?: () => void
}

export default function TypewriterText({
  text,
  speed = 60,
  enabled = true,
  className,
  onDone,
}: TypewriterTextProps) {
  const [displayed, setDisplayed] = useState(enabled ? '' : text)
  const [done, setDone] = useState(!enabled)

  useEffect(() => {
    // text 变化时重置
    if (!enabled) {
      setDisplayed(text)
      setDone(true)
      return
    }
    setDisplayed('')
    setDone(false)
    let i = 0
    const id = setInterval(() => {
      i++
      if (i >= text.length) {
        setDisplayed(text)
        setDone(true)
        clearInterval(id)
        onDone?.()
      } else {
        setDisplayed(text.slice(0, i))
      }
    }, speed)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, speed, enabled])

  return (
    <span className={className}>
      {displayed}
      {!done && <span className="typewriter-cursor">▍</span>}
    </span>
  )
}

/** 主题管理 Hook
 *  v3 三层架构：
 *  - config: 用户配置的 color + style + mode
 *  - derived: 从当前 style 派生的 layout / pacing / chrome
 *  组件可通过 useTheme() 读取这些字段做 JSX 切换和动效应用
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import type {
  ThemeConfig,
  ThemeDerived,
  ColorScheme,
  StyleMode,
  DisplayMode,
  LetterFont,
} from '../themes'
import { loadTheme, saveTheme, applyTheme } from '../themes'
import { styleSchemes } from '../themes'

export function useTheme() {
  const [config, setConfig] = useState<ThemeConfig>(loadTheme)

  // 应用主题到 DOM
  useEffect(() => {
    applyTheme(config)
    saveTheme(config)
  }, [config])

  // 派生字段：从当前 style 解析 layout / pacing / chrome
  // 用户可在 config 里覆盖（可选），未指定时使用 style 默认值
  const derived: ThemeDerived = useMemo(() => {
    const style = styleSchemes[config.style][config.mode]
    return {
      layout: config.layout ?? style.layout,
      pacing: config.pacing ?? style.pacing,
      chrome: {
        ...style.chrome,
        ...(config.chrome ?? {}),
      },
    }
  }, [config])

  const setColor = useCallback((color: ColorScheme) => {
    setConfig(prev => ({ ...prev, color }))
  }, [])

  const setStyle = useCallback((style: StyleMode) => {
    setConfig(prev => ({ ...prev, style }))
  }, [])

  const toggleMode = useCallback(() => {
    setConfig(prev => ({ ...prev, mode: prev.mode === 'light' ? 'dark' : 'light' }))
  }, [])

  const setMode = useCallback((mode: DisplayMode) => {
    setConfig(prev => ({ ...prev, mode }))
  }, [])

  /** 切换信纸字体（letter 风格使用，但任何风格下都可切换） */
  const setLetterFont = useCallback((letterFont: LetterFont) => {
    setConfig(prev => ({ ...prev, letterFont }))
  }, [])

  return { config, derived, setColor, setStyle, toggleMode, setMode, setLetterFont }
}

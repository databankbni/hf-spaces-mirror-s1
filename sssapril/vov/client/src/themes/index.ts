/** 主题系统入口 — 注册 + 应用 */

import type { ThemeConfig } from './types'
import { DEFAULT_THEME } from './types'
import { colorSchemes } from './colors'
import { styleSchemes, LETTER_FONTS, DEFAULT_LETTER_FONT, type LetterFont } from './styles'
import { THEME_PRESETS, PRESET_BY_ID } from './presets'

const STORAGE_KEY = 'vov-theme'

/** 从 localStorage 加载主题配置 */
export function loadTheme(): ThemeConfig {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved)
      return { ...DEFAULT_THEME, ...parsed }
    }
  } catch {}
  return DEFAULT_THEME
}

/** 保存主题配置到 localStorage */
export function saveTheme(config: ThemeConfig): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}

/** 将主题配置应用到 DOM */
export function applyTheme(config: ThemeConfig): void {
  const root = document.documentElement

  // 1. 设置 data 属性（用于 CSS 选择器）
  root.setAttribute('data-color', config.color)
  root.setAttribute('data-style', config.style)

  // 2. 设置亮/暗模式
  if (config.mode === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }

  // 3. 只覆盖色系变量（primary/accent/secondary 相关 + paper 信纸字段）
  const colors = colorSchemes[config.color][config.mode]
  root.style.setProperty('--primary', colors.primary)
  root.style.setProperty('--primary-foreground', colors.primaryForeground)
  root.style.setProperty('--accent', colors.accent)
  root.style.setProperty('--accent-foreground', colors.accentForeground)
  root.style.setProperty('--secondary', colors.secondary)
  root.style.setProperty('--secondary-foreground', colors.secondaryForeground)
  root.style.setProperty('--ring', colors.ring)
  root.style.setProperty('--input', colors.input)
  // v3.1 — paper 信纸字段（letter 风格使用）
  root.style.setProperty('--paper', colors.paper)
  root.style.setProperty('--paper-ink', colors.paperInk)
  root.style.setProperty('--paper-rule', colors.paperRule)

  // 4. 风格相关 — 设置 radius、背景渐变、阴影等
  const style = styleSchemes[config.style][config.mode]
  root.style.setProperty('--radius', style.radius)
  root.style.setProperty('--bg-gradient', style.backgroundGradient)
  root.style.setProperty('--shadow', style.shadow)
  root.style.setProperty('--font-stack', style.fontStack)
  root.style.setProperty('--paper-texture', style.paperTexture)
  root.style.setProperty('--line-style', style.lineStyle)
  root.style.setProperty('--line-width', style.lineWidth)
  root.style.setProperty('--shadow-style', style.shadowStyle)
  root.style.setProperty('--accent-decoration', style.accentDecoration)

  // 4.5 — 信纸字体（letter 风格使用）— 暴露为 CSS 变量
  //       任何风格下都设置，切回 letter 时仍生效
  const letterFontKey: LetterFont = config.letterFont ?? DEFAULT_LETTER_FONT
  const letterFont = LETTER_FONTS[letterFontKey]
  root.style.setProperty('--letter-font', letterFont.stack)
  root.setAttribute('data-letter-font', letterFontKey)

  // 5. v3 三层架构 — 把 layout / pacing / chrome 暴露为 data 属性
  //    CSS 可用 [data-layout="scattered"] 选择；JSX 用 useTheme().derived 读取
  const layout = config.layout ?? style.layout
  const pacing = config.pacing ?? style.pacing
  const chrome = { ...style.chrome, ...(config.chrome ?? {}) }
  root.setAttribute('data-layout', layout)
  root.setAttribute('data-pacing', pacing)
  root.setAttribute('data-show-logo', String(chrome.showLogo))
  root.setAttribute('data-show-subtitle', String(chrome.showSubtitle))
  root.setAttribute('data-show-date-row', String(chrome.showDateRow))
  root.setAttribute('data-show-footer', String(chrome.showFooter))
  root.setAttribute('data-show-dividers', String(chrome.showDividers))
}

/**
 * 应用预设主题（一键切换）
 * @param presetId presets.ts 中定义的预设 id
 * @returns 应用后的 ThemeConfig；如果 preset 未实现，返回 null
 */
export function applyPreset(presetId: string): ThemeConfig | null {
  const preset = PRESET_BY_ID[presetId]
  if (!preset) return null
  if (!preset.implemented) return null
  applyTheme(preset.config)
  saveTheme(preset.config)
  return preset.config
}

/** 导出供外部使用 */
export { colorSchemes, colorSchemeInfo } from './colors'
export { styleSchemes, styleSchemeInfo, LETTER_FONTS, DEFAULT_LETTER_FONT } from './styles'
export type { LetterFont, LetterFontOption } from './styles'
export { THEME_PRESETS, PRESET_BY_ID } from './presets'
export type {
  ThemeConfig,
  ThemePreset,
  ThemeDerived,
  ColorScheme,
  StyleMode,
  DisplayMode,
  LayoutStrategy,
  NarrativePacing,
  ChromeConfig,
  StyleVariables,
  ColorVariables,
} from './types'
export { DEFAULT_THEME } from './types'


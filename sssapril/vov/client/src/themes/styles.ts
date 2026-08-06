/** 风格定义 — 三层架构：
 *  1. 视觉质感（颜色/字体/边框/阴影/纹理/装饰）
 *  2. 布局策略（layout：newspaper / scattered / grid / compact / masonry）
 *  3. 叙事节奏（pacing：instant / fade-in / typewriter / line-by-line）
 *  + 装饰元素开关（chrome）
 *
 *  颜色变量由 colors.ts 控制，不在此处覆盖。
 */

import type { StyleMode, StyleVariables, ChromeConfig } from './types'

type StyleSet = { light: StyleVariables; dark: StyleVariables }

/** 标准报纸 chrome（vov logo + 报头副标题 + 日期行 + 报尾 + 导航 + 横线分割全显示） */
const newspaperChrome: ChromeConfig = {
  showLogo: true,
  showSubtitle: true,
  showDateRow: true,
  showFooter: true,
  showNav: true,
  showDividers: true,
}

/** 信笺 chrome（隐藏 vov logo / 副标题 / 报尾 / 导航，露出"信笺头 + 落款"位置） */
const letterChrome: ChromeConfig = {
  showLogo: false,
  showSubtitle: false,
  showDateRow: false,
  showFooter: false,
  showNav: true,   // 保留简单导航（让用户能切换主题）
  showDividers: false,
  letterhead: {
    greeting: '亲爱的创作者，',
    signature: '—— 来自 vov 的信',
  },
}

/** 默认风格 — 报纸：清晰、实心、印刷感 */
const defaultStyle: StyleSet = {
  light: {
    background: '#f5f0e8',
    card: '#fbf6ec',
    cardForeground: '#2c2416',
    foreground: '#2c2416',
    muted: '#ede5d0',
    mutedForeground: '#6b5e4a',
    border: 'rgba(212, 204, 186, 1)',
    popover: '#fbf6ec',
    popoverForeground: '#2c2416',
    destructive: '#c14e2f',
    destructiveForeground: '#fbf6ec',
    shadow: '0 2px 8px rgba(44, 36, 22, 0.06)',
    radius: '0.7rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '1',
    backgroundGradient: 'none',
    fontStack: '"Georgia", "Times New Roman", "Songti SC", "STSong", serif',
    paperTexture: 'none',
    lineStyle: 'solid',
    lineWidth: '1px',
    shadowStyle: 'soft',
    accentDecoration: 'none',
    // v3 三层架构
    layout: 'newspaper',
    pacing: 'instant',
    chrome: newspaperChrome,
  },
  dark: {
    background: '#1a1612',
    card: '#221d17',
    cardForeground: '#d4cab5',
    foreground: '#d4cab5',
    muted: '#2a241c',
    mutedForeground: '#9b8c74',
    border: 'rgba(212, 202, 181, 0.14)',
    popover: '#221d17',
    popoverForeground: '#d4cab5',
    destructive: '#c14e2f',
    destructiveForeground: '#1a1612',
    shadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
    radius: '0.7rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '1',
    backgroundGradient: 'none',
    fontStack: '"Georgia", "Times New Roman", "Songti SC", "STSong", serif',
    paperTexture: 'none',
    lineStyle: 'solid',
    lineWidth: '1px',
    shadowStyle: 'soft',
    accentDecoration: 'none',
    // v3
    layout: 'newspaper',
    pacing: 'instant',
    chrome: newspaperChrome,
  },
}

/** 柔和风格 — 在报纸基础上稍作柔化：更柔的米色底、更柔的阴影、更大的圆角
 *  不做玻璃模糊（不符合报纸的实体印刷感）
 *  注意：颜色变量不在此覆盖，由 colors.ts 和 index.css 的 data-style 选择器控制 */
const softStyle: StyleSet = {
  light: {
    background: '#f8f2e6',
    card: '#fbf6ec',
    cardForeground: '#2c2416',
    foreground: '#2c2416',
    muted: '#efe8d6',
    mutedForeground: '#7a6a55',
    border: 'rgba(212, 204, 186, 0.7)',
    popover: '#fbf6ec',
    popoverForeground: '#2c2416',
    destructive: '#c14e2f',
    destructiveForeground: '#fbf6ec',
    shadow: '0 2px 16px rgba(44, 36, 22, 0.05)',
    radius: '1rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '0.7',
    backgroundGradient: 'none',
    fontStack: '"Georgia", "Times New Roman", "Songti SC", "STSong", serif',
    paperTexture: 'none',
    lineStyle: 'solid',
    lineWidth: '1px',
    shadowStyle: 'soft',
    accentDecoration: 'none',
    // v3
    layout: 'newspaper',
    pacing: 'fade-in',
    chrome: newspaperChrome,
  },
  dark: {
    background: '#1f1a14',
    card: '#2a241c',
    cardForeground: '#d4cab5',
    foreground: '#d4cab5',
    muted: '#2a241c',
    mutedForeground: '#9b8c74',
    border: 'rgba(212, 202, 181, 0.12)',
    popover: '#2a241c',
    popoverForeground: '#d4cab5',
    destructive: '#c14e2f',
    destructiveForeground: '#1a1612',
    shadow: '0 2px 16px rgba(0, 0, 0, 0.18)',
    radius: '1rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '0.5',
    backgroundGradient: 'none',
    fontStack: '"Georgia", "Times New Roman", "Songti SC", "STSong", serif',
    paperTexture: 'none',
    lineStyle: 'solid',
    lineWidth: '1px',
    shadowStyle: 'soft',
    accentDecoration: 'none',
    // v3
    layout: 'newspaper',
    pacing: 'fade-in',
    chrome: newspaperChrome,
  },
}

/**
 * 手抄报风格 — 便签贴纸 + 手写字体 + 虚线边
 *  视觉：贴纸感、微微旋转、硬阴影
 *  布局：scattered（错落）
 *  节奏：instant（即时出现）
 *  chrome：保留报纸装饰（报头、报尾）
 */
const handcraftStyle: StyleSet = {
  light: {
    background: '#faf3dc',
    card: '#fdf6e3',
    cardForeground: '#3a2a1a',
    foreground: '#3a2a1a',
    muted: '#f0e3c0',
    mutedForeground: '#8b6f47',
    border: 'rgba(193, 78, 47, 0.5)',
    popover: '#fdf6e3',
    popoverForeground: '#3a2a1a',
    destructive: '#c14e2f',
    destructiveForeground: '#fdf6e3',
    shadow: '4px 4px 0 rgba(193, 78, 47, 0.85)',
    radius: '0.4rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '1',
    backgroundGradient: 'none',
    fontStack: '"ZCOOL KuaiLe", "Ma Shan Zheng", "Caveat", "KaiTi", "楷体", serif',
    paperTexture: 'paper',
    lineStyle: 'dashed',
    lineWidth: '2px',
    shadowStyle: 'hard',
    accentDecoration: 'tape',
    // v3
    layout: 'scattered',
    pacing: 'instant',
    chrome: newspaperChrome,
  },
  dark: {
    background: '#2a1f12',
    card: '#3d2c18',
    cardForeground: '#f5e8c8',
    foreground: '#f5e8c8',
    muted: '#3a2a1a',
    mutedForeground: '#c4a875',
    border: 'rgba(212, 165, 116, 0.45)',
    popover: '#3d2c18',
    popoverForeground: '#f5e8c8',
    destructive: '#e07a5f',
    destructiveForeground: '#2a1f12',
    shadow: '4px 4px 0 rgba(0, 0, 0, 0.7)',
    radius: '0.4rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '0.8',
    backgroundGradient: 'none',
    fontStack: '"ZCOOL KuaiLe", "Ma Shan Zheng", "Caveat", "KaiTi", "楷体", serif',
    paperTexture: 'paper',
    lineStyle: 'dashed',
    lineWidth: '2px',
    shadowStyle: 'hard',
    accentDecoration: 'tape',
    // v3
    layout: 'scattered',
    pacing: 'instant',
    chrome: newspaperChrome,
  },
}

/**
 * 手绘线条风格 — dashed 边 + 角部涂鸦 + 网格背景
 *  布局：grid（规则网格）
 *  节奏：line-by-line（逐行显现）
 */
const lineArtStyle: StyleSet = {
  ...defaultStyle,
  light: {
    ...defaultStyle.light,
    lineStyle: 'dashed',
    paperTexture: 'grid',
    accentDecoration: 'doodle',
    layout: 'grid',
    pacing: 'line-by-line',
  },
  dark: {
    ...defaultStyle.dark,
    lineStyle: 'dashed',
    paperTexture: 'grid',
    accentDecoration: 'doodle',
    layout: 'grid',
    pacing: 'line-by-line',
  },
}

/**
 * 极简单色风格 — 纯白底、极细线、无装饰
 *  布局：compact（紧凑单列）
 *  节奏：instant
 */
const minimalStyle: StyleSet = {
  ...defaultStyle,
  light: {
    ...defaultStyle.light,
    shadowStyle: 'none',
    radius: '0.25rem',
    layout: 'compact',
    pacing: 'instant',
  },
  dark: {
    ...defaultStyle.dark,
    shadowStyle: 'none',
    radius: '0.25rem',
    layout: 'compact',
    pacing: 'instant',
  },
}

/**
 * 复古信纸风格 — 错落布局 + 打字机节奏 + 隐藏 logo + 信笺头
 *  视觉：信纸质感 + 楷体 + 印章
 *  布局：scattered（错落，每张卡片微微旋转、错位）
 *  节奏：typewriter（打字机：每行字像写信一样流式输出）
 *  chrome：隐藏 vov logo / 副标题 / 报尾 / 日期行，露出"信笺头 + 落款"
 *
 *  v3.1：纸色由色系决定（白信纸/米黄信纸/玫瑰信纸…）
 *  实际颜色用 var(--paper) / var(--paper-ink) 引用，CSS 负责最终渲染
 */
const letterStyle: StyleSet = {
  light: {
    // 用 CSS 变量占位（CSS 会在 [data-style="letter"] 下用 var(--paper) 覆盖）
    background: 'var(--paper)',
    card: 'var(--paper)',
    cardForeground: 'var(--paper-ink)',
    foreground: 'var(--paper-ink)',
    muted: 'var(--paper)',
    mutedForeground: 'var(--paper-ink)',
    border: 'var(--paper-rule)',
    popover: 'var(--paper)',
    popoverForeground: 'var(--paper-ink)',
    destructive: '#c14e2f',
    destructiveForeground: 'var(--paper)',
    shadow: '0 1px 0 var(--paper-rule)',
    radius: '0.2rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '1',
    backgroundGradient: 'none',
    fontStack: '"Ma Shan Zheng", "ZCOOL KuaiLe", "KaiTi", "楷体", "Noto Serif SC", "STKaiti", serif',
    paperTexture: 'ruled',           // 横线信纸
    lineStyle: 'solid',              // 信纸边框是细实线
    lineWidth: '1px',
    shadowStyle: 'soft',
    accentDecoration: 'fold',        // 折角
    // v3 三层架构
    layout: 'scattered',             // 错落布局
    pacing: 'typewriter',            // 打字机节奏
    chrome: letterChrome,            // 隐藏 logo / 副标题 / 报尾
  },
  dark: {
    background: 'var(--paper)',
    card: 'var(--paper)',
    cardForeground: 'var(--paper-ink)',
    foreground: 'var(--paper-ink)',
    muted: 'var(--paper)',
    mutedForeground: 'var(--paper-ink)',
    border: 'var(--paper-rule)',
    popover: 'var(--paper)',
    popoverForeground: 'var(--paper-ink)',
    destructive: '#e07a5f',
    destructiveForeground: 'var(--paper)',
    shadow: '0 1px 0 rgba(0, 0, 0, 0.4)',
    radius: '0.2rem',
    cardBlur: '0px',
    cardOpacity: '1',
    borderOpacity: '1',
    backgroundGradient: 'none',
    fontStack: '"Ma Shan Zheng", "ZCOOL KuaiLe", "KaiTi", "楷体", "Noto Serif SC", "STKaiti", serif',
    paperTexture: 'ruled',
    lineStyle: 'solid',
    lineWidth: '1px',
    shadowStyle: 'soft',
    accentDecoration: 'fold',
    // v3
    layout: 'scattered',
    pacing: 'typewriter',
    chrome: letterChrome,
  },
}

export const styleSchemes: Record<StyleMode, StyleSet> = {
  default: defaultStyle,
  soft: softStyle,
  handcraft: handcraftStyle,
  lineArt: lineArtStyle,
  minimal: minimalStyle,
  letter: letterStyle,
}

/** 风格展示信息 */
export const styleSchemeInfo: Record<StyleMode, { label: string; description: string; emoji: string }> = {
  default:   { label: '经典报纸', description: '印刷感、衬线、实心卡片',       emoji: '📰' },
  soft:      { label: '柔和米色', description: '柔米底色、柔阴影、淡入',         emoji: '🌾' },
  handcraft: { label: '手抄报',   description: '便签贴纸 + 手写字体 + 错落',     emoji: '✂️' },
  lineArt:   { label: '手绘线条', description: 'dashed 边 + 网格 + 逐行',        emoji: '✏️' },
  minimal:   { label: '极简单色', description: '纯白底、紧凑列表、无装饰',       emoji: '◻️' },
  letter:    { label: '复古信纸', description: '错落 + 打字机 + 隐藏 logo + 信笺头', emoji: '✉️' },
}

/* ════════════════════════════════════════════════════════════
   信纸字体注册表 — 用户可在主题选择器中切换
   三个常见中文字体栈，覆盖 Windows / Mac / Linux
   ════════════════════════════════════════════════════════════ */

export interface LetterFontOption {
  /** UI 显示名 */
  label: string
  /** 字体描述（hover 提示） */
  description: string
  /** CSS font-family 栈（含跨平台 fallback） */
  stack: string
}

export const LETTER_FONTS = {
  kaiti: {
    label: '楷体',
    description: '传统书法体，呼应"信"的味道',
    stack: '"KaiTi", "STKaiti", "楷体", "BiauKai", "Noto Serif SC", "Source Han Serif CN", serif',
  },
  songti: {
    label: '宋体',
    description: '端庄正式，传统印刷感',
    stack: '"SongTi", "STSong", "宋体", "SimSun", "Noto Serif SC", "Source Han Serif CN", serif',
  },
  heiti: {
    label: '黑体',
    description: '现代简洁，清晰易读',
    stack: '"Heiti", "STHeiti", "黑体", "SimHei", "PingFang SC", "Noto Sans SC", "Source Han Sans CN", sans-serif',
  },
} as const satisfies Record<string, LetterFontOption>

export type LetterFont = keyof typeof LETTER_FONTS

export const DEFAULT_LETTER_FONT: LetterFont = 'kaiti'


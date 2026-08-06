/** 色系定义 — 每个色系提供亮/暗两套主色变量
 *  设计准则：报纸风格。墨色、棕褐、橄榄、酒红、青灰五种低饱和度偏暖色。
 *  整体保持低调印刷感，不使用现代 UI 的高饱和荧光色。
 *
 *  v3.1：每个色系额外提供 paper / paperInk / paperRule 三个字段
 *  让 letter 风格能使用色系提供"纸张"颜色（白信纸/米黄信纸/玫瑰信纸…）
 *  即：letter + 5 色系 = 5 种信纸效果
 */

import type { ColorScheme, ColorVariables } from './types'

type ColorSet = { light: ColorVariables; dark: ColorVariables }

const ink: ColorSet = {
  light: {
    primary: '#1f1b16',
    primaryForeground: '#fbf6ec',
    accent: '#e8e0cd',
    accentForeground: '#1f1b16',
    secondary: '#efe8d6',
    secondaryForeground: '#3a3024',
    ring: 'rgba(31, 27, 22, 0.28)',
    input: '#d4cab5',
    // 纸：白信纸（最正统）
    paper: '#fbf6ec',
    // 墨：近纯黑（更易读）
    paperInk: '#0a0805',
    paperRule: 'rgba(10, 8, 5, 0.22)',
  },
  dark: {
    primary: '#d4cab5',
    primaryForeground: '#1a1612',
    accent: '#2a241c',
    accentForeground: '#d4cab5',
    secondary: '#221d17',
    secondaryForeground: '#b8ac95',
    ring: 'rgba(212, 202, 181, 0.32)',
    input: 'rgba(212, 202, 181, 0.2)',
    paper: '#1a1612',
    paperInk: '#e8dcc4',
    paperRule: 'rgba(212, 202, 181, 0.1)',
  },
}

const sepia: ColorSet = {
  light: {
    primary: '#7a4f2c',
    primaryForeground: '#fbf6ec',
    accent: '#e8d8c0',
    accentForeground: '#5a3a1f',
    secondary: '#efe2cc',
    secondaryForeground: '#5a3a1f',
    ring: 'rgba(122, 79, 44, 0.3)',
    input: '#c4a373',
    // 纸：米黄信纸（最经典）
    paper: '#f4ead5',
    // 墨：深棕黑（保留棕褐特色）
    paperInk: '#1f1008',
    paperRule: 'rgba(31, 16, 8, 0.24)',
  },
  dark: {
    primary: '#c4a373',
    primaryForeground: '#1a1612',
    accent: '#2a2018',
    accentForeground: '#c4a373',
    secondary: '#221b14',
    secondaryForeground: '#c4a373',
    ring: 'rgba(196, 163, 115, 0.32)',
    input: 'rgba(196, 163, 115, 0.22)',
    paper: '#221b14',
    paperInk: '#d4b888',
    paperRule: 'rgba(196, 163, 115, 0.12)',
  },
}

const olive: ColorSet = {
  light: {
    primary: '#5a7038',
    primaryForeground: '#fbf6ec',
    accent: '#dde3c8',
    accentForeground: '#3d4f22',
    secondary: '#e6e8d0',
    secondaryForeground: '#3d4f22',
    ring: 'rgba(90, 112, 56, 0.3)',
    input: '#a3b87a',
    // 纸：草绿信纸
    paper: '#e8e8d0',
    // 墨：深橄榄黑
    paperInk: '#161a08',
    paperRule: 'rgba(22, 26, 8, 0.24)',
  },
  dark: {
    primary: '#a3b87a',
    primaryForeground: '#1a1612',
    accent: '#1f2414',
    accentForeground: '#a3b87a',
    secondary: '#1c1f14',
    secondaryForeground: '#a3b87a',
    ring: 'rgba(163, 184, 122, 0.32)',
    input: 'rgba(163, 184, 122, 0.22)',
    paper: '#1c1f14',
    paperInk: '#b8c890',
    paperRule: 'rgba(163, 184, 122, 0.12)',
  },
}

const wine: ColorSet = {
  light: {
    primary: '#7a2932',
    primaryForeground: '#fbf6ec',
    accent: '#e8cfcd',
    accentForeground: '#5a1a20',
    secondary: '#ecd4d4',
    secondaryForeground: '#5a1a20',
    ring: 'rgba(122, 41, 50, 0.3)',
    input: '#b85c66',
    // 纸：玫瑰信纸
    paper: '#f0d8d4',
    // 墨：深酒红黑
    paperInk: '#1f080a',
    paperRule: 'rgba(31, 8, 10, 0.26)',
  },
  dark: {
    primary: '#b85c66',
    primaryForeground: '#1a1612',
    accent: '#2a1416',
    accentForeground: '#b85c66',
    secondary: '#221418',
    secondaryForeground: '#b85c66',
    ring: 'rgba(184, 92, 102, 0.32)',
    input: 'rgba(184, 92, 102, 0.22)',
    paper: '#221418',
    paperInk: '#d4a0a8',
    paperRule: 'rgba(184, 92, 102, 0.12)',
  },
}

const steel: ColorSet = {
  light: {
    primary: '#3f4d5a',
    primaryForeground: '#fbf6ec',
    accent: '#d4dae0',
    accentForeground: '#26323d',
    secondary: '#dee3e8',
    secondaryForeground: '#26323d',
    ring: 'rgba(63, 77, 90, 0.3)',
    input: '#8595a5',
    // 纸：雪青信纸
    paper: '#dde2e8',
    // 墨：深青黑
    paperInk: '#0d1218',
    paperRule: 'rgba(13, 18, 24, 0.24)',
  },
  dark: {
    primary: '#8595a5',
    primaryForeground: '#1a1612',
    accent: '#1c2026',
    accentForeground: '#8595a5',
    secondary: '#191c22',
    secondaryForeground: '#8595a5',
    ring: 'rgba(133, 149, 165, 0.32)',
    input: 'rgba(133, 149, 165, 0.22)',
    paper: '#191c22',
    paperInk: '#b0bcc8',
    paperRule: 'rgba(133, 149, 165, 0.12)',
  },
}

export const colorSchemes: Record<ColorScheme, ColorSet> = {
  // 映射修正：ColorScheme 用 green/blue/purple/orange/cyan
  // 但视觉色系是墨黑/棕褐/橄榄/酒红/青灰（命名旧）
  // 借用通用色彩名作为键名保持向后兼容
  green:  ink,    // 墨黑（绿色键名——暂存此映射以保持历史兼容）
  blue:   sepia,  // 棕褐
  purple: olive,  // 橄榄
  orange: wine,   // 酒红
  cyan:   steel,  // 青灰
}

/** 色系展示信息 — 标签和预览色都改为报纸适配色
 *  v3.1：paperName 描述该色系在 letter 风格下的纸张效果
 */
export const colorSchemeInfo: Record<ColorScheme, { label: string; emoji: string; preview: string; paperName: string; paperPreview: string }> = {
  green:  { label: '墨黑', emoji: '🖋️', preview: '#1f1b16', paperName: '白信纸',   paperPreview: '#fbf6ec' },
  blue:   { label: '棕褐', emoji: '🍂', preview: '#7a4f2c', paperName: '米黄信纸', paperPreview: '#f4ead5' },
  purple: { label: '橄榄', emoji: '🌿', preview: '#5a7038', paperName: '草绿信纸', paperPreview: '#e8e8d0' },
  orange: { label: '酒红', emoji: '🍷', preview: '#7a2932', paperName: '玫瑰信纸', paperPreview: '#f0d8d4' },
  cyan:   { label: '青灰', emoji: '🌫️', preview: '#3f4d5a', paperName: '雪青信纸', paperPreview: '#dde2e8' },
}

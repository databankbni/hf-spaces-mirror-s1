/**
 * 预设主题注册表 — 一键应用的"色系 + 风格 + 亮暗"组合
 *
 * 设计动机：UI 层把"双选"改为"预设主题卡"，降低用户认知负担。
 * 底层 ThemeConfig 仍是 color + style 自由组合，preset 只是 UI 层的快捷方式。
 *
 * 当前已实现的预设：3 个（classic-newspaper / soft-cream / handcraft）
 * 占位预设：3 个（lineArt / minimal / letter）— 后续实现
 */

import type { ThemePreset } from './types'

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: 'classic-newspaper',
    name: '经典报纸',
    emoji: '📰',
    description: '印刷感、衬线字体、实心卡片',
    implemented: true,
    config: { color: 'green',  style: 'default',   mode: 'light' },
  },
  {
    id: 'soft-cream',
    name: '柔和米色',
    emoji: '🌾',
    description: '柔米底色、柔阴影、大圆角',
    implemented: true,
    config: { color: 'blue',   style: 'soft',      mode: 'light' },
  },
  {
    id: 'handcraft',
    name: '手抄报',
    emoji: '✂️',
    description: '便签贴纸 + 手写字体 + 虚线边',
    implemented: true,
    config: { color: 'orange', style: 'handcraft', mode: 'light' },
  },
  {
    id: 'line-art',
    name: '手绘线条',
    emoji: '✏️',
    description: 'dashed 边 + 角部涂鸦 + 网格',
    implemented: false,
    config: { color: 'cyan',   style: 'lineArt',   mode: 'light' },
  },
  {
    id: 'minimal',
    name: '极简单色',
    emoji: '◻️',
    description: '纯白底、极细线、无装饰',
    implemented: false,
    config: { color: 'cyan',   style: 'minimal',   mode: 'light' },
  },
  {
    id: 'letter',
    name: '复古信纸',
    emoji: '✉️',
    description: '错落布局 + 打字机节奏 + 信笺头',
    implemented: true,
    config: { color: 'purple', style: 'letter',    mode: 'light' },
  },
]

/** 通过 id 快速查找预设 */
export const PRESET_BY_ID: Record<string, ThemePreset> = Object.fromEntries(
  THEME_PRESETS.map(p => [p.id, p]),
)

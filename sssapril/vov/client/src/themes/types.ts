/** 主题系统类型定义 — v3 三层架构 */

/** 色系 — 5 种低饱和度、偏暖的"报纸适配色" */
export type ColorScheme = 'green' | 'blue' | 'purple' | 'orange' | 'cyan'

/**
 * 风格（视觉质感）— 持续扩展中
 *  - default: 标准报纸（印刷感）
 *  - soft: 柔和米色（柔底柔阴影）
 *  - handcraft: 手抄报（便签贴纸 + 手写字体 + 虚线边）
 *  - lineArt: 手绘线条（dashed 边 + 角部涂鸦 + 网格）
 *  - minimal: 极简单色（纯白底、极细线、无装饰）
 *  - letter: 复古信纸（错落布局 + 打字机节奏 + 隐藏 logo + 信笺头）
 *
 *  新增风格流程：
 *    1. 在此类型加 1 个 key
 *    2. 在 styles.ts 加 1 个 StyleSet（含 layout/pacing/chrome）
 *    3. 在 index.css 加 1 个 [data-style="xxx"] 块（可选，视觉部分）
 *    4. 在 ThemePicker.tsx 加 1 张卡片
 */
export type StyleMode = 'default' | 'soft' | 'handcraft' | 'lineArt' | 'minimal' | 'letter'

export type DisplayMode = 'light' | 'dark'

/* ════════════════════════════════════════════════════════════
   Layer 2: 布局策略 (Layout Strategy)
   - 决定页面骨架的排列方式
   - 由各组件读取并切换 JSX（不依赖 CSS 选择器）
   ════════════════════════════════════════════════════════════ */
export type LayoutStrategy =
  | 'newspaper'  // 经典报纸：横幅 + 大图 + 双列 + 三列（当前 default）
  | 'scattered'  // 错落：每张卡片微微旋转、错位摆放（letter 用）
  | 'grid'       // 规则网格：2/3 列等宽卡片
  | 'compact'    // 紧凑列表：单列细条卡片（minimal 用）
  | 'masonry'    // 瀑布流：高度错落的两列

/* ════════════════════════════════════════════════════════════
   Layer 3: 叙事节奏 (Narrative Pacing)
   - 决定文字、消息的呈现方式
   - 由具体内容组件读取并应用动效
   ════════════════════════════════════════════════════════════ */
export type NarrativePacing =
  | 'instant'        // 立即出现（默认）
  | 'fade-in'        // 渐显（柔和）
  | 'typewriter'     // 打字机：一个字一个字蹦出
  | 'line-by-line'   // 逐行显现：每行错开一点

/* ════════════════════════════════════════════════════════════
   Layer 4: 装饰元素 (Chrome) — 决定哪些全局装饰元素显示
   - vov 报头、报尾、导航条等
   ════════════════════════════════════════════════════════════ */
export interface ChromeConfig {
  showLogo: boolean           // 顶部 vov 报头
  showSubtitle: boolean       // "多 Agent 创作平台" 副标题
  showDateRow: boolean        // 日期/统计行
  showFooter: boolean         // 底部报尾
  showNav: boolean            // 中间导航条
  showDividers: boolean       // 报纸式横线分割
  /** 信笺风格下的"称呼 + 落款"占位 */
  letterhead?: {
    greeting: string          // 抬头称呼
    signature: string         // 落款
  }
}

export interface ThemeConfig {
  color: ColorScheme
  style: StyleMode
  mode: DisplayMode
  /** 布局策略（默认随 style 自动） */
  layout?: LayoutStrategy
  /** 叙事节奏（默认随 style 自动） */
  pacing?: NarrativePacing
  /** 装饰元素开关（默认随 style 自动） */
  chrome?: Partial<ChromeConfig>
  /**
   * 信纸字体（letter 风格使用）— 用户可切换楷体/宋体/黑体
   * 不影响其他风格，但作为全局字段持久化（切回 letter 时仍生效）
   */
  letterFont?: import('./styles').LetterFont
}

/** 色系变量（亮/暗各一套）
 *
 *  v3.1 扩展：增加 paper / paperInk / paperRule 三个字段
 *  - paper: 纸张底色（信纸/报纸的"纸"色）
 *  - paperInk: 纸张上的字色
 *  - paperRule: 信纸横线色
 *
 *  这三个字段专门为 letter 风格准备 — 让不同色系提供不同纸张效果
 *  （白色信纸、米黄信纸、玫瑰信纸、青灰信纸…）
 *  其他风格如果不需要可以忽略，继续用 StyleVariables 的硬编码值
 */
export interface ColorVariables {
  primary: string
  primaryForeground: string
  accent: string
  accentForeground: string
  secondary: string
  secondaryForeground: string
  ring: string
  input: string
  /** 纸张底色（letter 风格使用） */
  paper: string
  /** 纸张上的字色（墨水色） */
  paperInk: string
  /** 信纸横线色 */
  paperRule: string
}

/**
 * 风格变量（亮/暗各一套）— 决定视觉质感
 *
 * 基础 14 字段（所有风格共享）
 * 扩展 6 字段（特定风格专用，default/soft 用 fallback 值）
 *
 * 扩展字段语义：
 *  - fontStack: 标题/正文字体栈（handcraft 用手写体）
 *  - paperTexture: 'none' | 'paper' | 'grid' | 'ruled' | 'dot'（背景纹理）
 *  - lineStyle: 'solid' | 'dashed' | 'dotted' | 'double'（卡片边线样式）
 *  - lineWidth: '1px' | '2px' | '3px'（卡片边线粗细）
 *  - shadowStyle: 'soft' | 'hard' | 'none'（阴影：柔/硬/无）
 *  - accentDecoration: 'none' | 'tape' | 'fold' | 'doodle'（卡角装饰：便条/折角/涂鸦）
 *
 * 三层架构新增字段（v3）：
 *  - layout: 布局策略（错落/网格/瀑布流…）— 组件层读取切换 JSX
 *  - pacing: 叙事节奏（打字机/逐行…）— 组件层读取应用动效
 *  - chrome: 装饰元素开关（vov logo、报头、报尾…）— 组件层读取决定显隐
 */
export interface StyleVariables {
  background: string
  card: string
  cardForeground: string
  foreground: string
  muted: string
  mutedForeground: string
  border: string
  popover: string
  popoverForeground: string
  destructive: string
  destructiveForeground: string
  shadow: string
  radius: string
  /** 基础扩展字段 */
  cardBlur: string
  cardOpacity: string
  borderOpacity: string
  backgroundGradient: string
  /** 风格扩展字段（v2 — 支持多风格） */
  fontStack: string
  paperTexture: 'none' | 'paper' | 'grid' | 'ruled' | 'dot'
  lineStyle: 'solid' | 'dashed' | 'dotted' | 'double'
  lineWidth: '1px' | '2px' | '3px'
  shadowStyle: 'soft' | 'hard' | 'none'
  accentDecoration: 'none' | 'tape' | 'fold' | 'doodle'
  /** 三层架构新增字段（v3 — 布局 / 叙事 / 装饰元素） */
  layout: LayoutStrategy
  pacing: NarrativePacing
  chrome: ChromeConfig
}

export const DEFAULT_THEME: ThemeConfig = {
  color: 'green',
  style: 'default',
  mode: 'light',
}

/**
 * 主题派生字段（从当前 style 解析）— 给 useTheme hook 暴露
 * 组件用 useTheme().derived.layout / .pacing / .chrome 读取
 */
export interface ThemeDerived {
  layout: LayoutStrategy
  pacing: NarrativePacing
  chrome: ChromeConfig
}

/**
 * 预设主题（Preset）— 一键应用的"色系 + 风格 + 亮暗"组合
 *
 * 设计动机：UI 层把"双选"改为"预设主题卡"，降低用户认知负担。
 * 底层 ThemeConfig 仍是 color + style 自由组合，preset 只是 UI 层的快捷方式。
 */
export interface ThemePreset {
  id: string
  name: string
  emoji: string
  description: string
  /** 当前是否已实现（false 时 UI 显示"敬请期待"） */
  implemented: boolean
  config: ThemeConfig
}

/** `green` 在色系中映射为"墨黑"——最贴近经典报纸的配色 */


/** 主题选择器 — 预设主题卡 + 色系/风格微调（高级） + 亮暗模式 */

import { SunIcon, MoonIcon, CheckIcon, SparklesIcon, TypeIcon } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'
import {
  colorSchemeInfo,
  styleSchemeInfo,
  THEME_PRESETS,
  LETTER_FONTS,
  DEFAULT_LETTER_FONT,
} from '../themes'
import { applyPreset } from '../themes'
import type { ColorScheme, StyleMode, ThemePreset, LetterFont } from '../themes'

/** 判断当前 config 是否匹配某个预设 */
function isCurrentPreset(config: { color: ColorScheme; style: StyleMode; mode: 'light' | 'dark' }, preset: ThemePreset): boolean {
  return config.color === preset.config.color
      && config.style === preset.config.style
      && config.mode === preset.config.mode
}

export default function ThemePicker() {
  const { config, setColor, setStyle, setLetterFont, toggleMode } = useTheme()
  const currentLetterFont: LetterFont = config.letterFont ?? DEFAULT_LETTER_FONT

  return (
    <div className="space-y-6 font-newspaper">
      {/* 顶部：亮暗模式 */}
      <div>
        <h4 className="text-sm opacity-60 mb-3">显示模式</h4>
        <div className="flex gap-3">
          <button
            onClick={() => config.mode === 'dark' && toggleMode()}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm transition-all border border-foreground/15 ${
              config.mode === 'light'
                ? 'font-newspaper-bold border-b-2 border-b-foreground/60'
                : 'opacity-40 hover:opacity-70'
            }`}
          >
            <SunIcon className="w-4 h-4" />
            亮色
          </button>
          <button
            onClick={() => config.mode === 'light' && toggleMode()}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm transition-all border border-foreground/15 ${
              config.mode === 'dark'
                ? 'font-newspaper-bold border-b-2 border-b-foreground/60'
                : 'opacity-40 hover:opacity-70'
            }`}
          >
            <MoonIcon className="w-4 h-4" />
            暗色
          </button>
        </div>
      </div>

      {/* 核心：预设主题卡（3 列网格） */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <SparklesIcon className="w-3.5 h-3.5 opacity-60" />
          <h4 className="text-sm opacity-60">主题预设</h4>
          <span className="text-xs opacity-30">— 一键切换整体风格</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          {THEME_PRESETS.map(preset => {
            const active = isCurrentPreset(config, preset)
            return (
              <button
                key={preset.id}
                onClick={() => preset.implemented && applyPreset(preset.id)}
                disabled={!preset.implemented}
                className={`relative flex flex-col items-start gap-2 p-4 text-left transition-all border ${
                  active
                    ? 'border-foreground/40 border-b-2'
                    : preset.implemented
                      ? 'border-foreground/15 hover:border-foreground/30 opacity-70 hover:opacity-100'
                      : 'border-foreground/10 opacity-40 cursor-not-allowed'
                }`}
              >
                {/* emoji + 状态 */}
                <div className="flex items-center justify-between w-full">
                  <span className="text-2xl">{preset.emoji}</span>
                  {active && (
                    <div className="flex items-center gap-1 text-xs">
                      <CheckIcon className="w-3.5 h-3.5 opacity-70" />
                      <span className="opacity-60">已选中</span>
                    </div>
                  )}
                  {!preset.implemented && (
                    <span className="text-[10px] px-1.5 py-0.5 border border-foreground/15 opacity-60">
                      敬请期待
                    </span>
                  )}
                </div>

                {/* 名字 + 描述 */}
                <div className="flex-1">
                  <div className={`text-sm mb-0.5 ${active ? 'font-newspaper-bold' : ''}`}>
                    {preset.name}
                  </div>
                  <div className="text-xs opacity-50 leading-relaxed">
                    {preset.description}
                  </div>
                </div>

                {/* 底色块预览（小色卡） — 反映色系 + 风格 */}
                <div className="flex gap-1 mt-1">
                  <div
                    className="w-4 h-4 border border-foreground/10"
                    style={{ background: preset.config.color === 'green'  ? '#1f1b16'
                                            : preset.config.color === 'blue'   ? '#7a4f2c'
                                            : preset.config.color === 'purple' ? '#5a7038'
                                            : preset.config.color === 'orange' ? '#7a2932'
                                            : preset.config.color === 'cyan'   ? '#3f4d5a' : '#1f1b16' }}
                  />
                  <div
                    className="w-4 h-4 border border-foreground/10"
                    style={{ background: '#fbf6ec' }}
                  />
                  <div
                    className="w-4 h-4 border border-foreground/10"
                    style={{ background: '#f5f0e8' }}
                  />
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* 高级：色系微调（仅调整色相，不影响风格） */}
      <details className="border-t border-foreground/10 pt-4">
        <summary className="text-sm opacity-60 cursor-pointer hover:opacity-100 transition-opacity">
          高级 · 色系微调
        </summary>
        <div className="mt-3 flex gap-2 flex-wrap">
          {(Object.keys(colorSchemeInfo) as ColorScheme[]).map(color => {
            const info = colorSchemeInfo[color]
            const active = config.color === color
            return (
              <button
                key={color}
                onClick={() => setColor(color)}
                className={`relative flex flex-col items-center gap-1.5 px-3 py-2 text-xs transition-all border border-foreground/15 ${
                  active
                    ? 'border-b-2 border-b-foreground/60 font-newspaper-bold'
                    : 'opacity-50 hover:opacity-80'
                }`}
                title={info.label}
              >
                <div className="w-6 h-6 flex items-center justify-center text-base border border-foreground/10">
                  {info.emoji}
                </div>
                <span>{info.label}</span>
              </button>
            )
          })}
        </div>
      </details>

      {/* 高级：风格微调（仅调整质感，不影响色系） */}
      <details className="border-t border-foreground/10 pt-4">
        <summary className="text-sm opacity-60 cursor-pointer hover:opacity-100 transition-opacity">
          高级 · 风格微调
        </summary>
        <div className="mt-3 flex gap-2 flex-wrap">
          {(Object.keys(styleSchemeInfo) as StyleMode[]).map(style => {
            const info = styleSchemeInfo[style]
            const active = config.style === style
            return (
              <button
                key={style}
                onClick={() => setStyle(style)}
                className={`flex flex-col items-start gap-0.5 px-3 py-2 text-xs transition-all border border-foreground/15 ${
                  active
                    ? 'border-b-2 border-b-foreground/60 font-newspaper-bold'
                    : 'opacity-50 hover:opacity-80'
                }`}
              >
                <span>{info.emoji} {info.label}</span>
                <span className="text-[10px] opacity-40">{info.description}</span>
              </button>
            )
          })}
        </div>
      </details>

      {/* 字体切换：影响 letter 风格下正文字体（任何风格下都可切换预览） */}
      <div className="border-t border-foreground/10 pt-4">
        <div className="flex items-center gap-2 mb-3">
          <TypeIcon className="w-3.5 h-3.5 opacity-60" />
          <h4 className="text-sm opacity-60">信纸字体</h4>
          <span className="text-xs opacity-30">— 切换楷体 / 宋体 / 黑体（切到复古信纸时生效）</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(Object.keys(LETTER_FONTS) as LetterFont[]).map(key => {
            const font = LETTER_FONTS[key]
            const active = currentLetterFont === key
            return (
              <button
                key={key}
                onClick={() => setLetterFont(key)}
                className={`flex flex-col items-start gap-1 px-3 py-2.5 text-left transition-all border ${
                  active
                    ? 'border-foreground/40 border-b-2'
                    : 'border-foreground/15 hover:border-foreground/30 opacity-70 hover:opacity-100'
                }`}
                title={font.description}
              >
                <div className="flex items-center justify-between w-full">
                  <span
                    className={`text-base ${active ? 'font-newspaper-bold' : ''}`}
                    style={{ fontFamily: font.stack }}
                  >
                    {font.label}
                  </span>
                  {active && <CheckIcon className="w-3.5 h-3.5 opacity-70" />}
                </div>
                <div className="text-[10px] opacity-50 leading-relaxed">
                  {font.description}
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* 预览 */}
      <div>
        <h4 className="text-sm opacity-60 mb-3">预览</h4>
        <div className="grid grid-cols-2 gap-3">
          <div className="border border-foreground/15 p-4">
            <div className="text-sm font-newspaper-bold opacity-80 mb-1">示例卡片</div>
            <div className="text-xs opacity-40">这是卡片内容的预览效果</div>
            <div className="mt-3 flex gap-2">
              <span className="px-2 py-0.5 text-xs border border-foreground/15 opacity-60">标签</span>
              <span className="px-2 py-0.5 text-xs border border-foreground/10 opacity-40">次要</span>
            </div>
          </div>
          <div className="border border-foreground/15 p-4">
            <div className="text-sm font-newspaper-bold opacity-80 mb-1">操作按钮</div>
            <div className="text-xs opacity-40 mb-3">按钮样式预览</div>
            <div className="flex gap-2">
              <button className="text-xs font-newspaper-bold underline underline-offset-4 opacity-80 hover:opacity-100 transition-opacity">
                主要
              </button>
              <button className="text-xs opacity-50 hover:opacity-80 transition-opacity">
                次要
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

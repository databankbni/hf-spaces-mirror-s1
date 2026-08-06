/** 全局主题初始化器 — 在应用启动时立即应用 localStorage 中的主题
 *
 *  设计动机：useTheme 只在 ThemePicker 中使用，
 *  其他页面（首页 / Chat 等）没有 ThemePicker 挂载时不会调用 applyTheme。
 *  这个组件无渲染副作用（返回 null），只负责在挂载时同步执行一次 applyTheme。
 */

import { useEffect } from 'react'
import { loadTheme, applyTheme } from '../themes'

export default function ThemeInitializer() {
  useEffect(() => {
    applyTheme(loadTheme())
  }, [])
  return null
}

/** 中文字体预加载器 — 触发 Google Fonts 加载中文 unicode-range 子集
 *
 *  为什么需要：
 *  Google Fonts 中文（如 ZCOOL KuaiLe）采用 unicode-range 子集机制，
 *  浏览器只下载页面已渲染字符的子集。首次访问时如果页面没有出现
 *  ZCOOL KuaiLe 字体中的字符，浏览器不会下载该字体的中文字符。
 *
 *  这个组件在挂载时渲染一个隐藏的 div 包含常用中文字符，
 *  强制浏览器下载完整的中文字形子集，让 ZCOOL KuaiLe 在所有
 *  中文场景下都能立即生效。
 *
 *  注意：仅在用户启用 handcraft 风格时才挂载此组件，
 *  避免对 default/soft 风格造成无意义的字体下载。
 */

import { useEffect } from 'react'
import { useTheme } from '../hooks/useTheme'

/** 触发中文手写体下载的常用字符集（覆盖 UI 文本） */
const FONT_TRIGGER_CHARS =
  '项目设置管理界面新闻列表卡片字体便签贴纸手抄报创作平台' +
  '经典报纸柔和米色柔和极简单色复古信纸手绘线条' +
  '任务对话新建导入编辑删除查看详情群聊智能体' +
  '一二三四五六七八九十百千万亿〇○●○·' +
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' +
  '0123456789'

export default function FontPreload() {
  const { config } = useTheme()

  useEffect(() => {
    // 只在 handcraft 风格下预加载
    if (config.style !== 'handcraft') return

    // 创建隐藏 div 触发字体下载
    const trigger = document.createElement('div')
    trigger.setAttribute('data-font-trigger', 'handcraft')
    trigger.style.cssText = `
      position: absolute;
      left: -9999px;
      top: 0;
      visibility: hidden;
      pointer-events: none;
      font-family: "ZCOOL KuaiLe", "Ma Shan Zheng", "KaiTi", "楷体", serif;
      font-size: 16px;
    `
    trigger.textContent = FONT_TRIGGER_CHARS
    document.body.appendChild(trigger)

    return () => {
      trigger.remove()
    }
  }, [config.style])

  return null
}

/**
 * useViewFromHash —— 从 URL hash 解析主区域视图
 *
 * 设计见 docs/product-evolution-discussion.md 决策 7：
 * - URL hash 是"视图定位符"，记录当前渲染的 RenderSpec
 * - 有 hash（#v=...）时主区域渲染 RenderEngine
 * - 无 hash 时主区域显示默认路由内容
 * - agent 调 render 工具 → 更新 hash → 主区域自动切换视图
 *
 * hash 格式：#v=<base64url 编码的 RenderSpec JSON>
 */

import { useState, useEffect } from 'react';
import { hashToSpec } from '../render-engine/urlCodec';
import type { RenderSpec } from '../render-engine/types';

/**
 * 监听 URL hash 变化，返回解析出的 RenderSpec
 *
 * @returns 当前 hash 中的 RenderSpec，无匹配时返回 null
 */
export function useViewFromHash(): RenderSpec | null {
  const [spec, setSpec] = useState<RenderSpec | null>(() =>
    typeof window !== 'undefined' ? hashToSpec(window.location.hash) : null
  );

  useEffect(() => {
    const handler = () => setSpec(hashToSpec(window.location.hash));
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);

  return spec;
}

/**
 * 清除当前 hash 视图（回到默认路由内容）
 */
export function clearViewHash(): void {
  // 用 history.replaceState 避免触发 hashchange 导致的滚动
  if (window.location.hash) {
    history.replaceState(null, '', window.location.pathname + window.location.search);
    // 手动触发 hashchange 让 useViewFromHash 更新
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  }
}

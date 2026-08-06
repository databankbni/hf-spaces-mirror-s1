/**
 * RenderSpec URL 编解码工具
 *
 * 设计见 docs/product-evolution-discussion.md 决策 6/7：
 * - RenderSpec JSON 编码进 URL hash，实现"视图定位符"
 * - URL 可分享/收藏/复现，hash 是视图状态的唯一真相源
 *
 * 编码方案：JSON → UTF-8 bytes → base64url（URL 安全：+→- / →_ 去掉= padding）
 * base64url 避免 URL 中 + / = 被转义的问题。
 */

import type { RenderSpec } from './types';

/**
 * 将 RenderSpec 编码为 URL 安全的 base64url 字符串
 *
 * @param spec - 渲染规格
 * @returns base64url 编码字符串（无 padding）
 */
export function encodeSpec(spec: RenderSpec): string {
  const json = JSON.stringify(spec);
  const bytes = new TextEncoder().encode(json);
  let binary = '';
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  const b64 = btoa(binary);
  // base64 → base64url：+ → -, / → _, 去掉 = padding
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * 将 base64url 字符串解码为 RenderSpec
 *
 * @param encoded - base64url 编码字符串
 * @returns RenderSpec，解码失败返回 null
 */
export function decodeSpec(encoded: string): RenderSpec | null {
  try {
    // base64url → base64：- → +, _ → /
    let b64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
    // 补齐 padding
    while (b64.length % 4) {
      b64 += '=';
    }
    const binary = atob(b64);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    const json = new TextDecoder().decode(bytes);
    return JSON.parse(json) as RenderSpec;
  } catch {
    return null;
  }
}

/**
 * 编码并拼接到 URL hash（带前缀标识，便于区分）
 *
 * @param spec - 渲染规格
 * @returns 形如 "#v=eyJ2aWV3X3R5cGUi..." 的 hash 字符串
 */
export function specToHash(spec: RenderSpec): string {
  return `#v=${encodeSpec(spec)}`;
}

/**
 * 从 URL hash 解析 RenderSpec
 *
 * @param hash - URL hash（如 "#v=eyJ..." 或 "v=eyJ..."）
 * @returns RenderSpec，无匹配前缀或解码失败返回 null
 */
export function hashToSpec(hash: string): RenderSpec | null {
  const match = hash.match(/[#&?]v=([^&]+)/);
  if (!match) return null;
  return decodeSpec(match[1]);
}

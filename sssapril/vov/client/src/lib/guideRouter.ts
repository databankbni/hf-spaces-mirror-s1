/**
 * 引导 agent 路由（URL 前缀匹配）
 *
 * 设计见 docs/product-evolution-discussion.md 决策 6：
 * - 按 URL 最长前缀匹配决定 agent 身份
 * - 未匹配则往短回退，兜底到 `/` 的 L0
 * - 统一"页面路由"和"agent 路由"为同一套路由表的两个维度
 *
 * 路由表：
 *   /                         → L0 需求 agent（兜底，首页召唤）
 *   /project/:id              → L1 项目 agent（coordinator，项目内召唤）
 *   /project/:id/chat/:gid    → L2 群负责人 agent（后续）
 *
 * L0 和 L1 已激活，L2 为占位结构供后续扩展。
 */

/** 引导层级 */
export type GuideLevel = 'L0' | 'L1' | 'L2';

/** 路由表项 */
export interface GuideRoute {
  level: GuideLevel;
  /** URL 模式，:param 为路径参数 */
  pattern: string;
  /** 角色描述 */
  description: string;
  /** 是否已激活（未激活则回退到更短的已激活路由） */
  enabled: boolean;
}

/**
 * 路由表（按特异性从长到短排序，最长前缀优先匹配）
 */
const GUIDE_ROUTES: GuideRoute[] = [
  { level: 'L2', pattern: '/project/:id/chat/:gid', description: '群负责人 agent', enabled: false },
  { level: 'L1', pattern: '/project/:id', description: '项目 agent (coordinator)', enabled: true },
  { level: 'L0', pattern: '/', description: '需求 agent（兜底）', enabled: true },
];

/** 匹配结果 */
export interface GuideRouteMatch {
  level: GuideLevel;
  /** 从 URL 解析出的路径参数（如 { id: 'xxx', gid: 'yyy' }） */
  params: Record<string, string>;
  /** 匹配到的路由描述 */
  description: string;
}

/**
 * 将 pattern 与 pathname 分段匹配
 *
 * @returns 匹配成功返回参数对象，失败返回 null
 */
function matchPattern(pathname: string, pattern: string): Record<string, string> | null {
  const pathParts = pathname.split('/').filter(Boolean);
  const patternParts = pattern.split('/').filter(Boolean);

  // 段数不同则不匹配（精确匹配，不做前缀截断——前缀语义由路由表顺序保证）
  if (pathParts.length !== patternParts.length) return null;

  const params: Record<string, string> = {};
  for (let i = 0; i < patternParts.length; i++) {
    const pp = patternParts[i];
    const sp = pathParts[i];
    if (pp.startsWith(':')) {
      params[pp.slice(1)] = sp;
    } else if (pp !== sp) {
      return null;
    }
  }
  return params;
}

/**
 * 根据当前 URL 匹配引导 agent 路由
 *
 * 最长前缀匹配：按路由表顺序（长→短）逐个尝试，
 * 跳过未激活的路由，第一个匹配成功的即为结果。
 * 全部未匹配则兜底到 L0。
 *
 * @param pathname - 当前 URL pathname（如 '/' '/project/abc'）
 */
export function matchGuideRoute(pathname: string): GuideRouteMatch {
  for (const route of GUIDE_ROUTES) {
    if (!route.enabled) continue;
    const params = matchPattern(pathname, route.pattern);
    if (params !== null) {
      return { level: route.level, params, description: route.description };
    }
  }

  // 兜底：L0（首页 / 任何未匹配路径都走 L0 引导）
  // 特殊处理：pattern '/' 分段后为空数组，pathname '/' 也是空数组，上面应已匹配。
  // 这里防御性兜底，处理极端情况。
  const l0 = GUIDE_ROUTES.find((r) => r.level === 'L0')!;
  return { level: 'L0', params: {}, description: l0.description };
}

/**
 * 获取所有路由表项（供调试/UI 展示）
 */
export function listGuideRoutes(): readonly GuideRoute[] {
  return GUIDE_ROUTES;
}

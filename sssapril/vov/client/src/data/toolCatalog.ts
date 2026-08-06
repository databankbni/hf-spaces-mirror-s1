/**
 * 工具目录 - 类型定义与动态加载
 *
 * 数据源从后端 /tools/catalog API 动态加载，
 * 后端 agentflow/tool_catalog.py 是唯一数据源。
 * 添加新工具只需修改后端，前端自动同步。
 */

// [deploy marker] 强制触发 build context 重新导出 toolCatalog.ts (filter-branch index 失同步 fix)

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

// ── 类型定义 ──

export type ToolCategory =
  | 'file'
  | 'shell'
  | 'memory'
  | 'skill'
  | 'agent'
  | 'project'
  | 'group'
  | 'task'
  | 'resource'
  | 'render';

export interface ToolParam {
  key: string;
  label: string;
  type: 'string' | 'number' | 'boolean';
  default?: string | number | boolean;
  required?: boolean;
  placeholder?: string;
}

export interface ToolCatalogItem {
  kind: string;
  name: string;
  description: string;
  detail: string;
  category: ToolCategory;
  params: ToolParam[];
  recommended?: boolean;
}

export interface CategoryLabel {
  label: string;
  icon: string;
}

// ── API 响应类型 ──

interface ToolCatalogResponse {
  tools: ToolCatalogItem[];
  categories: Record<string, CategoryLabel>;
}

// ── 动态加载 Hook ──

export function useToolCatalog() {
  return useQuery({
    queryKey: ['tool-catalog'],
    queryFn: async () => {
      const resp = await apiClient.get<ToolCatalogResponse>('/tools/catalog');
      return resp.data;
    },
    staleTime: 5 * 60 * 1000, // 5分钟缓存，工具目录不常变
  });
}

// ── 工具函数 ──

export function getToolsByCategory(tools: ToolCatalogItem[]): Map<ToolCategory, ToolCatalogItem[]> {
  const map = new Map<ToolCategory, ToolCatalogItem[]>();
  for (const tool of tools) {
    if (!map.has(tool.category)) map.set(tool.category, []);
    map.get(tool.category)!.push(tool);
  }
  return map;
}

export function findToolByKind(tools: ToolCatalogItem[], kind: string): ToolCatalogItem | undefined {
  return tools.find(t => t.kind === kind);
}

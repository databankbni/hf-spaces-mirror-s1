import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import type { RenderSpec, DataSourceConfig } from './types';
import { applyTransform, extractDataByPath, resolveTemplate, resolveTemplateMap } from './DataTransform';

/**
 * 获取当前上下文变量（路由参数等），用于解析 data_source 中的模板变量
 */
function getContextVars(): Record<string, string | undefined> {
  const vars: Record<string, string | undefined> = {};
  // 从当前 URL 路径中提取参数
  const pathParts = window.location.pathname.split('/');
  // 匹配 /project/:projectId 和 /chat/:groupId 等模式
  for (let i = 0; i < pathParts.length - 1; i++) {
    if (pathParts[i] === 'project' && pathParts[i + 1]) {
      vars.project_id = pathParts[i + 1];
    }
    if (pathParts[i] === 'chat' && pathParts[i + 1]) {
      vars.group_id = pathParts[i + 1];
    }
  }
  // 从 URL search params 中提取
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of params.entries()) {
    vars[key] = value;
  }
  return vars;
}

interface RenderDataResult {
  data: unknown;
  isLoading: boolean;
  error: Error | null;
}

/**
 * 根据 RenderSpec 的 data_source 配置加载数据
 * 如果 spec.data 存在（内联数据），直接使用；否则通过 API 查询
 */
export function useRenderData(spec: RenderSpec): RenderDataResult {
  const ds = spec.data_source;

  const query = useQuery({
    queryKey: ['render-data', ds?.api, ds?.params, ds?.body],
    queryFn: async () => {
      if (!ds) return null;

      const vars = getContextVars();
      const resolvedApi = resolveTemplate(ds.api, vars);
      const rawParams = resolveTemplateMap(ds.params, vars);
      // 将 params 值转换为 apiClient.get 接受的类型
      const resolvedParams: Record<string, string | number | boolean | undefined> = {};
      if (rawParams) {
        for (const [key, value] of Object.entries(rawParams)) {
          resolvedParams[key] = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
            ? value
            : String(value);
        }
      }

      const method = ds.method || 'GET';
      let response;

      if (method === 'POST') {
        response = await apiClient.post(resolvedApi, ds.body || {});
      } else {
        response = await apiClient.get(resolvedApi, resolvedParams);
      }

      // 解包 ApiResponse：apiClient 返回 { success, data, message }，先取 data 字段
      const unwrapped = (response as Record<string, unknown>)?.data !== undefined
        ? (response as Record<string, unknown>).data
        : response;

      // 按 data_path 提取数据（基于解包后的数据）
      const extracted = extractDataByPath(unwrapped, ds.data_path);
      // 应用转换
      return applyTransform(ds.transform, extracted);
    },
    enabled: !!ds?.api,
    refetchInterval: ds?.refresh_interval ? ds.refresh_interval * 1000 : false,
  });

  // 优先使用内联数据
  if (spec.data != null) {
    let inlineData = spec.data;
    // 自动解包：当 data 是对象且只有一个 key 对应数组时，提取该数组
    // 例如 { capabilities: [...] } -> [...]，这样视图组件能直接遍历
    if (inlineData && typeof inlineData === 'object' && !Array.isArray(inlineData)) {
      const entries = Object.entries(inlineData);
      if (entries.length === 1 && Array.isArray(entries[0][1])) {
        inlineData = entries[0][1] as unknown as Record<string, unknown>;
      }
    }
    const transformed = applyTransform(spec.data_source?.transform, inlineData);
    return { data: transformed, isLoading: false, error: null };
  }

  return {
    data: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
  };
}

/**
 * 系统设置 Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsApi, type LLMSettingsUpdate } from '../api/settings';

export const settingsKeys = {
  all: ['settings'] as const,
  status: () => [...settingsKeys.all, 'status'] as const,
  llm: () => [...settingsKeys.all, 'llm'] as const,
  models: () => [...settingsKeys.all, 'models'] as const,
};

/** 获取系统状态 */
export function useSystemStatus() {
  return useQuery({
    queryKey: settingsKeys.status(),
    queryFn: () => settingsApi.getStatus(),
    retry: false,
    staleTime: 30_000,
  });
}

/** 获取 LLM 配置 */
export function useLLMSettings() {
  return useQuery({
    queryKey: settingsKeys.llm(),
    queryFn: () => settingsApi.getLLM(),
  });
}

/** 更新 LLM 配置 */
export function useUpdateLLMSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: LLMSettingsUpdate) => settingsApi.updateLLM(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: settingsKeys.llm() });
      queryClient.invalidateQueries({ queryKey: settingsKeys.status() });
    },
  });
}

/** 测试 LLM 连接 */
export function useTestLLM() {
  return useMutation({
    mutationFn: (data: { api_key: string; base_url?: string }) => settingsApi.testLLM(data),
  });
}

/** 获取可用模型列表 */
export function useLLMModels() {
  return useQuery({
    queryKey: settingsKeys.models(),
    queryFn: () => settingsApi.getModels(),
    enabled: false, // 手动触发
  });
}

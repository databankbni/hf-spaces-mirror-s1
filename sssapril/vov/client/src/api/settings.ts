/**
 * 系统设置 API
 */

import { apiClient } from './client';

export interface SystemStatus {
  llm_configured: boolean;
  db_driver: string;
  app_version: string;
}

export interface LLMSettings {
  api_key_masked: string;
  api_key_set: boolean;
  base_url: string | null;
  default_model: string | null;
}

export interface LLMSettingsUpdate {
  api_key?: string;
  base_url?: string;
  default_model?: string;
}

export interface LLMTestResult {
  success: boolean;
  message: string;
  models: string[];
}

export const settingsApi = {
  /** 获取系统状态（首次引导用） */
  // 注意: settings 端点返回裸数据 (非 {success, data} 包裹), 直接取 res 即可
  getStatus: async (): Promise<SystemStatus> => {
    return apiClient.get<SystemStatus>('/settings/status') as unknown as Promise<SystemStatus>;
  },

  /** 获取 LLM 配置 */
  getLLM: async (): Promise<LLMSettings> => {
    return apiClient.get<LLMSettings>('/settings/llm') as unknown as Promise<LLMSettings>;
  },

  /** 更新 LLM 配置 */
  updateLLM: async (data: LLMSettingsUpdate): Promise<{ ok: boolean; message: string }> => {
    return apiClient.put<{ ok: boolean; message: string }>('/settings/llm', data) as unknown as Promise<{ ok: boolean; message: string }>;
  },

  /** 测试 LLM 连接 */
  testLLM: async (data: { api_key: string; base_url?: string }): Promise<LLMTestResult> => {
    return apiClient.post<LLMTestResult>('/settings/llm/test', data) as unknown as Promise<LLMTestResult>;
  },

  /** 获取可用模型列表 */
  getModels: async (): Promise<{ models: string[]; count?: number; message?: string }> => {
    return apiClient.get<{ models: string[]; count?: number; message?: string }>('/settings/llm/models') as unknown as Promise<{ models: string[]; count?: number; message?: string }>;
  },
};

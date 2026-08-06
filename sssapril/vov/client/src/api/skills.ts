/**
 * 技能 API 模块
 *
 * 封装独立技能的 CRUD API 调用。
 */

import { apiClient } from './client';
import { ApiResponse, PaginatedResponse, Skill } from '../types';

export interface CreateSkillRequest {
  name: string;
  description?: string;
  skill_type: string;
  content?: string;
  config?: Record<string, unknown>;
  files?: Record<string, string>;
}

export interface UpdateSkillRequest {
  name?: string;
  description?: string;
  skill_type?: string;
  content?: string;
  config?: Record<string, unknown>;
  files?: Record<string, string>;
}

export const skillApi = {
  /** 获取所有技能 */
  list() {
    return apiClient.get<PaginatedResponse<Skill>>('/skills');
  },

  /** 获取技能详情 */
  get(id: string) {
    return apiClient.get<Skill>(`/skills/${id}`);
  },

  /** 创建技能 */
  create(data: CreateSkillRequest) {
    return apiClient.post<Skill>('/skills', data);
  },

  /** 更新技能 */
  update(id: string, data: UpdateSkillRequest) {
    return apiClient.put<Skill>(`/skills/${id}`, data);
  },

  /** 删除技能 */
  delete(id: string) {
    return apiClient.delete<void>(`/skills/${id}`);
  },
};

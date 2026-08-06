/**
 * Agent API模块
 *
 * 封装Agent相关的API调用。
 */

import { apiClient } from './client';
import {
  ApiResponse,
  PaginatedResponse,
  Agent,
  ProjectAgent,
  AgentMemory,
  CreateAgentRequest,
  UpdateAgentRequest,
  AgentFilters,
} from '../types';

/**
 * 全局Agent API
 */
export const agentApi = {
  /**
   * 获取全局Agent列表
   *
   * @param filters - 筛选参数
   * @returns Agent列表
   */
  list(filters?: AgentFilters) {
    return apiClient.get<PaginatedResponse<Agent>>('/agents', filters);
  },

  /**
   * 获取Agent详情
   *
   * @param id - Agent ID
   * @returns Agent详情
   */
  get(id: string) {
    return apiClient.get<Agent>(`/agents/${id}`);
  },

  /**
   * 创建Agent
   *
   * @param data - 创建参数
   * @returns 创建的Agent
   */
  create(data: CreateAgentRequest) {
    return apiClient.post<Agent>('/agents', data);
  },

  /**
   * 更新Agent
   *
   * @param id - Agent ID
   * @param data - 更新参数
   * @returns 更新后的Agent
   */
  update(id: string, data: UpdateAgentRequest) {
    return apiClient.put<Agent>(`/agents/${id}`, data);
  },

  /**
   * 删除Agent
   *
   * @param id - Agent ID
   */
  delete(id: string) {
    return apiClient.delete<void>(`/agents/${id}`);
  },
};

/**
 * 项目Agent API
 */
export const projectAgentApi = {
  /**
   * 获取项目Agent列表
   *
   * @param projectId - 项目ID
   * @returns 项目Agent列表
   */
  list(projectId: string) {
    return apiClient.get<PaginatedResponse<ProjectAgent>>(`/projects/${projectId}/agents`);
  },

  /**
   * 添加Agent到项目
   *
   * @param projectId - 项目ID
   * @param agentId - Agent ID
   * @param overrideConfig - 覆盖配置
   * @returns 添加的项目Agent
   */
  add(projectId: string, agentId: string, overrideConfig?: Record<string, unknown>) {
    return apiClient.post<ProjectAgent>(`/projects/${projectId}/agents`, {
      agent_id: agentId,
      override_config: overrideConfig,
    });
  },

  /**
   * 从项目移除Agent
   *
   * @param projectId - 项目ID
   * @param agentId - Agent ID
   */
  remove(projectId: string, agentId: string) {
    return apiClient.delete<void>(`/projects/${projectId}/agents/${agentId}`);
  },
};

/**
 * Agent记忆API
 */
export const memoryApi = {
  /**
   * 获取Agent在项目中的笔记（默认 slug）
   *
   * @param agentId - Agent ID
   * @param projectId - 项目ID
   * @param slug - 分类标识，默认 "default"
   * @returns Agent笔记
   */
  get(agentId: string, projectId: string, slug: string = 'default') {
    return apiClient.get<AgentMemory>(`/agents/${agentId}/projects/${projectId}/memory`, { slug });
  },

  /**
   * 获取项目所有Agent笔记
   *
   * @param projectId - 项目ID
   * @returns Agent笔记列表
   */
  listByProject(projectId: string) {
    return apiClient.get<PaginatedResponse<AgentMemory & { agent: Agent }>>(`/projects/${projectId}/memories`);
  },

  /**
   * 更新Agent笔记
   *
   * @param agentId - Agent ID
   * @param projectId - 项目ID
   * @param content - 笔记内容
   * @param tags - 标签
   * @returns 更新后的笔记
   */
  update(agentId: string, projectId: string, content: string, tags?: string[]) {
    return apiClient.put<AgentMemory>(`/agents/${agentId}/memories/${projectId}`, {
      content,
      tags,
    });
  },
};

export default { agentApi, projectAgentApi, memoryApi };

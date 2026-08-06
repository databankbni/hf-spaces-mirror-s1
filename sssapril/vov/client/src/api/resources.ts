/**
 * 资源API模块
 *
 * 封装资源(Resource)和标签(Tag)相关的API调用。
 */

import { apiClient } from './client';
import {
  ApiResponse,
  PaginatedResponse,
  Resource,
  CreateResourceRequest,
  UpdateResourceRequest,
  Tag,
  CreateTagRequest,
  UpdateTagRequest,
} from '../types';

/**
 * 资源API
 */
export const resourceApi = {
  /**
   * 获取项目全局资源列表
   *
   * @param projectId - 项目ID
   * @param type - 资源类型筛选
   * @param required - 是否必读筛选
   * @returns 资源列表
   */
  listByProject(projectId: string, type?: string, required?: boolean) {
    return apiClient.get<PaginatedResponse<Resource>>(`/projects/${projectId}/resources`, {
      type,
      required: required !== undefined ? String(required) : undefined,
    });
  },

  /**
   * 获取群聊资源列表
   *
   * @param groupId - 群聊ID
   * @returns 资源列表
   */
  listByGroup(groupId: string) {
    return apiClient.get<PaginatedResponse<Resource>>(`/groups/${groupId}/resources`);
  },

  /**
   * 创建资源
   *
   * @param data - 创建参数
   * @returns 创建的资源
   */
  create(data: CreateResourceRequest) {
    return apiClient.post<Resource>('/resources', data);
  },

  /**
   * 更新资源
   *
   * @param id - 资源ID
   * @param data - 更新参数
   * @returns 更新后的资源
   */
  update(id: string, data: UpdateResourceRequest) {
    return apiClient.put<Resource>(`/resources/${id}`, data);
  },

  /**
   * 删除资源
   *
   * @param id - 资源ID
   */
  delete(id: string) {
    return apiClient.delete<void>(`/resources/${id}`);
  },
};

/**
 * 标签API
 */
export const tagApi = {
  /**
   * 获取项目标签列表
   *
   * @param projectId - 项目ID
   * @returns 标签列表
   */
  list(projectId: string) {
    return apiClient.get<PaginatedResponse<Tag>>(`/projects/${projectId}/tags`);
  },

  /**
   * 创建标签
   *
   * @param projectId - 项目ID
   * @param data - 创建参数
   * @returns 创建的标签
   */
  create(projectId: string, data: CreateTagRequest) {
    return apiClient.post<Tag>(`/projects/${projectId}/tags`, data);
  },

  /**
   * 更新标签
   *
   * @param id - 标签ID
   * @param data - 更新参数
   * @returns 更新后的标签
   */
  update(id: string, data: UpdateTagRequest) {
    return apiClient.put<Tag>(`/tags/${id}`, data);
  },

  /**
   * 删除标签
   *
   * @param id - 标签ID
   */
  delete(id: string) {
    return apiClient.delete<void>(`/tags/${id}`);
  },
};

export default { resourceApi, tagApi };

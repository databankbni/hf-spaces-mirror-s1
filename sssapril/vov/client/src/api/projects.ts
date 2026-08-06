/**
 * 项目API模块
 *
 * 封装项目相关的API调用。
 */

import { apiClient } from './client';
import {
  ApiResponse,
  PaginatedResponse,
  Project,
  ProjectListItem,
  CreateProjectRequest,
  UpdateProjectRequest,
  ProjectFilters,
  PaginationParams,
} from '../types';

/**
 * 项目API
 */
export const projectApi = {
  /**
   * 获取项目列表
   *
   * @param filters - 筛选参数
   * @param pagination - 分页参数
   * @returns 项目列表
   */
  list(filters?: ProjectFilters, pagination?: PaginationParams) {
    return apiClient.get<PaginatedResponse<ProjectListItem>>('/projects', {
      ...filters,
      ...pagination,
    });
  },

  /**
   * 获取项目详情
   *
   * @param id - 项目ID
   * @returns 项目详情
   */
  get(id: string) {
    return apiClient.get<Project>(`/projects/${id}`);
  },

  /**
   * 创建项目
   *
   * @param data - 创建项目参数
   * @returns 创建的项目
   */
  create(data: CreateProjectRequest) {
    return apiClient.post<Project>('/projects', data);
  },

  /**
   * 更新项目
   *
   * @param id - 项目ID
   * @param data - 更新参数
   * @returns 更新后的项目
   */
  update(id: string, data: UpdateProjectRequest) {
    return apiClient.put<Project>(`/projects/${id}`, data);
  },

  /**
   * 删除项目
   *
   * @param id - 项目ID
   */
  delete(id: string) {
    return apiClient.delete<void>(`/projects/${id}`);
  },

  /**
   * 导出项目
   *
   * @param id - 项目ID
   * @param options - 导出选项
   */
  export(id: string, options?: Record<string, boolean>) {
    return apiClient.download(`/projects/${id}/export`, `project-${id}.zip`, options);
  },

  /**
   * 导入项目
   *
   * @param file - ZIP文件
   * @param mode - 导入模式
   * @returns 导入的项目
   */
  import(file: File, mode: 'create' | 'merge' = 'create') {
    return apiClient.upload<Project>('/projects/import', file, { mode });
  },
};

export default projectApi;

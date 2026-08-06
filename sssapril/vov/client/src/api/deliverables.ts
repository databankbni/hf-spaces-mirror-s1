/**
 * 交付物API模块
 *
 * 封装交付物相关的API调用。
 */

import { apiClient } from './client';
import {
  ApiResponse,
  PaginatedResponse,
  Deliverable,
  DeliverableListItem,
  CreateDeliverableRequest,
  UpdateDeliverableRequest,
  DeliverableDiff,
  DeliverableVersion,
} from '../types';

/**
 * 交付物API
 */
export const deliverableApi = {
  /**
   * 获取群聊交付物列表
   *
   * @param groupId - 群聊ID
   * @returns 交付物列表
   */
  listByGroup(groupId: string) {
    return apiClient.get<PaginatedResponse<DeliverableListItem>>(`/groups/${groupId}/deliverables`);
  },

  /**
   * 获取项目交付物列表
   *
   * @param projectId - 项目ID
   * @returns 交付物列表
   */
  listByProject(projectId: string) {
    return apiClient.get<PaginatedResponse<DeliverableListItem>>(`/projects/${projectId}/deliverables`);
  },

  /**
   * 获取交付物详情
   *
   * @param id - 交付物ID
   * @returns 交付物详情
   */
  get(id: string) {
    return apiClient.get<Deliverable>(`/deliverables/${id}`);
  },

  /**
   * 创建交付物
   *
   * @param data - 创建参数
   * @returns 创建的交付物
   */
  create(data: CreateDeliverableRequest) {
    return apiClient.post<Deliverable>('/deliverables', data);
  },

  /**
   * 更新交付物
   *
   * @param id - 交付物ID
   * @param data - 更新参数
   * @returns 更新后的交付物
   */
  update(id: string, data: UpdateDeliverableRequest) {
    return apiClient.put<Deliverable>(`/deliverables/${id}`, data);
  },

  /**
   * 获取交付物版本列表
   *
   * @param id - 交付物ID
   * @returns 版本列表
   */
  listVersions(id: string) {
    return apiClient.get<DeliverableVersion[]>(`/deliverables/${id}/versions`);
  },

  /**
   * 获取特定版本内容
   *
   * @param id - 交付物ID
   * @param version - 版本号
   * @returns 版本内容
   */
  getVersion(id: string, version: number) {
    return apiClient.get<DeliverableVersion>(`/deliverables/${id}/versions/${version}`);
  },

  /**
   * 版本对比
   *
   * @param id - 交付物ID
   * @param v1 - 版本1
   * @param v2 - 版本2
   * @returns 对比结果
   */
  diff(id: string, v1: number, v2: number) {
    return apiClient.get<DeliverableDiff>(`/deliverables/${id}/diff`, { v1, v2 });
  },
};

export default deliverableApi;

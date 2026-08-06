/**
 * 任务API模块
 *
 * 封装任务相关的API调用。
 */

import { apiClient } from './client';
import {
  ApiResponse,
  PaginatedResponse,
  Task,
  TaskListItem,
  CreateTaskRequest,
  UpdateTaskRequest,
  UpdateTaskStatusRequest,
  ChainView,
  GroupChainTree,
  Message,
  SendMessageRequest,
  StopAgentRequest,
} from '../types';

/**
 * 任务API
 */
export const taskApi = {
  /**
   * 获取群聊任务列表
   *
   * @param groupId - 群聊ID
   * @returns 任务列表
   */
  list(groupId: string) {
    return apiClient.get<PaginatedResponse<TaskListItem>>(`/groups/${groupId}/tasks`);
  },

  /**
   * 获取任务详情
   *
   * @param id - 任务ID
   * @returns 任务详情
   */
  get(id: string) {
    return apiClient.get<Task>(`/tasks/${id}`);
  },

  /**
   * 创建任务
   *
   * @param groupId - 群聊ID
   * @param data - 创建参数
   * @returns 创建的任务
   */
  create(groupId: string, data: CreateTaskRequest) {
    return apiClient.post<Task>(`/groups/${groupId}/tasks`, data);
  },

  /**
   * 更新任务
   *
   * @param id - 任务ID
   * @param data - 更新参数
   * @returns 更新后的任务
   */
  update(id: string, data: UpdateTaskRequest) {
    return apiClient.put<Task>(`/tasks/${id}`, data);
  },

  /**
   * 更新任务状态
   *
   * @param id - 任务ID
   * @param data - 状态更新参数
   * @returns 更新后的任务
   */
  updateStatus(id: string, data: UpdateTaskStatusRequest) {
    return apiClient.patch<Task>(`/tasks/${id}/status`, data);
  },

  /**
   * 删除任务
   *
   * @param id - 任务ID
   */
  delete(id: string) {
    return apiClient.delete<void>(`/tasks/${id}`);
  },
};

/**
 * Chain API
 */
export const chainApi = {
  /**
   * 获取Chain消息列表
   *
   * @param chainId - Chain ID
   * @returns 消息列表
   */
  listMessages(chainId: string) {
    return apiClient.get<PaginatedResponse<Message>>(`/chains/${chainId}/messages`);
  },

  /**
   * 发送消息（用户）
   *
   * @param chainId - Chain ID
   * @param data - 消息参数
   * @returns 发送的消息
   */
  sendMessage(chainId: string, data: SendMessageRequest) {
    return apiClient.post<Message>(`/chains/${chainId}/messages`, data);
  },

  /**
   * 停止Agent
   *
   * @param chainId - Chain ID
   * @param data - 停止参数
   */
  stopAgent(chainId: string, data: StopAgentRequest) {
    return apiClient.post<void>(`/chains/${chainId}/stop`, data);
  },

  /**
   * 恢复讨论
   *
   * @param chainId - Chain ID
   */
  resume(chainId: string) {
    return apiClient.post<void>(`/chains/${chainId}/resume`);
  },

  /**
   * 获取链视图（包列表 + 子链摘要）
   *
   * @param chainId - Chain ID
   * @param depth - 子链展开深度（0-3）
   * @returns 链视图
   */
  getView(chainId: string, depth: number = 1) {
    return apiClient.get<ChainView>(`/chains/${chainId}/view`, { depth });
  },

  /**
   * 获取群聊的链树
   *
   * @param groupId - 群聊ID
   * @returns 群链树
   */
  getGroupChains(groupId: string) {
    return apiClient.get<GroupChainTree>(`/groups/${groupId}/chains`);
  },
};

export default { taskApi, chainApi };

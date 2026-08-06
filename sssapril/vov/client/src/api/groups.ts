/**
 * 群聊API模块
 *
 * 封装群聊相关的API调用。
 */

import { apiClient } from './client';
import {
  ApiResponse,
  PaginatedResponse,
  Group,
  GroupListItem,
  CreateGroupRequest,
  UpdateGroupRequest,
  ReorderGroupsRequest,
  AddGroupMemberRequest,
  GroupMember,
  ChatResponse,
  ChatStreamResult,
  ChatStreamAttachResult,
  Message,
} from '../types';

/**
 * 群聊API
 */
export const groupApi = {
  /**
   * 获取项目的群聊列表
   *
   * @param projectId - 项目ID
   * @returns 群聊列表
   */
  list(projectId: string) {
    return apiClient.get<PaginatedResponse<GroupListItem>>(`/projects/${projectId}/groups`);
  },

  /**
   * 获取群聊详情
   *
   * @param id - 群聊ID
   * @returns 群聊详情
   */
  get(id: string) {
    return apiClient.get<Group>(`/groups/${id}`);
  },

  /**
   * 创建群聊
   *
   * @param projectId - 项目ID
   * @param data - 创建参数
   * @returns 创建的群聊
   */
  create(projectId: string, data: CreateGroupRequest) {
    return apiClient.post<Group>(`/projects/${projectId}/groups`, data);
  },

  /**
   * 更新群聊
   *
   * @param id - 群聊ID
   * @param data - 更新参数
   * @returns 更新后的群聊
   */
  update(id: string, data: UpdateGroupRequest) {
    return apiClient.put<Group>(`/groups/${id}`, data);
  },

  /**
   * 删除群聊
   *
   * @param id - 群聊ID
   */
  delete(id: string) {
    return apiClient.delete<void>(`/groups/${id}`);
  },

  /**
   * 群聊排序
   *
   * @param projectId - 项目ID
   * @param data - 排序参数
   */
  reorder(projectId: string, data: ReorderGroupsRequest) {
    return apiClient.put<void>(`/projects/${projectId}/groups/reorder`, data);
  },

  /**
   * 获取群聊成员列表
   *
   * @param groupId - 群聊ID
   * @returns 成员列表
   */
  listMembers(groupId: string) {
    return apiClient.get<PaginatedResponse<GroupMember>>(`/groups/${groupId}/members`);
  },

  /**
   * 添加群聊成员
   *
   * @param groupId - 群聊ID
   * @param data - 添加参数
   * @returns 添加的成员
   */
  addMember(groupId: string, data: AddGroupMemberRequest) {
    return apiClient.post<GroupMember>(`/groups/${groupId}/members`, data);
  },

  /**
   * 移除群聊成员
   *
   * @param groupId - 群聊ID
   * @param agentId - Agent ID
   */
  removeMember(groupId: string, agentId: string) {
    return apiClient.delete<void>(`/groups/${groupId}/members/${agentId}`);
  },

  updateMemberRole(groupId: string, agentId: string, role: string) {
    return apiClient.put<GroupMember>(`/groups/${groupId}/members/${agentId}/role`, { role });
  },

  /**
   * 发送消息并获取Agent响应
   *
   * @param groupId - 群聊ID
   * @param content - 消息内容
   * @param targetAgentId - 指定响应的Agent ID
   * @returns 用户消息和Agent响应
   */
  chat(groupId: string, content: string, targetAgentId?: string) {
    return apiClient.post<ChatResponse>(`/groups/${groupId}/chat`, { content, target_agent_id: targetAgentId });
  },

  /**
   * 流式发送消息 (v2: POST 返回 JSON, 事件通过 WebSocket 推送)
   *
   * 后端流程:
   *   1. 保存用户消息 + 创建占位 agent packet
   *   2. 通过 WebSocket 广播 user_message / chain_start
   *   3. 启动后台 LLM task (token/tool_call 等通过 WebSocket 实时推送)
   *   4. 立即返回 {chain_id, packet_id, ...}
   *
   * 前端通过 useChatStream.handleStreamEvent 接收 WebSocket 事件:
   *   token / tool_call / tool_result / render_spec / chain_end / done / error
   *
   * @param groupId - 群聊ID
   * @param content - 消息内容
   * @param targetAgentId - 指定响应的Agent ID
   * @returns 流式 session 元信息
   */
  async chatStream(
    groupId: string,
    content: string,
    targetAgentId?: string,
  ): Promise<ChatStreamResult> {
    const res = await apiClient.post<ChatStreamResult>(
      `/groups/${groupId}/chat/stream`,
      { content, target_agent_id: targetAgentId },
    );
    if (!res.data) throw new Error('empty response from /chat/stream');
    return res.data;
  },

  /**
   * 查询正在进行的流的状态 (v2: POST 返回 snapshot, 事件通过 WebSocket 推送)
   *
   * 返回当前快照:
   *   - 有活跃流: {active: true, chain_id, packet_id, content, metadata, chain_start}
   *   - 无活跃流: {active: false}
   *
   * 前端拿到快照后, 通过 useChatStream.handleStreamEvent 接收后续 WebSocket 事件。
   *
   * @param groupId  - 群聊ID
   * @param packetId - 目标 packet ID (优先)
   * @param chainId  - 目标 chain ID (fallback)
   */
  async chatStreamAttach(
    groupId: string,
    packetId: string | undefined,
    chainId: string | undefined,
  ): Promise<ChatStreamAttachResult> {
    const res = await apiClient.post<ChatStreamAttachResult>(
      `/groups/${groupId}/chat/stream/attach`,
      { packet_id: packetId, chain_id: chainId },
    );
    return (
      res.data ?? {
        active: false,
        group_id: groupId,
        chain_id: chainId,
        packet_id: packetId,
      }
    );
  },

  /**
   * 主动停止一个流（用户按 Stop 按钮时调用）
   */
  async chatStreamCancel(
    groupId: string,
    packetId?: string,
    chainId?: string,
  ): Promise<{ cancelled: boolean }> {
    const res = await apiClient.post<{ cancelled: boolean }>(
      `/groups/${groupId}/chat/stream/cancel`,
      { packet_id: packetId, chain_id: chainId },
    );
    return res.data ?? { cancelled: false };
  },

  /**
   * 快速查询 group / chain / packet 是否有活跃流（不建立 SSE 连接）
   */
  async chatStreamStatus(
    groupId: string,
    chainId?: string,
    packetId?: string,
  ): Promise<{
    active: boolean;
    chain_id?: string;
    packet_id?: string;
    is_streaming?: boolean;
    is_cancelled?: boolean;
    content_length?: number;
  }> {
    const res = await apiClient.get<{
      active: boolean;
      chain_id?: string;
      packet_id?: string;
      is_streaming?: boolean;
      is_cancelled?: boolean;
      content_length?: number;
    }>(`/groups/${groupId}/chat/stream/status`, {
      chain_id: chainId,
      packet_id: packetId,
    });
    return res.data ?? { active: false };
  },

  /**
   * 获取群聊历史消息
   *
   * @param groupId - 群聊ID
   * @param limit - 返回消息数量上限
   * @returns 历史消息列表
   */
  getMessages(groupId: string, limit: number = 50) {
    return apiClient.get<Message[]>(`/groups/${groupId}/messages`, { limit });
  },

  /**
   * 解析消息中的@mention，返回匹配的Agent ID
   *
   * @param groupId - 群聊ID
   * @param content - 消息内容
   * @returns 匹配的Agent ID
   */
  resolveMention(groupId: string, content: string) {
    return apiClient.get<{ agent_id: string | null }>(`/groups/${groupId}/resolve-mention`, { content });
  },
};

export default groupApi;

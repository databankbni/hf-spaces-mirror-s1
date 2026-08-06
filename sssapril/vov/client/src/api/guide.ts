/**
 * 引导 agent API
 *
 * 提供引导 project 的幂等初始化与状态查询。
 * 引导 project 是每用户一个的 is_guide 标记 project，
 * 用于承载 L0/L1/L2 引导 agent 的对话与工具调用。
 */

import { apiClient } from './client';

/**
 * 引导状态
 *
 * 包含引导 project / agent / group 的 id 与展示信息。
 * 前端 UniversalChat 拿到 group_id 后即可接入 useChatStream。
 */
export interface GuideState {
  project_id: string;
  agent_id: string;
  project_agent_id: string;
  group_id: string;
  agent_name: string;
  agent_avatar: string | null;
  group_name: string;
}

export const guideApi = {
  /**
   * L0: 幂等初始化引导 project
   *
   * 首次调用创建 project+agent+group，后续调用返回已有状态。
   * UniversalChat 首页（L0）挂载时调用。
   */
  ensure() {
    return apiClient.post<GuideState>('/guide/ensure');
  },

  /**
   * L1: 幂等确保项目有 coordinator + 项目引导群
   *
   * 进入项目页 (/project/:id) 时调用。
   * 确保项目有 coordinator agent 和引导群聊，返回 group_id 接入 useChatStream。
   */
  ensureProject(projectId: string) {
    return apiClient.post<GuideState>(`/guide/ensure_project?project_id=${encodeURIComponent(projectId)}`);
  },

  /**
   * 查询引导状态（只查不建）
   *
   * 用于在不触发创建的前提下判断是否已初始化。
   */
  getState() {
    return apiClient.get<GuideState | null>('/guide/state');
  },
};

/**
 * 任务相关类型定义模块
 *
 * 定义任务(Task)相关的TypeScript类型。
 */

import { TaskStatus } from './common';
import { Agent } from './agent';
import { Deliverable } from './deliverable';

/**
 * 任务基础信息
 */
export interface TaskBase {
  /** 任务ID */
  id: string;
  /** 所属群聊ID */
  group_id: string;
  /** 任务标题 */
  title: string;
  /** 任务描述 */
  description: string | null;
  /** 任务状态 */
  status: TaskStatus;
  /** 排序索引 */
  order_index: number;
  /** 验收标准 */
  acceptance_criteria: string | null;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
  /** 开始时间 */
  started_at: string | null;
  /** 完成时间 */
  completed_at: string | null;
  /** v2 P2: 任务链是否继承主链截至分支点的历史 */
  inherit_main_chain: boolean;
}

/**
 * 任务负责人 / 指派 Agent 的轻量摘要（卡片/弹窗用，避免把整个 Agent 全量下发）
 */
export interface TaskAgentBrief {
  /** project_agent.id（任务指派表主键），便于做反查/编辑 */
  id: string;
  /** project_agent_id（与 lead_agent.id 对齐） */
  project_agent_id?: string;
  /** 底层 Agent 名称 */
  name: string;
  /** 头像（URL 或 emoji） */
  avatar: string | null;
}

/**
 * 任务链摘要（卡片/弹窗用，不暴露整条链）
 */
export interface TaskChainBrief {
  id: string;
  status: ChainStatus;
  packet_count: number;
}

/**
 * 任务列表项
 */
export interface TaskListItem extends TaskBase {
  /** 任务主导 Agent（task 负责人） */
  lead_agent: TaskAgentBrief | null;
  /** 指派的 Agent 列表（参与者） */
  assignees: TaskAgentBrief[];
  /** 任务链 ID（兼容老字段，等价于 chain?.id） */
  chain_id: string | null;
  /** 任务链摘要 */
  chain: TaskChainBrief | null;
  /** 交付物摘要 */
  deliverable: Deliverable | null;
}

/**
 * 任务详情
 */
export interface Task extends TaskBase {
  /** 主导Agent信息 */
  lead_agent: Agent | null;
  /** 指派的Agent列表 */
  assignees: Agent[];
  /** 讨论链 */
  chain: Chain | null;
  /** 交付物 */
  deliverable: Deliverable | null;
}

/**
 * 链类型枚举
 */
export type ChainType = 'group' | 'task' | 'reply' | 'tool';

/**
 * 链状态枚举
 *
 * 对齐后端 Chain.status 字段 (含 v2 P2 新增的 paused/archived):
 *   - pending:   任务链已创建但任务未开始 (in_progress 之前)
 *   - active:    当前正在接收/生成 packet 的活跃链 (主链 or task chain)
 *   - paused:    主链被任务链接管时挂起 (v2 P2 任务接管主链机制)
 *   - completed: 历史链正常结束 (群聊通常不会进此状态)
 *   - archived:  任务 done 后 task chain 折叠归档到主链 (v2 P2)
 *   - failed:    异常退出
 */
export type ChainStatus = 'pending' | 'active' | 'paused' | 'completed' | 'archived' | 'failed';

/**
 * 包类型枚举
 */
export type PacketType = 'user_input' | 'agent_text' | 'think' | 'tool_call' | 'tool_result' | 'error' | 'system';

/**
 * 包发送者类型枚举
 */
export type PacketSenderType = 'user' | 'agent' | 'system' | 'tool';

/**
 * 讨论链信息（对齐后端 Chain 模型）
 */
export interface Chain {
  /** 链ID */
  id: string;
  /** 父链ID（群链为null） */
  parent_chain_id: string | null;
  /** 链类型 */
  chain_type: ChainType;
  /** 所属群聊ID */
  group_id: string;
  /** 关联任务ID（task链才有） */
  task_id: string | null;
  /** 执行Agent ID（reply/tool链才有） */
  agent_id: string | null;
  /** 链状态 */
  status: ChainStatus;
  /** 链头包ID */
  head_packet_id: string | null;
  /** 链尾包ID */
  tail_packet_id: string | null;
  /** 描述 */
  description: string | null;
  /** 包数量 */
  packet_count: number;
  /** 子链数量 */
  sub_chain_count: number;
  /** 完成时间 */
  completed_at: string | null;
  /** 创建时间 */
  created_at: string;
}

/**
 * 包信息（对齐后端 Packet 模型）
 */
export interface Packet {
  /** 包ID */
  id: string;
  /** 所属链ID */
  chain_id: string;
  /** 链内前一个包ID */
  prev_packet_id: string | null;
  /** 包类型 */
  packet_type: PacketType;
  /** 发送者类型 */
  sender_type: PacketSenderType;
  /** 发送者ID */
  sender_id: string;
  /** 发送者显示名称 */
  sender_name: string;
  /** 内容 */
  content: string;
  /** 内容类型 */
  content_type: string;
  /** 本包触发的子链ID */
  sub_chain_id: string | null;
  /** 扩展元数据 */
  metadata: Record<string, unknown>;
  /** 创建时间 */
  created_at: string;
}

/**
 * 链视图响应（GET /chains/{id}/view）
 */
export interface ChainView {
  /** 链信息 */
  chain: Chain;
  /** 包列表 */
  packets: Packet[];
  /** 子链摘要列表 */
  sub_chains: ChainView[];
}

/**
 * 群聊链树响应（GET /groups/{id}/chains）
 */
export interface GroupChainTree {
  /** 群链 */
  chain: Chain | null;
  /** 任务链列表 */
  sub_chains: Chain[];
}

/**
 * 创建任务请求参数
 */
export interface CreateTaskRequest {
  /** 任务标题 */
  title: string;
  /** 任务描述 */
  description?: string;
  /** 验收标准 */
  acceptance_criteria?: string;
  /** 主导Agent ID */
  lead_agent_id?: string;
  /** 指派的Agent ID列表 */
  assignee_ids?: string[];
  /** 任务链是否继承主链截至分支点的历史 (true=接入主链, false=隔离上下文) */
  inherit_main_chain?: boolean;
}

/**
 * 更新任务请求参数
 */
export interface UpdateTaskRequest {
  /** 任务标题 */
  title?: string;
  /** 任务描述 */
  description?: string;
  /** 验收标准 */
  acceptance_criteria?: string;
  /** 主导Agent ID */
  lead_agent_id?: string;
  /** 任务链是否继承主链截至分支点的历史 (true=接入主链, false=隔离上下文) */
  inherit_main_chain?: boolean;
}

/**
 * 更新任务状态请求参数
 */
export interface UpdateTaskStatusRequest {
  /** 新状态 */
  status: TaskStatus;
}

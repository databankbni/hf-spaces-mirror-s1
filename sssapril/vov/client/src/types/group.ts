/**
 * 群聊相关类型定义模块
 *
 * 定义群聊(Group)相关的TypeScript类型。
 */

import { GroupStatus, AutonomyLevel } from './common';
import { GroupMember } from './agent';
import { Task } from './task';
import { Deliverable } from './deliverable';
import { Resource } from './resource';

/**
 * 群聊基础信息
 */
export interface GroupBase {
  /** 群聊ID */
  id: string;
  /** 所属项目ID */
  project_id: string;
  /** 群聊名称 */
  name: string;
  /** 群聊描述 */
  description: string | null;
  /** 群聊状态 */
  status: GroupStatus;
  /** 排序索引 */
  order_index: number;
  /** 自主级别 */
  autonomy_level: AutonomyLevel;
  /** 完成后是否自动推进 */
  auto_advance: boolean;
  /** 空闲 watchdog 监控本群开关 (默认 true, 关后不消耗 lead LLM token) */
  watchdog_enabled: boolean;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/**
 * 群聊列表项
 *
 * 用于群聊列表展示，包含统计信息。
 */
export interface GroupListItem extends GroupBase {
  /** 主导Agent信息 */
  lead_agent: {
    id: string;
    name: string;
    role: string;
    avatar: string | null;
  } | null;
  /** 成员数量 */
  member_count: number;
  /** 任务总数 */
  task_count: number;
  /** 已完成任务数 */
  done_task_count: number;
  /** 消息数量 */
  message_count: number;
  /** 交付物数量 */
  deliverable_count: number;
}

/**
 * 群聊详情
 *
 * 包含群聊的完整信息。
 */
export interface Group extends GroupBase {
  /** 主导Agent信息 */
  lead_agent: GroupMember | null;
  /** 成员列表 */
  members: GroupMember[];
  /** 任务列表 */
  tasks: Task[];
  /** 群聊资源 */
  resources: Resource[];
  /** 群聊交付物 */
  deliverables: Deliverable[];
}

/**
 * 创建群聊请求参数
 */
export interface CreateGroupRequest {
  /** 群聊名称 */
  name: string;
  /** 群聊描述 */
  description?: string;
  /** 自主级别 */
  autonomy_level?: AutonomyLevel;
  /** 主导Agent ID */
  lead_agent_id?: string;
  /** 成员Agent ID列表 */
  member_agent_ids?: string[];
  /** 是否自动推进 */
  auto_advance?: boolean;
}

/**
 * 更新群聊请求参数
 */
export interface UpdateGroupRequest {
  /** 群聊名称 */
  name?: string;
  /** 群聊描述 */
  description?: string;
  /** 自主级别 */
  autonomy_level?: AutonomyLevel;
  /** 主导Agent ID */
  lead_agent_id?: string;
  /** 是否自动推进 */
  auto_advance?: boolean;
  /** 空闲 watchdog 监控本群开关 */
  watchdog_enabled?: boolean;
  /** 群聊状态 */
  status?: GroupStatus;
}

/**
 * 群聊排序请求参数
 */
export interface ReorderGroupsRequest {
  /** 排序后的群聊ID列表 */
  ordered_ids: string[];
}

/**
 * 添加群聊成员请求参数
 */
export interface AddGroupMemberRequest {
  /** 项目Agent ID */
  project_agent_id: string;
  /** 成员角色 */
  role?: 'lead' | 'participant';
}

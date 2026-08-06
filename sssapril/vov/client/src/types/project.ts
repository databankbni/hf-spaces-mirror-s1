/**
 * 项目相关类型定义模块
 *
 * 定义项目(Project)相关的TypeScript类型。
 */

import { ProjectStatus } from './common';
import { Group } from './group';
import { ProjectAgent } from './agent';
import { Resource } from './resource';

/**
 * 项目基础信息
 *
 * 包含项目的基本字段，用于列表展示。
 */
export interface ProjectBase {
  /** 项目ID */
  id: string;
  /** 项目名称 */
  name: string;
  /** 项目描述 */
  description: string | null;
  /** 封面渐变色 */
  cover_color: string | null;
  /** 项目标签 */
  tags: string[];
  /** 项目状态 */
  status: ProjectStatus;
  /** 是否为引导 project（不展示在项目列表） */
  is_guide?: boolean;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/**
 * 项目列表项
 *
 * 用于项目列表展示，包含统计信息。
 */
export interface ProjectListItem extends ProjectBase {
  /** 群聊数量 */
  group_count: number;
  /** Agent数量 */
  agent_count: number;
  /** 任务总数 */
  task_count: number;
  /** 已完成任务数 */
  done_task_count: number;
}

/**
 * 项目详情
 *
 * 包含项目的完整信息，包括关联的群聊、Agent、资源等。
 */
export interface Project extends ProjectBase {
  /** 工作流配置 */
  workflow_config: WorkflowConfig;
  /** 群聊列表 */
  groups: Group[];
  /** 项目Agent列表 */
  agents: ProjectAgent[];
  /** 全局资源列表 */
  resources: Resource[];
}

/**
 * 工作流配置
 *
 * 控制项目工作流的行为。
 */
export interface WorkflowConfig {
  /** 是否默认自动推进 */
  auto_advance?: boolean;
}

/**
 * 创建项目请求参数
 */
export interface CreateProjectRequest {
  /** 项目名称 */
  name: string;
  /** 项目描述 */
  description?: string;
  /** 封面色 */
  cover_color?: string;
  /** 标签 */
  tags?: string[];
}

/**
 * 更新项目请求参数
 */
export interface UpdateProjectRequest {
  /** 项目名称 */
  name?: string;
  /** 项目描述 */
  description?: string;
  /** 封面色 */
  cover_color?: string;
  /** 标签 */
  tags?: string[];
  /** 项目状态 */
  status?: ProjectStatus;
  /** 工作流配置 */
  workflow_config?: WorkflowConfig;
}

/**
 * 项目筛选参数
 */
export interface ProjectFilters {
  /** 按状态筛选 */
  status?: ProjectStatus;
  /** 搜索关键词 */
  search?: string;
}

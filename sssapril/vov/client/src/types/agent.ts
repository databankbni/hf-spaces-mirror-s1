/**
 * Agent相关类型定义模块
 *
 * 定义Agent相关的TypeScript类型，包括全局Agent、项目Agent等。
 *
 * v2 P3: 删除 AgentRole 枚举. agent 的"职业身份"由 system_prompt 表达,
 * "分类/标签"通过 capabilities 描述. 不再有硬编码的角色白名单.
 */

import { ContentType } from './common';

/**
 * Agent工具定义
 */
export interface AgentTool {
  /** 工具ID */
  id: string;
  /** 工具名称 */
  name: string;
  /** 工具处理器标识，对应 agentflow processor kind */
  kind: string | null;
  /** 工具描述 */
  description: string | null;
  /** 工具类型 */
  tool_type: string;
  /** 工具配置 */
  config: Record<string, unknown>;
}

/**
 * 技能定义（独立实体，可被多个 Agent 复用）
 */
export interface Skill {
  /** 技能ID */
  id: string;
  /** 技能名称 */
  name: string;
  /** 技能描述 */
  description: string | null;
  /** 技能类型 */
  skill_type: string;
  /** 技能内容 */
  content: string | null;
  /** 技能配置 */
  config: Record<string, unknown>;
  /** 附加文件 {filename: content} */
  files: Record<string, string>;
  /** 创建时间 */
  created_at?: string;
  /** 更新时间 */
  updated_at?: string;
}

/** @deprecated 使用 Skill 替代 */
export type AgentSkill = Skill;

/**
 * 模型配置
 */
export interface ModelConfig {
  /** 模型名称 */
  model?: string;
  /** 温度参数 */
  temperature?: number;
  /** 最大token数 */
  max_tokens?: number;
  /** 其他配置 */
  [key: string]: unknown;
}

/**
 * 全局Agent
 *
 * Agent是可复用的AI角色定义。
 */
export interface Agent {
  /** Agent ID */
  id: string;
  /** Agent名称 */
  name: string;
  // v2 P3: 删除 role 字段
  /** 头像（URL或emoji） */
  avatar: string | null;
  /** 描述 */
  description: string | null;
  /** 系统提示词 */
  system_prompt: string;
  /** 模型配置 */
  llm_config: ModelConfig;
  /** 能力描述列表 */
  capabilities: string[];
  /** 是否启用 */
  is_active: boolean;
  /** 绑定的工具 */
  tools: AgentTool[];
  /** 绑定的技能 */
  skills: AgentSkill[];
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/**
 * 项目Agent
 *
 * 将全局Agent关联到项目，可覆盖部分配置。
 */
export interface ProjectAgent {
  /** 项目Agent ID */
  id: string;
  /** 关联的全局Agent */
  agent: Agent;
  /** 项目内覆盖配置 */
  override_config: Record<string, unknown>;
  /** 在项目中的个人笔记 */
  memory: AgentMemory | null;
  /** 创建时间 */
  created_at: string;
}

/**
 * Agent个人笔记
 *
 * Agent在项目中的知识积累，跨群聊共用。
 */
export interface AgentMemory {
  /** 笔记ID */
  id: string;
  /** Agent ID */
  agent_id: string;
  /** 项目ID */
  project_id: string;
  /** 笔记内容（Markdown） */
  content: string;
  /** 内容类型 */
  content_type: ContentType;
  /** 笔记分类标识（如 default、role、task 等） */
  slug?: string;
  /** 标签 */
  tags: string[];
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/**
 * 群聊成员
 *
 * Agent在群聊中的角色信息。
 */
export interface GroupMember {
  /** 成员记录ID */
  id: string;
  /** 项目Agent ID */
  project_agent_id: string;
  /** 关联的Agent信息 */
  agent: Agent;
  /** 成员角色 */
  role: 'lead' | 'participant';
  /** 加入时间 */
  joined_at: string;
}

/**
 * 创建Agent请求参数
 */
export interface CreateAgentRequest {
  /** Agent名称 */
  name: string;
  // v2 P3: 删除 role 字段
  /** 头像 */
  avatar?: string;
  /** 描述 */
  description?: string;
  /** 系统提示词 */
  system_prompt: string;
  /** 模型配置 */
  llm_config?: ModelConfig;
  /** 能力描述 */
  capabilities?: string[];
  /** 工具列表 */
  tools?: Omit<AgentTool, 'id'>[];
  /** 绑定的技能ID列表 */
  skill_ids?: string[];
}

/**
 * 更新Agent请求参数
 */
export interface UpdateAgentRequest {
  /** Agent名称 */
  name?: string;
  // v2 P3: 删除 role 字段
  /** 头像 */
  avatar?: string;
  /** 描述 */
  description?: string;
  /** 系统提示词 */
  system_prompt?: string;
  /** 模型配置 */
  llm_config?: ModelConfig;
  /** 能力描述 */
  capabilities?: string[];
  /** 是否启用 */
  is_active?: boolean;
  /** 工具列表 */
  tools?: Omit<AgentTool, 'id'>[];
  /** 绑定的技能ID列表 */
  skill_ids?: string[];
}

/**
 * Agent筛选参数
 */
export interface AgentFilters {
  // v2 P3: 删除 role 字段
  /** 搜索关键词 */
  search?: string;
  /** 允许任意筛选参数 */
  [key: string]: string | number | boolean | undefined;
}

/**
 * 项目模板 API 客户端
 */

import { apiClient } from './client'
import type { ApiResponse } from '../types'

/** 模板摘要（用于列表展示） */
export interface TemplateSummary {
  template_id: string
  name: string
  description: string
  version: string
  cover_color?: string | null
  emoji?: string | null
  tags: string[]
  preview: {
    agent_count: number
    skill_count: number
    group_count: number
    task_count: number
    resource_count: number
  }
}

/** 模板详情（包含完整 skills/agents/groups/resources） */
export interface TemplateDetail extends TemplateSummary {
  skills: Array<{
    name: string
    description?: string
    skill_type: string
    content: string
    config?: Record<string, unknown>
  }>
  agents: Array<{
    name: string
    role: string
    avatar?: string
    description?: string
    system_prompt: string
    llm_config?: Record<string, unknown>
    capabilities?: string[]
    tools: Array<{
      name: string
      kind?: string
      tool_type?: string
      description?: string
      config?: Record<string, unknown>
    }>
    skill_refs: string[]
  }>
  groups: Array<{
    name: string
    description?: string
    lead_agent?: string
    autonomy_level: string
    auto_advance: boolean
    order_index: number
    members: Array<{ agent_name: string; role: string }>
    tasks: Array<{
      title: string
      description?: string
      lead_agent?: string
      assignees: string[]
      acceptance_criteria?: string
      order_index: number
    }>
  }>
  resources: Array<{
    title: string
    content_type: string
    resource_type: string
    is_required: boolean
    tags: string[]
    content: string
  }>
}

/** 应用模板的请求 */
export interface ApplyTemplateRequest {
  template_id: string
  project_name: string
  project_description?: string
  cover_color?: string
  project_tags?: string[]
}

/** 应用模板的响应 */
export interface ApplyTemplateResult {
  project_id: string
  project_name: string
  created_skills: string[]
  reused_skills: string[]
  created_agents: string[]
  reused_agents: string[]
  project_agent_count: number
  group_count: number
  task_count: number
  resource_count: number
  summary: string
}

/** 项目模板 API */
export const templatesApi = {
  /** 列出所有可用模板 */
  list(): Promise<ApiResponse<TemplateSummary[]>> {
    return apiClient.get<TemplateSummary[]>('/templates')
  },

  /** 获取模板详情 */
  get(templateId: string): Promise<ApiResponse<TemplateDetail>> {
    return apiClient.get<TemplateDetail>(`/templates/${templateId}`)
  },

  /** 应用模板创建项目 */
  apply(payload: ApplyTemplateRequest): Promise<ApiResponse<ApplyTemplateResult>> {
    return apiClient.post<ApplyTemplateResult>('/templates/apply', payload)
  },
}

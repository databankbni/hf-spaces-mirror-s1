/**
 * 资源相关类型定义模块
 *
 * 定义资源(Resource)和标签(Tag)相关的TypeScript类型。
 */

import { ContentType, ResourceType, Scope } from './common';

/**
 * 资源信息
 *
 * 资料是项目/群聊的参考材料。
 */
export interface Resource {
  /** 资源ID */
  id: string;
  /** 所属项目ID */
  project_id: string;
  /** 所属群聊ID（NULL表示全局资源） */
  group_id: string | null;
  /** 资源标题 */
  title: string;
  /** 资源内容（Markdown） */
  content: string;
  /** 内容类型 */
  content_type: ContentType;
  /** 资源类型 */
  type: ResourceType;
  /** 标签列表 */
  tags: string[];
  /** 是否必读 */
  is_required: boolean;
  /** 创建者 */
  created_by: string;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/**
 * 创建资源请求参数
 */
export interface CreateResourceRequest {
  /** 资源标题 */
  title: string;
  /** 资源内容 */
  content: string;
  /** 内容类型 */
  content_type?: ContentType;
  /** 资源类型 */
  type?: ResourceType;
  /** 标签 */
  tags?: string[];
  /** 是否必读 */
  is_required?: boolean;
  /** 所属项目ID */
  project_id: string;
  /** 所属群聊ID（不传表示全局资源） */
  group_id?: string;
  /** 创建者 */
  created_by?: string;
}

/**
 * 更新资源请求参数
 */
export interface UpdateResourceRequest {
  /** 资源标题 */
  title?: string;
  /** 资源内容 */
  content?: string;
  /** 资源类型 */
  type?: ResourceType;
  /** 标签 */
  tags?: string[];
  /** 是否必读 */
  is_required?: boolean;
}

/**
 * 项目标签
 *
 * 每个项目独立管理自己的标签体系。
 */
export interface Tag {
  /** 标签ID */
  id: string;
  /** 所属项目ID */
  project_id: string;
  /** 标签名称 */
  name: string;
  /** 标签说明 */
  description: string | null;
  /** 建议的格式/模板 */
  suggested_template: string | null;
  /** 标签颜色 */
  color: string | null;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/**
 * 创建标签请求参数
 */
export interface CreateTagRequest {
  /** 标签名称 */
  name: string;
  /** 标签说明 */
  description?: string;
  /** 建议的格式/模板 */
  suggested_template?: string;
  /** 标签颜色 */
  color?: string;
}

/**
 * 更新标签请求参数
 */
export interface UpdateTagRequest {
  /** 标签名称 */
  name?: string;
  /** 标签说明 */
  description?: string;
  /** 建议的格式/模板 */
  suggested_template?: string;
  /** 标签颜色 */
  color?: string;
}

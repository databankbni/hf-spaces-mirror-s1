/**
 * 交付物相关类型定义模块
 *
 * 定义交付物(Deliverable)相关的TypeScript类型。
 */

import { ContentType, Scope } from './common';

/**
 * 交付物版本信息
 */
export interface DeliverableVersion {
  /** 版本ID */
  id: string;
  /** 交付物ID */
  deliverable_id: string;
  /** 版本号 */
  version: number;
  /** 该版本的内容 */
  content: string;
  /** 变更说明 */
  change_summary: string | null;
  /** 修改者 */
  created_by: string | null;
  /** 创建时间 */
  created_at: string;
}

/**
 * 交付物基础信息
 */
export interface DeliverableBase {
  /** 交付物ID */
  id: string;
  /** 关联的讨论链ID */
  chain_id: string | null;
  /** 所属群聊ID */
  group_id: string;
  /** 关联的任务ID */
  task_id: string | null;
  /** 交付物标题 */
  title: string;
  /** 内容类型 */
  content_type: ContentType;
  /** 交付物类型（标签） */
  type: string | null;
  /** 额外标签 */
  tags: string[];
  /** 作用域 */
  scope: Scope;
  /** 版本号 */
  version: number;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/**
 * 交付物列表项
 */
export interface DeliverableListItem extends DeliverableBase {
  /** 主导Agent信息 */
  author: {
    id: string;
    name: string;
    role: string;
  } | null;
}

/**
 * 交付物详情
 */
export interface Deliverable extends DeliverableBase {
  /** 交付物内容（Markdown） */
  content: string;
  /** 主导Agent信息 */
  author: {
    id: string;
    name: string;
    role: string;
  } | null;
  /** 参与Agent列表 */
  participants: {
    id: string;
    name: string;
    role: string;
  }[];
  /** 版本历史 */
  versions: DeliverableVersion[];
}

/**
 * 创建交付物请求参数
 */
export interface CreateDeliverableRequest {
  /** 交付物标题 */
  title: string;
  /** 交付物内容 */
  content: string;
  /** 内容类型 */
  content_type?: ContentType;
  /** 交付物类型 */
  type?: string;
  /** 标签 */
  tags?: string[];
  /** 作用域 */
  scope?: Scope;
  /** 关联的讨论链ID */
  chain_id?: string;
  /** 所属群聊ID */
  group_id: string;
  /** 关联的任务ID */
  task_id?: string;
  /** 主导Agent ID */
  author_id?: string;
  /** 参与Agent ID列表 */
  participant_ids?: string[];
}

/**
 * 更新交付物请求参数
 */
export interface UpdateDeliverableRequest {
  /** 交付物标题 */
  title?: string;
  /** 交付物内容 */
  content: string;
  /** 变更说明 */
  change_summary?: string;
  /** 标签 */
  tags?: string[];
  /** 作用域 */
  scope?: Scope;
}

/**
 * 版本对比结果
 */
export interface DeliverableDiff {
  /** 版本1 */
  v1: {
    version: number;
    content: string;
  };
  /** 版本2 */
  v2: {
    version: number;
    content: string;
  };
  /** 差异内容 */
  diff: DiffItem[];
}

/**
 * 差异项
 */
export interface DiffItem {
  /** 类型：equal/delete/insert */
  type: 'equal' | 'delete' | 'insert';
  /** 内容 */
  content: string;
}

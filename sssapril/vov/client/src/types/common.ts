/**
 * 通用类型定义模块
 *
 * 定义前端通用的类型，包括API响应、分页等。
 */

/**
 * API标准响应格式
 *
 * 与后端ApiResponse schema对应。
 *
 * @template T - 响应数据类型
 */
export interface ApiResponse<T> {
  /** 是否成功 */
  success: boolean;
  /** 响应数据 */
  data: T;
  /** 响应消息 */
  message?: string;
}

/**
 * 分页响应格式
 *
 * 与后端 PaginatedResponse schema 对应，使用 skip/limit（偏移量分页）。
 *
 * @template T - 列表项类型
 */
export interface PaginatedResponse<T> {
  /** 数据列表 */
  items: T[];
  /** 总数 */
  total: number;
  /** 跳过数量（偏移量） */
  skip: number;
  /** 每页数量限制 */
  limit: number;
}

/**
 * 分页查询参数
 */
export interface PaginationParams {
  /** 跳过数量，默认0 */
  skip?: number;
  /** 每页数量限制，默认100 */
  limit?: number;
}

/**
 * 项目状态枚举
 */
export type ProjectStatus = 'active' | 'paused' | 'completed' | 'archived';

/**
 * 群聊状态枚举
 */
export type GroupStatus = 'pending' | 'active' | 'completed';

/**
 * 任务状态枚举
 */
export type TaskStatus = 'todo' | 'in_progress' | 'done' | 'reopened';

/**
 * 自主级别枚举
 */
export type AutonomyLevel = 'full_auto' | 'semi_auto' | 'manual';


/**
 * 发送者类型枚举
 */
export type SenderType = 'agent' | 'user' | 'system';

/**
 * 资源类型枚举
 */
export type ResourceType = 'note' | 'reference' | 'guideline' | 'rule' | 'custom' | 'map';

/**
 * 作用域枚举
 */
export type Scope = 'group' | 'project';

/**
 * 内容类型枚举
 *
 * 对齐 render_engine 的视图类型，决定资料的编辑和预览方式：
 * - text: 纯文本（消息等场景）
 * - markdown: Markdown 编辑器 + MarkdownRenderer 预览
 * - map: 地图编辑器 + RenderEngine(view_type='map') 预览
 * - 其他（table/list/tree/document/card/stat/timeline）: JSON 编辑器 + RenderEngine 预览
 */
export type ContentType = 'text' | 'markdown' | 'json' | 'table' | 'list' | 'tree' | 'document' | 'card' | 'stat' | 'timeline' | 'map';

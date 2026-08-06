/** 统一导出导入类型定义 */

/** 可导出资源项 */
export interface ExportableItem {
  id: string
  type: 'skill' | 'agent' | 'project'
  name: string
  description?: string
  role?: string
  skill_type?: string
  skill_names?: string[]
}

/** 导出请求项 */
export interface ExportRequestItem {
  type: 'skill' | 'agent' | 'project'
  id: string
  selection?: Record<string, boolean>
}

/** 导入预览中的单项 */
export interface ImportPreviewItem {
  type: string
  scope: string
  name?: string
  title?: string
  description?: string
  [key: string]: unknown
}

/** 导入冲突项 */
export interface ImportConflict {
  item_type: string
  name: string
  existing_id: string
  existing_name: string
  suggested_action: 'overwrite' | 'rename' | 'skip'
  suggested_new_name?: string
}

/** 导入预览结果 */
export interface ImportPreviewResult {
  items: ImportPreviewItem[]
  conflicts: ImportConflict[]
  total: number
  conflict_count: number
}

/** 冲突解决方案 */
export interface ConflictResolution {
  item_index: number
  action: 'overwrite' | 'rename' | 'skip'
  new_name?: string
}

/** 导入执行结果 */
export interface ImportExecuteResult {
  created: string[]
  updated: string[]
  skipped: string[]
  errors: string[]
  summary: string
}

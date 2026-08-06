import { apiClient } from './client'
import type {
  ApiResponse,
  ExportableItem,
  ExportRequestItem,
  ImportPreviewResult,
  ImportExecuteResult,
  ConflictResolution,
} from '../types'

/** 统一导出 API */
export const exportApi = {
  /** 列出可导出的 skills */
  listSkills(): Promise<ApiResponse<ExportableItem[]>> {
    return apiClient.get<ExportableItem[]>('/unified-export-import/export/skills')
  },

  /** 列出可导出的 agents */
  listAgents(): Promise<ApiResponse<ExportableItem[]>> {
    return apiClient.get<ExportableItem[]>('/unified-export-import/export/agents')
  },

  /** 列出可导出的 projects */
  listProjects(): Promise<ApiResponse<ExportableItem[]>> {
    return apiClient.get<ExportableItem[]>('/unified-export-import/export/projects')
  },

  /** 导出选中资源为 ZIP */
  download(items: ExportRequestItem[], filename: string): Promise<void> {
    return apiClient.postDownload('/unified-export-import/export/download', items, filename)
  },
}

/** 统一导入 API */
export const importApi = {
  /** 上传 ZIP 预览导入内容 */
  preview(file: File): Promise<ApiResponse<ImportPreviewResult>> {
    return apiClient.upload<ImportPreviewResult>('/unified-export-import/import/preview', file)
  },

  /** 执行导入 */
  execute(file: File, resolutions: ConflictResolution[]): Promise<ApiResponse<ImportExecuteResult>> {
    return apiClient.upload<ImportExecuteResult>(
      '/unified-export-import/import/execute',
      file,
      { resolutions: JSON.stringify(resolutions) }
    )
  },
}

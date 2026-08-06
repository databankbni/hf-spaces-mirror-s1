import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { exportApi, importApi } from '../api/exportImport'
import type {
  ExportableItem,
  ExportRequestItem,
  ConflictResolution,
  ImportPreviewResult,
  ImportExecuteResult,
} from '../types'

/** 查询可导出的 skills */
export function useExportableSkills() {
  return useQuery({
    queryKey: ['exportable-skills'],
    queryFn: async () => {
      const res = await exportApi.listSkills()
      return res.data
    },
  })
}

/** 查询可导出的 agents */
export function useExportableAgents() {
  return useQuery({
    queryKey: ['exportable-agents'],
    queryFn: async () => {
      const res = await exportApi.listAgents()
      return res.data
    },
  })
}

/** 查询可导出的 projects */
export function useExportableProjects() {
  return useQuery({
    queryKey: ['exportable-projects'],
    queryFn: async () => {
      const res = await exportApi.listProjects()
      return res.data
    },
  })
}

/** 导出下载 */
export function useExportDownload() {
  return useMutation({
    mutationFn: ({ items, filename }: { items: ExportRequestItem[]; filename: string }) =>
      exportApi.download(items, filename),
    onSuccess: () => toast.success('导出成功'),
    onError: () => toast.error('导出失败'),
  })
}

/** 导入预览 */
export function useImportPreview() {
  return useMutation({
    mutationFn: (file: File) => importApi.preview(file),
    onError: () => toast.error('解析导入文件失败'),
  })
}

/** 执行导入 */
export function useImportExecute() {
  return useMutation({
    mutationFn: ({ file, resolutions }: { file: File; resolutions: ConflictResolution[] }) =>
      importApi.execute(file, resolutions),
    onSuccess: (res) => {
      const data = res.data
      toast.success(data.summary || '导入完成')
    },
    onError: () => toast.error('导入失败'),
  })
}

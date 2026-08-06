/**
 * 项目模板相关 hooks
 */

import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { templatesApi } from '../api/templates'
import type { ApplyTemplateRequest } from '../api/templates'

/** 列出所有可用模板 */
export function useTemplateList() {
  return useQuery({
    queryKey: ['templates'],
    queryFn: async () => {
      const res = await templatesApi.list()
      return res.data
    },
  })
}

/** 获取模板详情 */
export function useTemplateDetail(templateId: string | null) {
  return useQuery({
    queryKey: ['template', templateId],
    queryFn: async () => {
      if (!templateId) return null
      const res = await templatesApi.get(templateId)
      return res.data
    },
    enabled: !!templateId,
  })
}

/** 应用模板创建项目 */
export function useApplyTemplate() {
  return useMutation({
    mutationFn: (payload: ApplyTemplateRequest) => templatesApi.apply(payload),
    onSuccess: (res) => {
      toast.success(res.data.summary || '项目创建成功')
    },
    onError: (err: unknown) => {
      const message =
        err && typeof err === 'object' && 'message' in err
          ? (err as { message: string }).message
          : '应用模板失败'
      toast.error(message)
    },
  })
}

import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { projectBundleApi } from '../api/projectBundles';
import type { ProjectBundleSelection } from '../types';

export function usePreviewProjectBundle() {
  return useMutation({
    mutationFn: ({ projectId, selection }: { projectId: string; selection: ProjectBundleSelection }) =>
      projectBundleApi.preview(projectId, selection),
  });
}

export function useExportProjectBundle() {
  return useMutation({
    mutationFn: ({ projectId, selection, filename }: { projectId: string; selection: ProjectBundleSelection; filename: string }) =>
      projectBundleApi.download(projectId, selection, filename),
    onSuccess: () => {
      toast.success('资产包已开始下载');
    },
    onError: () => {
      toast.error('导出资产包失败');
    },
  });
}

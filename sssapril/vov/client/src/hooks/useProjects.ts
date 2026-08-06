/**
 * 项目相关API Hook
 *
 * 提供项目CRUD操作的React Hook封装，
 * 内部使用TanStack Query管理缓存和请求状态。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { projectApi } from '../api';
import { CreateProjectRequest, UpdateProjectRequest, ProjectFilters } from '../types';

/** Query key工厂 */
export const projectKeys = {
  all: ['projects'] as const,
  lists: () => [...projectKeys.all, 'list'] as const,
  list: (filters?: ProjectFilters) => [...projectKeys.lists(), filters] as const,
  details: () => [...projectKeys.all, 'detail'] as const,
  detail: (id: string) => [...projectKeys.details(), id] as const,
};

/**
 * 获取项目列表
 *
 * @param filters - 可选的筛选条件
 * @returns 项目列表及加载状态
 */
export function useProjects(filters?: ProjectFilters) {
  return useQuery({
    queryKey: projectKeys.list(filters),
    queryFn: async () => {
      const res = await projectApi.list(filters);
      return res.data;
    },
  });
}

/**
 * 获取项目详情
 *
 * @param id - 项目ID
 * @returns 项目详情及加载状态
 */
export function useProject(id: string) {
  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn: async () => {
      const res = await projectApi.get(id);
      return res.data;
    },
    enabled: !!id,
  });
}

/**
 * 创建项目
 *
 * @returns 创建项目的mutation
 */
export function useCreateProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateProjectRequest) => {
      const res = await projectApi.create(data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

/**
 * 更新项目
 *
 * @returns 更新项目的mutation
 */
export function useUpdateProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateProjectRequest }) => {
      const res = await projectApi.update(id, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(variables.id) });
    },
  });
}

/**
 * 删除项目
 *
 * @returns 删除项目的mutation
 */
export function useDeleteProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      await projectApi.delete(id);
      return id;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

/**
 * 导出项目
 *
 * @returns 导出项目的mutation
 */
export function useExportProject() {
  return useMutation({
    mutationFn: async (id: string) => {
      await projectApi.export(id);
    },
  });
}

/**
 * 导入项目
 *
 * @returns 导入项目的mutation
 */
export function useImportProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (file: File) => {
      const res = await projectApi.import(file);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

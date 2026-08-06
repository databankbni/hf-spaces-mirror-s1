/**
 * 资源相关API Hook
 *
 * 提供资源CRUD操作的React Hook封装。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { resourceApi, tagApi } from '../api';
import { CreateResourceRequest, UpdateResourceRequest, CreateTagRequest, UpdateTagRequest } from '../types';

/** Query key工厂 */
export const resourceKeys = {
  all: ['resources'] as const,
  lists: () => [...resourceKeys.all, 'list'] as const,
  listByProject: (projectId: string) => [...resourceKeys.lists(), 'project', projectId] as const,
  listByGroup: (groupId: string) => [...resourceKeys.lists(), 'group', groupId] as const,
  details: () => [...resourceKeys.all, 'detail'] as const,
  detail: (id: string) => [...resourceKeys.details(), id] as const,
};

export const tagKeys = {
  all: ['tags'] as const,
  listByProject: (projectId: string) => [...tagKeys.all, 'project', projectId] as const,
};

/**
 * 获取项目的全局资源列表
 *
 * @param projectId - 项目ID
 * @returns 资源列表及加载状态
 */
export function useProjectResources(projectId: string) {
  return useQuery({
    queryKey: resourceKeys.listByProject(projectId),
    queryFn: async () => {
      const res = await resourceApi.listByProject(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });
}

/**
 * 获取群聊的资源列表
 *
 * @param groupId - 群聊ID
 * @returns 资源列表及加载状态
 */
export function useGroupResources(groupId: string) {
  return useQuery({
    queryKey: resourceKeys.listByGroup(groupId),
    queryFn: async () => {
      const res = await resourceApi.listByGroup(groupId);
      return res.data;
    },
    enabled: !!groupId,
  });
}

/**
 * 创建资源
 *
 * @returns 创建资源的mutation
 */
export function useCreateResource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateResourceRequest) => {
      const res = await resourceApi.create(data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      if (variables.group_id) {
        queryClient.invalidateQueries({ queryKey: resourceKeys.listByGroup(variables.group_id) });
      } else {
        queryClient.invalidateQueries({ queryKey: resourceKeys.listByProject(variables.project_id) });
      }
    },
  });
}

/**
 * 更新资源
 *
 * @returns 更新资源的mutation
 */
export function useUpdateResource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateResourceRequest }) => {
      const res = await resourceApi.update(id, data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.lists() });
    },
  });
}

/**
 * 删除资源
 *
 * @returns 删除资源的mutation
 */
export function useDeleteResource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      await resourceApi.delete(id);
      return id;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.lists() });
    },
  });
}

/**
 * 获取项目的标签列表
 *
 * @param projectId - 项目ID
 * @returns 标签列表及加载状态
 */
export function useTags(projectId: string) {
  return useQuery({
    queryKey: tagKeys.listByProject(projectId),
    queryFn: async () => {
      const res = await tagApi.list(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });
}

/**
 * 创建标签
 *
 * @returns 创建标签的mutation
 */
export function useCreateTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ projectId, data }: { projectId: string; data: CreateTagRequest }) => {
      const res = await tagApi.create(projectId, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: tagKeys.listByProject(variables.projectId) });
    },
  });
}

/**
 * 更新标签
 *
 * @returns 更新标签的mutation
 */
export function useUpdateTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateTagRequest }) => {
      const res = await tagApi.update(id, data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tagKeys.all });
    },
  });
}

/**
 * 删除标签
 *
 * @returns 删除标签的mutation
 */
export function useDeleteTag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      await tagApi.delete(id);
      return id;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tagKeys.all });
    },
  });
}

/**
 * 交付物相关API Hook
 *
 * 提供交付物CRUD操作的React Hook封装。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { deliverableApi } from '../api';
import { CreateDeliverableRequest, UpdateDeliverableRequest } from '../types';

/** Query key工厂 */
export const deliverableKeys = {
  all: ['deliverables'] as const,
  lists: () => [...deliverableKeys.all, 'list'] as const,
  listByGroup: (groupId: string) => [...deliverableKeys.lists(), 'group', groupId] as const,
  listByProject: (projectId: string) => [...deliverableKeys.lists(), 'project', projectId] as const,
  details: () => [...deliverableKeys.all, 'detail'] as const,
  detail: (id: string) => [...deliverableKeys.details(), id] as const,
  versions: (id: string) => [...deliverableKeys.detail(id), 'versions'] as const,
  diff: (id: string, v1: number, v2: number) => [...deliverableKeys.detail(id), 'diff', v1, v2] as const,
};

/**
 * 获取群聊的交付物列表
 *
 * @param groupId - 群聊ID
 * @returns 交付物列表及加载状态
 */
export function useDeliverablesByGroup(groupId: string) {
  return useQuery({
    queryKey: deliverableKeys.listByGroup(groupId),
    queryFn: async () => {
      const res = await deliverableApi.listByGroup(groupId);
      return res.data;
    },
    enabled: !!groupId,
  });
}

/**
 * 获取项目的交付物列表
 *
 * @param projectId - 项目ID
 * @returns 交付物列表及加载状态
 */
export function useDeliverablesByProject(projectId: string) {
  return useQuery({
    queryKey: deliverableKeys.listByProject(projectId),
    queryFn: async () => {
      const res = await deliverableApi.listByProject(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });
}

/**
 * 获取交付物详情
 *
 * @param deliverableId - 交付物ID
 * @returns 交付物详情及加载状态
 */
export function useDeliverable(deliverableId: string) {
  return useQuery({
    queryKey: deliverableKeys.detail(deliverableId),
    queryFn: async () => {
      const res = await deliverableApi.get(deliverableId);
      return res.data;
    },
    enabled: !!deliverableId,
  });
}

/**
 * 创建交付物
 *
 * @returns 创建交付物的mutation
 */
export function useCreateDeliverable() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateDeliverableRequest) => {
      const res = await deliverableApi.create(data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: deliverableKeys.listByGroup(variables.group_id) });
    },
  });
}

/**
 * 更新交付物
 *
 * @returns 更新交付物的mutation
 */
export function useUpdateDeliverable() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateDeliverableRequest }) => {
      const res = await deliverableApi.update(id, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: deliverableKeys.detail(variables.id) });
    },
  });
}

/**
 * 获取交付物的版本列表
 *
 * @param deliverableId - 交付物ID
 * @returns 版本列表及加载状态
 */
export function useDeliverableVersions(deliverableId: string) {
  return useQuery({
    queryKey: deliverableKeys.versions(deliverableId),
    queryFn: async () => {
      const res = await deliverableApi.listVersions(deliverableId);
      return res.data;
    },
    enabled: !!deliverableId,
  });
}

/**
 * 获取版本差异
 *
 * @param deliverableId - 交付物ID
 * @param versionA - 版本A
 * @param versionB - 版本B
 * @returns 差异信息及加载状态
 */
export function useDeliverableDiff(deliverableId: string, versionA: number, versionB: number) {
  return useQuery({
    queryKey: deliverableKeys.diff(deliverableId, versionA, versionB),
    queryFn: async () => {
      const res = await deliverableApi.diff(deliverableId, versionA, versionB);
      return res.data;
    },
    enabled: !!deliverableId && versionA > 0 && versionB > 0,
  });
}

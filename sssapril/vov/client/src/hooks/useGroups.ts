/**
 * 群聊相关API Hook
 *
 * 提供群聊CRUD操作的React Hook封装。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { groupApi } from '../api';
import { CreateGroupRequest, UpdateGroupRequest } from '../types';

/** Query key工厂 */
export const groupKeys = {
  all: ['groups'] as const,
  lists: () => [...groupKeys.all, 'list'] as const,
  listByProject: (projectId: string) => [...groupKeys.lists(), 'project', projectId] as const,
  details: () => [...groupKeys.all, 'detail'] as const,
  detail: (id: string) => [...groupKeys.details(), id] as const,
  members: (groupId: string) => [...groupKeys.detail(groupId), 'members'] as const,
};

/**
 * 获取项目的群聊列表
 *
 * @param projectId - 项目ID
 * @returns 群聊列表及加载状态
 */
export function useGroups(projectId: string) {
  return useQuery({
    queryKey: groupKeys.listByProject(projectId),
    queryFn: async () => {
      const res = await groupApi.list(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });
}

/**
 * 获取群聊详情
 *
 * @param groupId - 群聊ID
 * @returns 群聊详情及加载状态
 */
export function useGroup(groupId: string) {
  return useQuery({
    queryKey: groupKeys.detail(groupId),
    queryFn: async () => {
      const res = await groupApi.get(groupId);
      return res.data;
    },
    enabled: !!groupId,
  });
}

/**
 * 获取群聊成员列表
 *
 * @param groupId - 群聊ID
 * @returns 成员列表及加载状态
 */
export function useGroupMembers(groupId: string) {
  return useQuery({
    queryKey: groupKeys.members(groupId),
    queryFn: async () => {
      const res = await groupApi.listMembers(groupId);
      return res.data;
    },
    enabled: !!groupId,
  });
}

/**
 * 创建群聊
 *
 * @returns 创建群聊的mutation
 */
export function useCreateGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ projectId, data }: { projectId: string; data: CreateGroupRequest }) => {
      const res = await groupApi.create(projectId, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.listByProject(variables.projectId) });
    },
  });
}

/**
 * 更新群聊
 *
 * @returns 更新群聊的mutation
 */
export function useUpdateGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateGroupRequest }) => {
      const res = await groupApi.update(id, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.detail(variables.id) });
    },
  });
}

/**
 * 删除群聊
 *
 * @returns 删除群聊的mutation
 */
export function useDeleteGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ groupId, projectId }: { groupId: string; projectId: string }) => {
      await groupApi.delete(groupId);
      return groupId;
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.listByProject(variables.projectId) });
    },
  });
}

/**
 * 重新排序群聊
 *
 * @returns 重新排序的mutation
 */
export function useReorderGroups() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ projectId, orderedIds }: { projectId: string; orderedIds: string[] }) => {
      await groupApi.reorder(projectId, { ordered_ids: orderedIds });
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.listByProject(variables.projectId) });
    },
  });
}

/**
 * 添加群聊成员
 *
 * @returns 添加成员的mutation
 */
export function useAddGroupMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ groupId, projectAgentId, role }: { groupId: string; projectAgentId: string; role?: 'lead' | 'participant' }) => {
      const res = await groupApi.addMember(groupId, { project_agent_id: projectAgentId, role: role || 'participant' });
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.members(variables.groupId) });
      queryClient.invalidateQueries({ queryKey: groupKeys.detail(variables.groupId) });
    },
  });
}

/**
 * 移除群聊成员
 *
 * @returns 移除成员的mutation
 */
export function useRemoveGroupMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ groupId, agentId }: { groupId: string; agentId: string }) => {
      return await groupApi.removeMember(groupId, agentId);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.members(variables.groupId) });
      queryClient.invalidateQueries({ queryKey: groupKeys.detail(variables.groupId) });
    },
  });
}

export function useUpdateMemberRole() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ groupId, agentId, role }: { groupId: string; agentId: string; role: string }) => {
      const res = await groupApi.updateMemberRole(groupId, agentId, role);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.detail(variables.groupId) });
    },
  });
}

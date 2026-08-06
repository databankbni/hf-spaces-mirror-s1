/**
 * Agent相关API Hook
 *
 * 提供Agent CRUD操作的React Hook封装。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { agentApi, projectAgentApi, memoryApi } from '../api';
import { CreateAgentRequest, UpdateAgentRequest, AgentFilters } from '../types';

/** Query key工厂 */
export const agentKeys = {
  all: ['agents'] as const,
  lists: () => [...agentKeys.all, 'list'] as const,
  list: (filters?: AgentFilters) => [...agentKeys.lists(), filters] as const,
  details: () => [...agentKeys.all, 'detail'] as const,
  detail: (id: string) => [...agentKeys.details(), id] as const,
};

export const projectAgentKeys = {
  all: ['projectAgents'] as const,
  listByProject: (projectId: string) => [...projectAgentKeys.all, 'project', projectId] as const,
};

export const memoryKeys = {
  all: ['memories'] as const,
  byAgentAndProject: (agentId: string, projectId: string) =>
    [...memoryKeys.all, agentId, projectId] as const,
  listByProject: (projectId: string) => [...memoryKeys.all, 'project', projectId] as const,
};

/**
 * 获取Agent列表
 *
 * @param filters - 可选的筛选条件
 * @returns Agent列表及加载状态
 */
export function useAgents(filters?: AgentFilters) {
  return useQuery({
    queryKey: agentKeys.list(filters),
    queryFn: async () => {
      const res = await agentApi.list(filters);
      return res.data;
    },
  });
}

/**
 * 获取Agent详情
 *
 * @param agentId - Agent ID
 * @returns Agent详情及加载状态
 */
export function useAgent(agentId: string) {
  return useQuery({
    queryKey: agentKeys.detail(agentId),
    queryFn: async () => {
      const res = await agentApi.get(agentId);
      return res.data;
    },
    enabled: !!agentId,
  });
}

/**
 * 创建Agent
 *
 * @returns 创建Agent的mutation
 */
export function useCreateAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateAgentRequest) => {
      const res = await agentApi.create(data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() });
    },
  });
}

/**
 * 更新Agent
 *
 * @returns 更新Agent的mutation
 */
export function useUpdateAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateAgentRequest }) => {
      const res = await agentApi.update(id, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: agentKeys.detail(variables.id) });
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() });
    },
  });
}

/**
 * 删除Agent
 *
 * @returns 删除Agent的mutation
 */
export function useDeleteAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      await agentApi.delete(id);
      return id;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() });
    },
  });
}

/**
 * 获取项目的Agent列表
 *
 * @param projectId - 项目ID
 * @returns 项目Agent列表及加载状态
 */
export function useProjectAgents(projectId: string) {
  return useQuery({
    queryKey: projectAgentKeys.listByProject(projectId),
    queryFn: async () => {
      const res = await projectAgentApi.list(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });
}

/**
 * 添加Agent到项目
 *
 * @returns 添加Agent的mutation
 */
export function useAddAgentToProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ projectId, agentId, overrideConfig }: {
      projectId: string;
      agentId: string;
      overrideConfig?: Record<string, unknown>;
    }) => {
      const res = await projectAgentApi.add(projectId, agentId, overrideConfig);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: projectAgentKeys.listByProject(variables.projectId) });
    },
  });
}

/**
 * 从项目移除Agent
 *
 * @returns 移除Agent的mutation
 */
export function useRemoveAgentFromProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ projectId, agentId }: { projectId: string; agentId: string }) => {
      await projectAgentApi.remove(projectId, agentId);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: projectAgentKeys.listByProject(variables.projectId) });
    },
  });
}

/**
 * 获取Agent在项目中的笔记
 *
 * @param agentId - Agent ID
 * @param projectId - 项目ID
 * @returns 笔记及加载状态
 */
export function useAgentMemory(agentId: string, projectId: string) {
  return useQuery({
    queryKey: memoryKeys.byAgentAndProject(agentId, projectId),
    queryFn: async () => {
      const res = await memoryApi.get(agentId, projectId);
      return res.data;
    },
    enabled: !!agentId && !!projectId,
  });
}

/**
 * 获取项目的所有Agent笔记
 *
 * @param projectId - 项目ID
 * @returns 笔记列表及加载状态
 */
export function useProjectMemories(projectId: string) {
  return useQuery({
    queryKey: memoryKeys.listByProject(projectId),
    queryFn: async () => {
      const res = await memoryApi.listByProject(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });
}

/**
 * 更新Agent笔记
 *
 * @returns 更新笔记的mutation
 */
export function useUpdateAgentMemory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ agentId, projectId, content, tags }: {
      agentId: string;
      projectId: string;
      content: string;
      tags?: string[];
    }) => {
      const res = await memoryApi.update(agentId, projectId, content, tags);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: memoryKeys.byAgentAndProject(variables.agentId, variables.projectId)
      });
      queryClient.invalidateQueries({
        queryKey: memoryKeys.listByProject(variables.projectId)
      });
    },
  });
}

/**
 * 任务相关API Hook
 *
 * 提供任务CRUD操作的React Hook封装。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { taskApi, chainApi } from '../api';
import { CreateTaskRequest, UpdateTaskRequest, TaskStatus, SendMessageRequest } from '../types';
import { groupKeys } from './useGroups';

/** Query key工厂 */
export const taskKeys = {
  all: ['tasks'] as const,
  lists: () => [...taskKeys.all, 'list'] as const,
  listByGroup: (groupId: string) => [...taskKeys.lists(), 'group', groupId] as const,
  details: () => [...taskKeys.all, 'detail'] as const,
  detail: (id: string) => [...taskKeys.details(), id] as const,
};

/** Query key工厂 for chains */
export const chainKeys = {
  all: ['chains'] as const,
  byTask: (taskId: string) => [...chainKeys.all, 'task', taskId] as const,
  messages: (chainId: string) => [...chainKeys.all, chainId, 'messages'] as const,
};

/**
 * 创建任务
 *
 * @returns 创建任务的mutation
 */
export function useCreateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ groupId, data }: { groupId: string; data: CreateTaskRequest }) => {
      const res = await taskApi.create(groupId, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      // 任务列表内嵌在 group detail 里 (group.tasks), 必须失效 group detail 才能让侧边栏更新
      queryClient.invalidateQueries({ queryKey: groupKeys.detail(variables.groupId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    },
  });
}

/**
 * 更新任务
 *
 * @returns 更新任务的mutation
 */
export function useUpdateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateTaskRequest }) => {
      const res = await taskApi.update(id, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(variables.id) });
      // 任务列表内嵌在 group detail 里, 失效所有 group detail (无 groupId 信息, 兜底全刷)
      queryClient.invalidateQueries({ queryKey: groupKeys.details() });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    },
  });
}

/**
 * 更新任务状态
 *
 * @returns 更新任务状态的mutation
 */
export function useUpdateTaskStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, status }: { id: string; status: TaskStatus }) => {
      const res = await taskApi.updateStatus(id, { status });
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(variables.id) });
      // 任务状态变更 (如 in_progress→done) 会改变 task chain 状态, 侧边栏任务列表也需更新
      queryClient.invalidateQueries({ queryKey: groupKeys.details() });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    },
  });
}

/**
 * 删除任务
 *
 * @returns 删除任务的mutation
 */
export function useDeleteTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ taskId, groupId }: { taskId: string; groupId: string }) => {
      await taskApi.delete(taskId);
      return taskId;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: groupKeys.detail(variables.groupId) });
    },
  });
}

/**
 * 获取讨论链的消息列表
 *
 * @param chainId - 讨论链ID
 * @returns 消息列表及加载状态
 */
export function useChainMessages(chainId: string) {
  return useQuery({
    queryKey: chainKeys.messages(chainId),
    queryFn: async () => {
      const res = await chainApi.listMessages(chainId);
      return res.data;
    },
    enabled: !!chainId,
  });
}

/**
 * 发送消息
 *
 * @returns 发送消息的mutation
 */
export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ chainId, data }: { chainId: string; data: SendMessageRequest }) => {
      const res = await chainApi.sendMessage(chainId, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: chainKeys.messages(variables.chainId) });
    },
  });
}

/**
 * 停止Agent
 *
 * @returns 停止Agent的mutation
 */
export function useStopAgent() {
  return useMutation({
    mutationFn: async ({ chainId, mode }: { chainId: string; mode: 'wait_complete' | 'wait_task' | 'force' }) => {
      await chainApi.stopAgent(chainId, { mode });
    },
  });
}

/**
 * 恢复讨论
 *
 * @returns 恢复讨论的mutation
 */
export function useResumeChain() {
  return useMutation({
    mutationFn: async (chainId: string) => {
      await chainApi.resume(chainId);
    },
  });
}

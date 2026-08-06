/**
 * 技能相关 API Hook
 *
 * 提供独立技能 CRUD 操作的 React Hook 封装。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { skillApi, type CreateSkillRequest, type UpdateSkillRequest } from '../api/skills';

export const skillKeys = {
  all: ['skills'] as const,
  lists: () => [...skillKeys.all, 'list'] as const,
  list: () => [...skillKeys.lists()] as const,
  details: () => [...skillKeys.all, 'detail'] as const,
  detail: (id: string) => [...skillKeys.details(), id] as const,
};

/** 获取所有技能 */
export function useSkills() {
  return useQuery({
    queryKey: skillKeys.list(),
    queryFn: async () => {
      const res = await skillApi.list();
      return res.data;
    },
  });
}

/** 获取技能详情 */
export function useSkill(id: string) {
  return useQuery({
    queryKey: skillKeys.detail(id),
    queryFn: async () => {
      const res = await skillApi.get(id);
      return res.data;
    },
    enabled: !!id,
  });
}

/** 创建技能 */
export function useCreateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: CreateSkillRequest) => {
      const res = await skillApi.create(data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillKeys.lists() });
    },
  });
}

/** 更新技能 */
export function useUpdateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateSkillRequest }) => {
      const res = await skillApi.update(id, data);
      return res.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: skillKeys.detail(variables.id) });
      queryClient.invalidateQueries({ queryKey: skillKeys.lists() });
    },
  });
}

/** 删除技能 */
export function useDeleteSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await skillApi.delete(id);
      return id;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillKeys.lists() });
    },
  });
}

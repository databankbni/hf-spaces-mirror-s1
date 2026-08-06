/**
 * 应用操作工具函数
 *
 * 提供组件需要的操作函数，封装API调用。
 * 这些函数用于替代旧的mock数据函数。
 */

import { projectApi, groupApi, taskApi, resourceApi } from '../api';
import { useAppStore } from '../store/appStore';

/**
 * 创建项目
 */
export async function createProject(
  name: string,
  description: string,
  tags: string[],
  coverColor: string
) {
  const res = await projectApi.create({
    name,
    description,
    tags,
    cover_color: coverColor,
  });
  return res.data;
}

/**
 * 创建群聊
 */
export async function createGroup(
  projectId: string,
  name: string,
  description: string,
  agentIds: string[]
) {
  const res = await groupApi.create(projectId, {
    name,
    description,
    member_agent_ids: agentIds,
  });
  return res.data;
}

/**
 * 添加Agent到群聊
 */
export async function addAgentToGroup(
  projectId: string,
  groupId: string,
  agentId: string
) {
  const res = await groupApi.addMember(groupId, {
    project_agent_id: agentId,
  });
  return res.data;
}

/**
 * 创建任务
 */
export async function createTask(
  projectId: string,
  groupId: string,
  title: string,
  description: string,
  assigneeIds: string[]
) {
  const res = await taskApi.create(groupId, {
    title,
    description,
    assignee_ids: assigneeIds,
  });
  return res.data;
}

/**
 * 更新任务状态
 */
export async function updateTaskStatus(
  projectId: string,
  groupId: string,
  taskId: string,
  status: string
) {
  const res = await taskApi.updateStatus(taskId, { status: status as 'todo' | 'in_progress' | 'done' | 'reopened' });
  return res.data;
}

/**
 * 添加资源到项目
 */
export async function addResourceToProject(
  projectId: string,
  title: string,
  content: string,
  type: string
) {
  const res = await resourceApi.create({
    project_id: projectId,
    title,
    content,
    type: type as 'note' | 'reference' | 'guideline' | 'rule' | 'custom',
  });
  return res.data;
}

/**
 * 发送消息并获取Agent响应
 */
export async function sendMessage(
  projectId: string,
  groupId: string,
  content: string
) {
  const res = await groupApi.chat(groupId, content);
  return res.data;
}

/**
 * 设置当前活跃的群聊ID
 */
export function setActiveGroupId(groupId: string | null) {
  useAppStore.getState().setActiveGroupId(groupId);
}

/**
 * 设置当前活跃的交付物ID
 */
export function setActiveDeliverableId(deliverableId: string | null) {
  useAppStore.getState().setActiveDeliverableId(deliverableId);
}

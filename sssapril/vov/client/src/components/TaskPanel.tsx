import { useState } from 'react';
import { PlusIcon, CheckCircleIcon, CircleIcon, ClockIcon, FileTextIcon, ChevronDownIcon, PencilIcon, TrashIcon, XIcon, UserIcon, UsersIcon, Link2Icon, Link2OffIcon, MessageSquareIcon, InfoIcon } from 'lucide-react';
import { TaskListItem, TaskStatus, Deliverable } from '../types';
import { useCreateTask, useUpdateTask, useUpdateTaskStatus, useDeleteTask } from '../hooks/useTasks';
import { useNavigate } from 'react-router-dom';
import ConfirmDialog from './ConfirmDialog';
import TaskDetailDialog from './TaskDetailDialog';

interface TaskPanelProps {
  tasks?: TaskListItem[];
  deliverables?: Deliverable[];
  projectId?: string;
  groupId?: string;
  memberIds?: string[];
  members?: { id: string; name: string; avatar?: string }[];
  onTaskClick?: (taskId: string) => void;
  /** 任务变更后回调 (创建/更新/状态变更/删除), 用于刷新主链视图让 task chain 内联块即时更新 */
  onTaskMutated?: () => void;
}

const statusConfig = {
  todo: { icon: CircleIcon, label: '待完成', color: 'text-foreground/40' },
  in_progress: { icon: ClockIcon, label: '进行中', color: 'text-foreground/60' },
  done: { icon: CheckCircleIcon, label: '已完成', color: 'text-foreground/60' },
  reopened: { icon: ClockIcon, label: '重新打开', color: 'text-foreground/60' },
};

export default function TaskPanel({
  tasks = [],
  deliverables = [],
  projectId = '',
  groupId = '',
  memberIds = [],
  members = [],
  onTaskClick,
  onTaskMutated,
}: TaskPanelProps) {
  const navigate = useNavigate();
  const [showForm, setShowForm] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newCriteria, setNewCriteria] = useState('');
  const [newAssignees, setNewAssignees] = useState<string[]>([]);
  const [newInheritMainChain, setNewInheritMainChain] = useState(true);
  const [openStatusMenu, setOpenStatusMenu] = useState<string | null>(null);
  const [editingTask, setEditingTask] = useState<TaskListItem | null>(null);
  const [deletingTask, setDeletingTask] = useState<TaskListItem | null>(null);
  const [detailTask, setDetailTask] = useState<TaskListItem | null>(null);

  const createTaskMutation = useCreateTask();
  const updateTaskMutation = useUpdateTask();
  const updateTaskStatusMutation = useUpdateTaskStatus();
  const deleteTaskMutation = useDeleteTask();

  const handleCreate = async () => {
    if (!newTitle.trim() || !groupId) return;
    try {
      await createTaskMutation.mutateAsync({
        groupId,
        data: {
          title: newTitle.trim(),
          description: newDesc.trim() || undefined,
          acceptance_criteria: newCriteria.trim() || undefined,
          assignee_ids: newAssignees.length > 0 ? newAssignees : undefined,
          inherit_main_chain: newInheritMainChain,
        },
      });
      setNewTitle('');
      setNewDesc('');
      setNewCriteria('');
      setNewAssignees([]);
      setNewInheritMainChain(true);
      setShowForm(false);
      onTaskMutated?.();
    } catch (error) {
      console.error('Failed to create task:', error);
    }
  };

  const handleUpdate = async () => {
    if (!editingTask || !editingTask.title.trim()) return;
    try {
      await updateTaskMutation.mutateAsync({
        id: editingTask.id,
        data: {
          title: editingTask.title.trim(),
          description: editingTask.description?.trim() || undefined,
          acceptance_criteria: editingTask.acceptance_criteria?.trim() || undefined,
          inherit_main_chain: editingTask.inherit_main_chain,
        },
      });
      setEditingTask(null);
      onTaskMutated?.();
    } catch (error) {
      console.error('Failed to update task:', error);
    }
  };

  const handleDelete = async () => {
    if (!deletingTask || !groupId) return;
    await deleteTaskMutation.mutateAsync({ taskId: deletingTask.id, groupId });
    onTaskMutated?.();
  };

  const handleStatusChange = async (taskId: string, status: TaskStatus) => {
    try {
      await updateTaskStatusMutation.mutateAsync({ id: taskId, status });
      setOpenStatusMenu(null);
      onTaskMutated?.();
    } catch (error) {
      console.error('Failed to update task status:', error);
    }
  };

  const handleViewDeliverable = (delivId: string) => {
    navigate(`/workbench?projectId=${projectId}&resourceId=${delivId}&mode=view`);
  };

  const toggleAssignee = (agentId: string) => {
    setNewAssignees(prev =>
      prev.includes(agentId) ? prev.filter(id => id !== agentId) : [...prev, agentId]
    );
  };

  const isLoading = createTaskMutation.isPending || updateTaskMutation.isPending;

  return (
    <div data-cmp="TaskPanel" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-newspaper-bold text-foreground">任务列表</span>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1 text-xs font-newspaper text-foreground/60 hover:text-foreground/80 underline-offset-2 hover:underline transition-all"
        >
          <PlusIcon className="w-3.5 h-3.5" />
          新建任务
        </button>
      </div>

      {/* Create form */}
      <div className={`overflow-hidden transition-all duration-200 ${showForm ? 'max-h-96' : 'max-h-0'}`}>
        <div className="border border-foreground/15 p-3 flex flex-col gap-2">
          <input
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            placeholder="任务标题 *"
            className="w-full px-2.5 py-1.5 border border-foreground/15 bg-transparent font-newspaper text-xs text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/30"
          />
          <textarea
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            placeholder="任务描述（可选）"
            rows={2}
            className="w-full px-2.5 py-1.5 border border-foreground/15 bg-transparent font-newspaper text-xs text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/30 resize-none"
          />
          <textarea
            value={newCriteria}
            onChange={e => setNewCriteria(e.target.value)}
            placeholder="验收标准（可选）"
            rows={2}
            className="w-full px-2.5 py-1.5 border border-foreground/15 bg-transparent font-newspaper text-xs text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/30 resize-none"
          />
          {/* 上下文隔离 */}
          <div>
            <div className="text-xs font-newspaper text-foreground/60 mb-1.5">上下文</div>
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={() => setNewInheritMainChain(true)}
                className={`flex items-center gap-1 px-2 py-1 text-xs font-newspaper transition-all ${
                  newInheritMainChain
                    ? 'border border-foreground/40 text-foreground/80 underline'
                    : 'border border-foreground/15 text-foreground/50 hover:border-foreground/30'
                }`}
              >
                <Link2Icon className="w-3 h-3" />
                接入主链
              </button>
              <button
                type="button"
                onClick={() => setNewInheritMainChain(false)}
                className={`flex items-center gap-1 px-2 py-1 text-xs font-newspaper transition-all ${
                  !newInheritMainChain
                    ? 'border border-amber-500/40 bg-amber-500/5 text-amber-700/80 underline'
                    : 'border border-foreground/15 text-foreground/50 hover:border-foreground/30'
                }`}
              >
                <Link2OffIcon className="w-3 h-3" />
                隔离上下文
              </button>
            </div>
          </div>
          {/* Assignee selection */}
          {members.length > 0 && (
            <div>
              <div className="text-xs font-newspaper text-foreground/60 mb-1.5">负责人</div>
              <div className="flex flex-wrap gap-1.5">
                {members.map(member => (
                  <button
                    key={member.id}
                    onClick={() => toggleAssignee(member.id)}
                    className={`flex items-center gap-1 px-2 py-1 text-xs font-newspaper transition-all ${
                      newAssignees.includes(member.id)
                        ? 'border border-foreground/40 text-foreground/80 underline'
                        : 'border border-foreground/15 text-foreground/50 hover:border-foreground/30'
                    }`}
                  >
                    <UserIcon className="w-3 h-3" />
                    {member.name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="text-xs font-newspaper text-foreground/50 hover:text-foreground/70 px-2 py-1 underline-offset-2 hover:underline">取消</button>
            <button onClick={handleCreate} disabled={!newTitle.trim() || isLoading} className="text-xs font-newspaper text-foreground/70 hover:text-foreground/90 px-3 py-1 underline-offset-2 hover:underline disabled:opacity-40">
              {isLoading ? '创建中...' : '创建'}
            </button>
          </div>
        </div>
      </div>

      {tasks.length === 0 && !showForm && (
        <div className="text-xs font-newspaper text-foreground/40 py-3 text-center">暂无任务</div>
      )}

      {tasks.map(task => {
        const cfg = statusConfig[task.status];
        const deliverable = task.deliverable;
        const isEditing = editingTask?.id === task.id;
        const lead = task.lead_agent;
        const assignees = task.assignees || [];
        const extraAssignees = Math.max(0, assignees.length - 2);

        return (
          <div key={task.id} className="border border-foreground/15 p-3 flex flex-col gap-2 group">
            {isEditing ? (
              /* Edit mode */
              <div className="flex flex-col gap-2">
                <input
                  value={editingTask.title}
                  onChange={e => setEditingTask({ ...editingTask, title: e.target.value })}
                  className="w-full px-2 py-1 border border-foreground/15 bg-transparent font-newspaper text-xs text-foreground focus:outline-none focus:border-foreground/30"
                />
                <textarea
                  value={editingTask.description || ''}
                  onChange={e => setEditingTask({ ...editingTask, description: e.target.value })}
                  rows={2}
                  className="w-full px-2 py-1 border border-foreground/15 bg-transparent font-newspaper text-xs text-foreground focus:outline-none focus:border-foreground/30 resize-none"
                />
                <textarea
                  value={editingTask.acceptance_criteria || ''}
                  onChange={e => setEditingTask({ ...editingTask, acceptance_criteria: e.target.value })}
                  rows={2}
                  placeholder="验收标准"
                  className="w-full px-2 py-1 border border-foreground/15 bg-transparent font-newspaper text-xs text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/30 resize-none"
                />
                {/* 上下文隔离 */}
                <div>
                  <div className="text-xs font-newspaper text-foreground/60 mb-1.5">上下文</div>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => setEditingTask({ ...editingTask, inherit_main_chain: true })}
                      className={`flex items-center gap-1 px-2 py-1 text-xs font-newspaper transition-all ${
                        editingTask.inherit_main_chain
                          ? 'border border-foreground/40 text-foreground/80 underline'
                          : 'border border-foreground/15 text-foreground/50 hover:border-foreground/30'
                      }`}
                    >
                      <Link2Icon className="w-3 h-3" />
                      接入主链
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingTask({ ...editingTask, inherit_main_chain: false })}
                      className={`flex items-center gap-1 px-2 py-1 text-xs font-newspaper transition-all ${
                        !editingTask.inherit_main_chain
                          ? 'border border-amber-500/40 bg-amber-500/5 text-amber-700/80 underline'
                          : 'border border-foreground/15 text-foreground/50 hover:border-foreground/30'
                      }`}
                    >
                      <Link2OffIcon className="w-3 h-3" />
                      隔离上下文
                    </button>
                  </div>
                </div>
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setEditingTask(null)} className="text-xs font-newspaper text-foreground/50 hover:text-foreground/70 px-2 py-1 underline-offset-2 hover:underline">
                    <XIcon className="w-3 h-3 inline mr-1" />取消
                  </button>
                  <button onClick={handleUpdate} disabled={!editingTask.title.trim() || isLoading} className="text-xs font-newspaper text-foreground/70 hover:text-foreground/90 px-3 py-1 underline-offset-2 hover:underline disabled:opacity-40">
                    {isLoading ? '保存中...' : '保存'}
                  </button>
                </div>
              </div>
            ) : (
              /* View mode */
              <>
                <div className="flex items-start gap-2">
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => setOpenStatusMenu(openStatusMenu === task.id ? null : task.id)}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpenStatusMenu(openStatusMenu === task.id ? null : task.id); } }}
                    className={`mt-0.5 flex-shrink-0 ${cfg.color} hover:opacity-70 transition-opacity relative cursor-pointer`}
                  >
                    <cfg.icon className="w-4 h-4" />
                    <div className={`absolute top-5 left-0 z-10 bg-background border border-foreground/20 p-1 flex flex-col gap-0.5 w-28 transition-all duration-100 ${openStatusMenu === task.id ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}>
                      {(Object.entries(statusConfig) as Array<[TaskStatus, typeof statusConfig[TaskStatus]]>).map(([st, scfg]) => (
                        <button
                          key={st}
                          onClick={e => { e.stopPropagation(); handleStatusChange(task.id, st); }}
                          className={`flex items-center gap-1.5 px-2 py-1 text-xs font-newspaper hover:bg-foreground/5 transition-colors ${scfg.color}`}
                        >
                          <scfg.icon className="w-3 h-3" />
                          {scfg.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div
                    className="flex-1 min-w-0 cursor-pointer"
                    onClick={() => setDetailTask(task)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setDetailTask(task); } }}
                    title="点击查看任务详情"
                  >
                    <div className={`text-xs font-newspaper ${task.status === 'done' ? 'line-through text-foreground/40' : 'text-foreground/80'}`}>
                      {task.title}
                    </div>
                    {task.description && (
                      <div className="text-xs font-newspaper text-foreground/40 mt-0.5 leading-relaxed line-clamp-2">{task.description}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <span className="font-newspaper-bold opacity-70 text-[10px]">
                      {cfg.label}
                    </span>
                    {task.chain_id && onTaskClick && (
                      <button
                        onClick={() => onTaskClick(task.id)}
                        className="p-1 hover:bg-foreground/5 transition-colors"
                        title="在聊天区展开该任务链"
                      >
                        <MessageSquareIcon className="w-3 h-3 text-foreground/40" />
                      </button>
                    )}
                    <button
                      onClick={() => setDetailTask(task)}
                      className="p-1 hover:bg-foreground/5 transition-colors"
                      title="查看任务详情"
                    >
                      <InfoIcon className="w-3 h-3 text-foreground/40" />
                    </button>
                    <button
                      onClick={() => setEditingTask(task)}
                      className="p-1 hover:bg-foreground/5 transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <PencilIcon className="w-3 h-3 text-foreground/40" />
                    </button>
                    <button
                      onClick={() => setDeletingTask(task)}
                      className="p-1 hover:bg-foreground/5 transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <TrashIcon className="w-3 h-3 text-foreground/40 hover:text-foreground/60" />
                    </button>
                  </div>
                </div>

                {/* 负责人 + 接入主链标识 + 参与者摘要 */}
                <div className="flex items-center flex-wrap gap-x-2 gap-y-1 pl-6">
                  {/* 任务负责人 */}
                  {lead && (
                    <span
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 border border-foreground/20 text-[10px] font-newspaper text-foreground/70"
                      title="任务负责人"
                    >
                      <UserIcon className="w-2.5 h-2.5" />
                      <span className="text-sm leading-none">{lead.avatar || '👤'}</span>
                      <span className="truncate max-w-[6rem]">{lead.name}</span>
                    </span>
                  )}
                  {/* 是否继承主链历史 */}
                  <span
                    className={`inline-flex items-center gap-1 px-1.5 py-0.5 border text-[10px] font-newspaper ${
                      task.inherit_main_chain
                        ? 'border-foreground/15 text-foreground/60'
                        : 'border-amber-500/40 bg-amber-500/5 text-amber-700/80'
                    }`}
                    title={task.inherit_main_chain ? '任务链继承主链截至分支点的历史' : '任务链完全隔离，不读主链历史'}
                  >
                    {task.inherit_main_chain ? <Link2Icon className="w-2.5 h-2.5" /> : <Link2OffIcon className="w-2.5 h-2.5" />}
                    {task.inherit_main_chain ? '接入主链' : '隔离'}
                  </span>
                  {/* 参与者摘要（>=3 人时折叠） */}
                  {assignees.length > 0 && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-newspaper text-foreground/50" title={`参与者（${assignees.length}）: ${assignees.map(a => a.name).join(', ')}`}>
                      <UsersIcon className="w-2.5 h-2.5" />
                      {assignees.slice(0, 2).map(a => a.name).join(', ')}
                      {extraAssignees > 0 && ` +${extraAssignees}`}
                    </span>
                  )}
                </div>

                {deliverable && (
                  <button
                    onClick={() => handleViewDeliverable(deliverable.id)}
                    className="flex items-center gap-2 px-2.5 py-1.5 border border-foreground/15 hover:border-foreground/30 transition-all text-left group/deliv"
                  >
                    <FileTextIcon className="w-3.5 h-3.5 text-foreground/50 flex-shrink-0" />
                    <span className="text-xs font-newspaper text-foreground/60 group-hover/deliv:underline group-hover/deliv:underline-offset-2 truncate flex-1">
                      {deliverable.title}
                    </span>
                    <ChevronDownIcon className="w-3 h-3 text-foreground/40 flex-shrink-0 -rotate-90" />
                  </button>
                )}
              </>
            )}
          </div>
        );
      })}

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={!!deletingTask}
        onClose={() => setDeletingTask(null)}
        onConfirm={handleDelete}
        title="删除任务"
        description={`确定要删除任务「${deletingTask?.title}」吗？此操作不可撤销。`}
        confirmText="删除"
        destructive
      />

      {/* Task Detail Dialog */}
      <TaskDetailDialog
        task={detailTask}
        open={!!detailTask}
        onOpenChange={(open) => { if (!open) setDetailTask(null); }}
      />
    </div>
  );
}

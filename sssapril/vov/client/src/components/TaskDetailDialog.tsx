/**
 * 任务详情弹窗
 *
 * 点击任务卡片后弹出，集中展示任务元数据：
 * 状态、负责人、指派、验收标准、链状态、交付物、
 * 是否继承主链历史、关键时间戳。
 */
import { CircleIcon, CheckCircleIcon, ClockIcon, Link2Icon, Link2OffIcon, UserIcon, UsersIcon, FileTextIcon, MessageSquareIcon, CalendarIcon } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';
import type { TaskListItem, TaskStatus, ChainStatus } from '../types';

interface TaskDetailDialogProps {
  task: TaskListItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const statusConfig: Record<TaskStatus, { icon: typeof CircleIcon; label: string }> = {
  todo: { icon: CircleIcon, label: '待完成' },
  in_progress: { icon: ClockIcon, label: '进行中' },
  done: { icon: CheckCircleIcon, label: '已完成' },
  reopened: { icon: ClockIcon, label: '重新打开' },
};

const chainStatusLabels: Record<ChainStatus, string> = {
  pending: '待开始',
  active: '进行中',
  paused: '已挂起',
  completed: '已完成',
  archived: '已归档',
  failed: '异常',
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function TaskDetailDialog({ task, open, onOpenChange }: TaskDetailDialogProps) {
  if (!task) return null;
  const cfg = statusConfig[task.status];
  const StatusIcon = cfg.icon;
  const lead = task.lead_agent;
  const assignees = task.assignees || [];
  const chain = task.chain;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2 text-xs font-newspaper text-foreground/60">
            <StatusIcon className="w-3.5 h-3.5" />
            <span>{cfg.label}</span>
            {chain && (
              <>
                <span className="text-foreground/30">·</span>
                <MessageSquareIcon className="w-3.5 h-3.5" />
                <span>链 {chainStatusLabels[chain.status] || chain.status} · {chain.packet_count} 包</span>
              </>
            )}
          </div>
          <DialogTitle className={`text-base font-newspaper-bold ${task.status === 'done' ? 'line-through text-foreground/50' : 'text-foreground'}`}>
            {task.title}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {/* 任务目标 */}
          <div className="border border-foreground/15 p-2.5 flex flex-col gap-1">
            <div className="text-[10px] font-newspaper-bold text-foreground/50">任务目标</div>
            <div className="text-xs font-newspaper text-foreground/70 whitespace-pre-wrap">
              {task.description?.trim() ? task.description : '未填写'}
            </div>
          </div>

          {/* 负责人 + 是否接入主链 */}
          <div className="grid grid-cols-2 gap-2">
            <div className="border border-foreground/15 p-2.5 flex flex-col gap-1">
              <div className="flex items-center gap-1 text-[10px] font-newspaper text-foreground/50">
                <UserIcon className="w-3 h-3" />
                任务负责人
              </div>
              {lead ? (
                <div className="flex items-center gap-1.5 text-xs font-newspaper text-foreground/80">
                  <span className="text-sm leading-none">{lead.avatar || '👤'}</span>
                  <span className="truncate">{lead.name}</span>
                </div>
              ) : (
                <div className="text-xs font-newspaper text-foreground/30">未指派</div>
              )}
            </div>
            <div className={`border p-2.5 flex flex-col gap-1 ${
              task.inherit_main_chain ? 'border-foreground/15' : 'border-amber-500/40 bg-amber-500/5'
            }`}>
              <div className="flex items-center gap-1 text-[10px] font-newspaper text-foreground/50">
                {task.inherit_main_chain ? <Link2Icon className="w-3 h-3" /> : <Link2OffIcon className="w-3 h-3" />}
                接入主链历史
              </div>
              <div className="text-xs font-newspaper text-foreground/80">
                {task.inherit_main_chain ? '是 · 继承分支点之前主链' : '否 · 完全隔离'}
              </div>
            </div>
          </div>

          {/* 参与者 */}
          {assignees.length > 0 && (
            <div className="border border-foreground/15 p-2.5 flex flex-col gap-1.5">
              <div className="flex items-center gap-1 text-[10px] font-newspaper text-foreground/50">
                <UsersIcon className="w-3 h-3" />
                参与者（{assignees.length}）
              </div>
              <div className="flex flex-wrap gap-1.5">
                {assignees.map(a => (
                  <span key={a.id} className="flex items-center gap-1 px-1.5 py-0.5 border border-foreground/15 text-xs font-newspaper text-foreground/70">
                    <span className="text-sm leading-none">{a.avatar || '👤'}</span>
                    {a.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 验收标准 */}
          <div className="border border-foreground/15 p-2.5 flex flex-col gap-1">
            <div className="text-[10px] font-newspaper-bold text-foreground/50">验收标准</div>
            <div className="text-xs font-newspaper text-foreground/70 whitespace-pre-wrap">
              {task.acceptance_criteria?.trim() ? task.acceptance_criteria : '未填写'}
            </div>
          </div>

          {/* 交付物 */}
          {task.deliverable && (
            <div className="border border-foreground/15 p-2.5 flex items-center gap-2">
              <FileTextIcon className="w-3.5 h-3.5 text-foreground/50 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-[10px] font-newspaper text-foreground/50">交付物</div>
                <div className="text-xs font-newspaper text-foreground/80 truncate">{task.deliverable.title}</div>
              </div>
            </div>
          )}

          {/* 时间戳 */}
          <div className="border border-foreground/15 p-2.5 flex flex-col gap-1 text-[11px] font-newspaper text-foreground/60">
            <div className="flex items-center gap-1 text-foreground/50">
              <CalendarIcon className="w-3 h-3" />
              <span>时间</span>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
              <span>创建：{formatDateTime(task.created_at)}</span>
              <span>开始：{formatDateTime(task.started_at)}</span>
              <span>更新：{formatDateTime(task.updated_at)}</span>
              <span>完成：{formatDateTime(task.completed_at)}</span>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

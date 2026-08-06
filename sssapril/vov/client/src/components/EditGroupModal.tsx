import { useState, useEffect } from 'react';
import { XIcon, BotIcon, CheckIcon, TrashIcon } from 'lucide-react';
import { toast } from 'sonner';
import { useUpdateGroup, useDeleteGroup } from '../hooks/useGroups';
import { useProjectAgents } from '../hooks/useAgents';
import ConfirmDialog from './ConfirmDialog';
import { useAppStore, type VisibilityKey } from '../store/appStore';
import type { GroupListItem, Group, AutonomyLevel, GroupStatus } from '../types';

interface EditGroupModalProps {
  open?: boolean;
  onClose?: () => void;
  onUpdated?: (id: string) => void;
  onDeleted?: (id: string) => void;
  group?: GroupListItem | Group | null;
  projectId?: string;
}

const AUTONOMY_LEVELS: { value: AutonomyLevel; label: string; description: string }[] = [
  { value: 'full_auto', label: '全自动', description: 'Agent 自由发言，无需确认' },
  { value: 'semi_auto', label: '半自动', description: 'Agent 可发言，关键操作需确认' },
  { value: 'manual', label: '手动', description: '所有操作需人工确认' },
];

const GROUP_STATUSES: { value: GroupStatus; label: string; description: string }[] = [
  { value: 'pending', label: '待开始', description: '群聊尚未启动' },
  { value: 'active', label: '进行中', description: '群聊正在活跃运行' },
  { value: 'completed', label: '已完成', description: '群聊任务已完成' },
];

/** 群级别可见性覆盖字段配置 */
const VISIBILITY_FIELDS: { key: VisibilityKey; label: string; description: string }[] = [
  { key: 'showThink', label: '思考过程', description: 'LLM 推理过程块' },
  { key: 'showToolCalls', label: '工具调用', description: 'Agent 调用的工具及结果' },
  { key: 'showSystemMessages', label: '系统消息', description: '任务创建/完成通知等' },
];

export default function EditGroupModal({
  open = false,
  onClose = () => {},
  onUpdated = () => {},
  onDeleted = () => {},
  group,
  projectId = '',
}: EditGroupModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [autonomyLevel, setAutonomyLevel] = useState<AutonomyLevel>('semi_auto');
  const [autoAdvance, setAutoAdvance] = useState(false);
  const [watchdogEnabled, setWatchdogEnabled] = useState(true);
  const [leadAgentId, setLeadAgentId] = useState('');
  const [status, setStatus] = useState<GroupStatus>('pending');
  const [deleting, setDeleting] = useState(false);

  const updateGroupMutation = useUpdateGroup();
  const deleteGroupMutation = useDeleteGroup();
  const { data: projectAgentsData } = useProjectAgents(projectId);
  const projectAgents = projectAgentsData?.items || [];

  // 群级别可见性覆盖：读取系统级默认 + 当前群的覆盖
  const systemShowThink = useAppStore((s) => s.showThink);
  const systemShowToolCalls = useAppStore((s) => s.showToolCalls);
  const systemShowSystemMessages = useAppStore((s) => s.showSystemMessages);
  const groupOverrides = useAppStore((s) =>
    group?.id ? s.groupVisibilityOverrides[group.id] : undefined
  );
  const setGroupVisibilityOverride = useAppStore((s) => s.setGroupVisibilityOverride);
  const systemValues: Record<VisibilityKey, boolean> = {
    showThink: systemShowThink,
    showToolCalls: systemShowToolCalls,
    showSystemMessages: systemShowSystemMessages,
  };

  useEffect(() => {
    if (group && open) {
      setName(group.name || '');
      setDescription(group.description || '');
      setAutonomyLevel(group.autonomy_level || 'semi_auto');
      setAutoAdvance(group.auto_advance || false);
      setWatchdogEnabled((group as Group).watchdog_enabled ?? true);
      setLeadAgentId(group.lead_agent?.id || '');
      setStatus(group.status || 'pending');
    }
    if (!open) {
      setDeleting(false);
    }
  }, [group, open]);

  const handleSubmit = async () => {
    if (!name.trim() || !group) return;
    try {
      await updateGroupMutation.mutateAsync({
        id: group.id,
        data: {
          name: name.trim(),
          description: description.trim(),
          autonomy_level: autonomyLevel,
          auto_advance: autoAdvance,
          watchdog_enabled: watchdogEnabled,
          lead_agent_id: leadAgentId || undefined,
          status,
        },
      });
      toast.success('群聊已更新');
      onUpdated(group.id);
      onClose();
    } catch (error) {
      console.error('Failed to update group:', error);
      toast.error('更新群聊失败');
    }
  };

  const handleDelete = async () => {
    if (!group || !projectId) return;
    try {
      await deleteGroupMutation.mutateAsync({ groupId: group.id, projectId });
      toast.success('群聊已删除');
      onDeleted(group.id);
      setDeleting(false);
      onClose();
    } catch (error) {
      console.error('Failed to delete group:', error);
      toast.error('删除群聊失败');
      throw error;
    }
  };

  const isLoading = updateGroupMutation.isPending;

  return (
    <>
      <div className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-200 ${open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}>
        <div className="absolute inset-0 bg-foreground/20 backdrop-blur-sm" onClick={onClose} />
        <div className={`relative border border-foreground/20 w-[500px] max-h-[85vh] overflow-y-auto transition-all duration-200 ${open ? 'scale-100' : 'scale-95'}`} onClick={e => e.stopPropagation()}>
          {/* Masthead header */}
          <div className="px-6 py-4 border-b border-foreground/20">
            <h2 className="text-base font-newspaper-bold text-foreground tracking-wide">编辑群聊</h2>
            <button onClick={onClose} className="absolute top-4 right-4 p-1.5 hover:bg-foreground/5 transition-colors">
              <XIcon className="w-4 h-4 text-foreground/40" />
            </button>
          </div>

          <div className="p-6 flex flex-col gap-4">
            {/* Name */}
            <div>
              <label className="text-xs font-newspaper-bold text-foreground/60 mb-1.5 block">群聊名称 *</label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder={`例：第一章创作组、世界观设定组`}
                className="w-full px-3 py-2 border border-foreground/15 bg-transparent font-newspaper text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/30"
              />
            </div>

            {/* Description */}
            <div>
              <label className="text-xs font-newspaper-bold text-foreground/60 mb-1.5 block">群聊描述</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder={`描述本群聊的任务目标`}
                rows={2}
                className="w-full px-3 py-2 border border-foreground/15 bg-transparent font-newspaper text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/30 resize-none"
              />
            </div>

            {/* Status */}
            <div>
              <label className="text-xs font-newspaper-bold text-foreground/60 mb-2 block">群聊状态</label>
              <div className="flex gap-2">
                {GROUP_STATUSES.map(s => (
                  <button
                    key={s.value}
                    onClick={() => setStatus(s.value)}
                    className={`flex-1 px-3 py-2 border text-center transition-all font-newspaper ${
                      status === s.value
                        ? 'border-foreground/40 text-foreground/80 underline underline-offset-2'
                        : 'border-foreground/15 text-foreground/50 hover:border-foreground/30'
                    }`}
                  >
                    <div className="text-sm font-newspaper-bold">{s.label}</div>
                    <div className="text-[10px] mt-0.5 opacity-70">{s.description}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Autonomy Level */}
            <div>
              <label className="text-xs font-newspaper-bold text-foreground/60 mb-2 block">自主级别</label>
              <div className="flex flex-col gap-2">
                {AUTONOMY_LEVELS.map(level => (
                  <button
                    key={level.value}
                    onClick={() => setAutonomyLevel(level.value)}
                    className={`flex items-start gap-3 p-3 border transition-all text-left font-newspaper ${
                      autonomyLevel === level.value ? 'border-foreground/40 underline' : 'border-foreground/15 hover:border-foreground/30'
                    }`}
                  >
                    <div className={`w-5 h-5 border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-all ${autonomyLevel === level.value ? 'border-foreground/60' : 'border-foreground/20'}`}>
                      <CheckIcon className={`w-3 h-3 ${autonomyLevel === level.value ? 'text-foreground/80' : 'text-transparent'}`} />
                    </div>
                    <div>
                      <div className="text-sm font-newspaper-bold text-foreground">{level.label}</div>
                      <div className="text-xs text-foreground/50">{level.description}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Auto Advance */}
            <div className="flex items-center justify-between p-3 border border-foreground/15">
              <div>
                <div className="text-sm font-newspaper-bold text-foreground">自动推进</div>
                <div className="text-xs text-foreground/50 font-newspaper">完成后自动进入下一阶段</div>
              </div>
              <button
                onClick={() => setAutoAdvance(!autoAdvance)}
                className={`w-11 h-6 transition-all ${autoAdvance ? 'bg-foreground/60' : 'bg-foreground/15'}`}
              >
                <div className={`w-5 h-5 bg-background transition-transform ${autoAdvance ? 'translate-x-5.5' : 'translate-x-0.5'}`} />
              </button>
            </div>

            {/* Watchdog (空闲提醒) */}
            <div className="flex items-center justify-between p-3 border border-foreground/15">
              <div>
                <div className="text-sm font-newspaper-bold text-foreground">空闲提醒</div>
                <div className="text-xs text-foreground/50 font-newspaper">群空闲 10 分钟时自动唤醒 lead; 不关心的群请关闭以节省 LLM token</div>
              </div>
              <button
                onClick={() => setWatchdogEnabled(!watchdogEnabled)}
                className={`w-11 h-6 transition-all ${watchdogEnabled ? 'bg-foreground/60' : 'bg-foreground/15'}`}
              >
                <div className={`w-5 h-5 bg-background transition-transform ${watchdogEnabled ? 'translate-x-5.5' : 'translate-x-0.5'}`} />
              </button>
            </div>

            {/* Lead Agent */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <BotIcon className="w-4 h-4 text-foreground/50" />
                <label className="text-xs font-newspaper-bold text-foreground/60">主导 Agent</label>
              </div>
              <select
                value={leadAgentId}
                onChange={e => setLeadAgentId(e.target.value)}
                className="w-full px-3 py-2 border border-foreground/15 bg-transparent font-newspaper text-sm text-foreground focus:outline-none focus:border-foreground/30"
              >
                <option value="">未指定</option>
                {projectAgents.map(pa => {
                  const agent = pa.agent;
                  return (
                    <option key={pa.id} value={pa.id}>
                      {agent?.name || 'Unknown'}
                    </option>
                  );
                })}
              </select>
            </div>

            {/* 消息显示偏好 (群级别覆盖系统级) */}
            {group?.id && (
              <div className="mt-2 pt-4 border-t border-foreground/20">
                <div className="mb-3">
                  <div className="text-sm font-newspaper-bold text-foreground">消息显示偏好</div>
                  <div className="text-xs text-foreground/50 font-newspaper mt-0.5">
                    为本群单独覆盖系统级可见性。"继承"表示跟随系统设置（括号内为当前系统值）。
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  {VISIBILITY_FIELDS.map(field => {
                    const override = groupOverrides?.[field.key];
                    const systemValue = systemValues[field.key];
                    return (
                      <div key={field.key} className="flex items-center justify-between gap-3 p-2 border border-foreground/10">
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-newspaper-bold text-foreground">{field.label}</div>
                          <div className="text-xs text-foreground/50 font-newspaper">{field.description}</div>
                        </div>
                        <div className="flex gap-1 flex-shrink-0">
                          {([undefined, true, false] as const).map(val => {
                            const isActive = override === val;
                            const label = val === undefined
                              ? `继承 (${systemValue ? '显示' : '隐藏'})`
                              : val ? '显示' : '隐藏';
                            return (
                              <button
                                key={String(val)}
                                type="button"
                                onClick={() => setGroupVisibilityOverride(group.id, field.key, val)}
                                className={`px-2 py-1 text-xs font-newspaper border transition-all whitespace-nowrap ${
                                  isActive
                                    ? 'border-foreground/50 text-foreground/80 bg-foreground/5'
                                    : 'border-foreground/15 text-foreground/50 hover:border-foreground/30'
                                }`}
                              >
                                {label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Danger Zone */}
            <div className="mt-2 pt-4 border-t border-foreground/20">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-newspaper-bold text-foreground/60">删除群聊</div>
                  <div className="text-xs text-foreground/40 font-newspaper">删除后不可恢复，所有消息和任务将被清除</div>
                </div>
                <button
                  onClick={() => setDeleting(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-foreground/30 text-sm font-newspaper text-foreground/60 hover:text-foreground/80 hover:border-foreground/50 transition-colors"
                >
                  <TrashIcon className="w-4 h-4" />
                  删除
                </button>
              </div>
            </div>
          </div>

          <div className="px-6 pb-6 flex gap-3 justify-end">
            <button onClick={onClose} className="px-4 py-2 text-sm font-newspaper text-foreground/50 hover:text-foreground/70 underline-offset-2 hover:underline transition-all">
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={!name.trim() || isLoading}
              className="px-5 py-2 text-sm font-newspaper-bold text-foreground/70 hover:text-foreground/90 underline-offset-2 hover:underline transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isLoading ? '保存中...' : '保存修改'}
            </button>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={deleting}
        onClose={() => setDeleting(false)}
        onConfirm={handleDelete}
        title="删除群聊"
        description={`确定要删除群聊「${group?.name || ''}」吗？此操作不可撤销，所有消息和任务将被永久删除。`}
        confirmText="删除"
        destructive
      />
    </>
  );
}

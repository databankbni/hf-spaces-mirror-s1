import { useState } from 'react';
import { XIcon, BotIcon, CheckIcon } from 'lucide-react';
import { useCreateGroup } from '../hooks/useGroups';
import { useProjectAgents } from '../hooks/useAgents';

interface CreateGroupModalProps {
  open?: boolean;
  projectId?: string;
  onClose?: () => void;
  onCreated?: (id: string) => void;
}

export default function CreateGroupModal({
  open = false,
  projectId = '',
  onClose = () => {},
  onCreated = () => {},
}: CreateGroupModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);

  const createGroupMutation = useCreateGroup();
  const { data: projectAgentsData } = useProjectAgents(projectId);
  const projectAgents = projectAgentsData?.items || [];

  const toggleAgent = (agentId: string) => {
    setSelectedAgents(prev =>
      prev.includes(agentId) ? prev.filter(id => id !== agentId) : [...prev, agentId]
    );
  };

  const handleSubmit = async () => {
    if (!name.trim() || !projectId) return;
    try {
      const group = await createGroupMutation.mutateAsync({
        projectId,
        data: {
          name: name.trim(),
          description: description.trim(),
          member_agent_ids: selectedAgents,
        },
      });
      setName('');
      setDescription('');
      setSelectedAgents([]);
      onCreated(group.id);
      onClose();
    } catch (error) {
      console.error('Failed to create group:', error);
    }
  };

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-200 ${open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}>
      <div className="absolute inset-0 bg-foreground/20 backdrop-blur-sm" onClick={onClose} />
      <div className={`relative border border-foreground/20 w-[500px] max-h-[85vh] overflow-y-auto transition-all duration-200 ${open ? 'scale-100' : 'scale-95'}`} onClick={e => e.stopPropagation()}>
        {/* Masthead header */}
        <div className="px-6 py-4 border-b border-foreground/20">
          <h2 className="text-base font-newspaper-bold text-foreground tracking-wide">创建群聊</h2>
          <button onClick={onClose} className="absolute top-4 right-4 p-1.5 hover:bg-foreground/5 transition-colors">
            <XIcon className="w-4 h-4 text-foreground/40" />
          </button>
        </div>

        <div className="p-6 flex flex-col gap-4">
          <div>
            <label className="text-xs font-newspaper-bold text-foreground/60 mb-1.5 block">群聊名称 *</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder={`例：第一章创作组、世界观设定组`}
              className="w-full px-3 py-2 border border-foreground/15 bg-transparent font-newspaper text-sm text-foreground placeholder:text-foreground/30 focus:outline-none focus:border-foreground/30"
            />
          </div>

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

          <div>
            <div className="flex items-center gap-2 mb-2">
              <BotIcon className="w-4 h-4 text-foreground/50" />
              <label className="text-xs font-newspaper-bold text-foreground/60">邀请 Agent</label>
              <span className="text-xs font-newspaper text-foreground/40 ml-auto">{selectedAgents.length} 已选</span>
            </div>
            {projectAgents.length === 0 ? (
              <div className="text-xs font-newspaper text-foreground/40 py-3 text-center border border-foreground/15">
                项目中暂无 Agent，请先在项目中添加 Agent
              </div>
            ) : (
              <div className="flex flex-col gap-2 max-h-52 overflow-y-auto">
                {projectAgents.map(pa => {
                  const agent = pa.agent;
                  const selected = selectedAgents.includes(pa.id);
                  return (
                    <button
                      key={pa.id}
                      onClick={() => toggleAgent(pa.id)}
                      className={`flex items-center gap-3 p-3 border transition-all text-left font-newspaper ${selected ? 'border-foreground/40 underline' : 'border-foreground/15 hover:border-foreground/30'}`}
                    >
                      <div className="w-9 h-9 border border-foreground/15 flex items-center justify-center text-base flex-shrink-0">
                        {agent?.avatar || '🤖'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-newspaper-bold text-foreground">{agent?.name || 'Unknown'}</div>
                      </div>
                      <div className={`w-5 h-5 border-2 flex items-center justify-center flex-shrink-0 transition-all ${selected ? 'border-foreground/60' : 'border-foreground/20'}`}>
                        <CheckIcon className={`w-3 h-3 ${selected ? 'text-foreground/80' : 'text-transparent'}`} />
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="px-6 pb-6 flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm font-newspaper text-foreground/50 hover:text-foreground/70 underline-offset-2 hover:underline transition-all">
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={!name.trim()}
            className="px-5 py-2 text-sm font-newspaper-bold text-foreground/70 hover:text-foreground/90 underline-offset-2 hover:underline transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            创建群聊
          </button>
        </div>
      </div>
    </div>
  );
}

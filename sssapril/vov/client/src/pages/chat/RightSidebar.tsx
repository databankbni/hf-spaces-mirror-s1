import { useMemo } from 'react';
import { FileTextIcon } from 'lucide-react';
import { useChatPage } from './context';
import { useProjectMemories } from '../../hooks/useAgents';
import TaskPanel from '../../components/TaskPanel';
import MemberPanel from '../../components/MemberPanel';
import type { AgentMemory } from '../../types/agent';

export default function RightSidebar() {
  const {
    rightTab, setRightTab, group, project,
    handleTaskClick, handleViewDeliverable,
    refreshChains,
  } = useChatPage();

  // 获取项目所有 Agent 记忆，构建 agent_id -> AgentMemory[] 映射
  const { data: memoriesData } = useProjectMemories(project.id);
  const memoriesMap = useMemo<Record<string, AgentMemory[]>>(() => {
    if (!memoriesData?.items) return {};
    const map: Record<string, AgentMemory[]> = {};
    for (const item of memoriesData.items) {
      const agentId = (item as any).agent_id;
      if (agentId) {
        if (!map[agentId]) {
          map[agentId] = [];
        }
        map[agentId].push(item as AgentMemory);
      }
    }
    return map;
  }, [memoriesData]);

  return (
    <aside className="w-64 flex-shrink-0 border-l border-foreground/15 flex flex-col overflow-hidden">
      <div className="flex gap-1 p-1.5 border-b border-foreground/15 flex-shrink-0">
        <button
          onClick={() => setRightTab('tasks')}
          className={`flex-1 text-[10px] py-1 font-newspaper transition-all duration-200 border-b-2 ${
            rightTab === 'tasks' ? 'border-foreground/60 text-foreground/80' : 'border-transparent text-foreground/40 hover:text-foreground/60'
          }`}
        >
          任务
        </button>
        <button
          onClick={() => setRightTab('members')}
          className={`flex-1 text-[10px] py-1 font-newspaper transition-all duration-200 border-b-2 ${
            rightTab === 'members' ? 'border-foreground/60 text-foreground/80' : 'border-transparent text-foreground/40 hover:text-foreground/60'
          }`}
        >
          成员
        </button>
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-y-auto p-2">

        {/* Tasks tab */}
        <div className={rightTab === 'tasks' ? '' : 'hidden'}>
          <TaskPanel
            tasks={(group.tasks || []) as any}
            deliverables={group.deliverables || []}
            projectId={project.id}
            groupId={group.id}
            memberIds={(group.members || []).map((m: any) => m.agent?.id || '')}
            onTaskClick={handleTaskClick}
            onTaskMutated={refreshChains}
          />

          {/* Deliverables section */}
          <div className={`mt-3 flex flex-col gap-1.5 ${(group.deliverables || []).length === 0 ? 'hidden' : ''}`}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-newspaper-bold text-foreground/80">交付物</span>
              <span className="text-[10px] border border-foreground/20 text-foreground/60 px-1.5 py-0.5 font-newspaper">
                {(group.deliverables || []).length}
              </span>
            </div>
            {(group.deliverables || []).map((deliv: any) => (
              <button
                key={deliv.id}
                onClick={() => handleViewDeliverable(deliv.id)}
                className="flex items-start gap-2 p-2 border border-foreground/15 hover:border-foreground/30 transition-all text-left group"
              >
                <FileTextIcon className="w-3.5 h-3.5 text-foreground/60 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] font-newspaper-bold text-foreground/60 group-hover:text-foreground/80 transition-colors line-clamp-2">
                    {deliv.title}
                  </div>
                  <div className="text-[10px] text-foreground/30 mt-0.5 font-newspaper">{deliv.author?.name || '未知'}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Members tab */}
        <div className={rightTab === 'members' ? '' : 'hidden'}>
          <MemberPanel
            members={group.members || []}
            projectId={project.id}
            groupId={group.id}
            memories={memoriesMap}
          />
        </div>
      </div>
    </aside>
  );
}

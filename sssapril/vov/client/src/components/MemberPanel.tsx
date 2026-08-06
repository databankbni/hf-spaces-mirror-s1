import { useState, useMemo } from 'react';
import { BotIcon, UserIcon, PlusIcon, XIcon, TrashIcon, CrownIcon, ShieldCheckIcon, SearchIcon } from 'lucide-react';
import { useAddGroupMember, useRemoveGroupMember, useUpdateMemberRole } from '../hooks/useGroups';
import { useProjectAgents, useAgents, useAddAgentToProject } from '../hooks/useAgents';
import AgentCard from './AgentCard';
import ConfirmDialog from './ConfirmDialog';
import type { GroupMember } from '../types/agent';
import type { AgentMemory } from '../types/agent';

interface MemberPanelProps {
  members?: GroupMember[];
  memberIds?: string[];
  projectId?: string;
  groupId?: string;
  memories?: Record<string, AgentMemory[]>;
}

type InviteCandidate = {
  id: string;
  agent: any;
  inProject: boolean;
  projectAgentId?: string;
};

export default function MemberPanel({
  members,
  memberIds = [],
  projectId = '',
  groupId = '',
  memories,
}: MemberPanelProps) {
  const [selectedAgent, setSelectedAgent] = useState<{
    agent: any;
    groupRole?: 'lead' | 'participant';
    joinedAt?: string;
    memories?: AgentMemory[] | null;
  } | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [removingMember, setRemovingMember] = useState<typeof memberList[0] | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [invitingId, setInvitingId] = useState<string | null>(null);

  const addMemberMutation = useAddGroupMember();
  const removeMemberMutation = useRemoveGroupMember();
  const updateRoleMutation = useUpdateMemberRole();
  const addAgentToProjectMutation = useAddAgentToProject();
  const { data: projectAgentsData } = useProjectAgents(projectId);
  const projectAgents = projectAgentsData?.items || [];
  const { data: allAgentsData } = useAgents();
  const allAgents = allAgentsData?.items || [];

  // 辅助函数：优先获取 default slug 的记忆，否则取第一条
  const getDefaultMemory = (memories: AgentMemory[] | undefined): AgentMemory | null => {
    if (!memories || memories.length === 0) return null;
    return memories.find(m => m.slug === 'default') || memories[0];
  };

  const memberList = members && members.length > 0
    ? members.map(m => ({
        projectAgentId: m.project_agent_id,
        agent: m.agent,
        groupRole: m.role,
        joinedAt: m.joined_at,
        memory: getDefaultMemory(memories?.[m.agent?.id]),
        memories: memories?.[m.agent?.id] || null,
      }))
    : projectAgents
        .filter(pa => memberIds.includes(pa.id))
        .map(pa => ({
          projectAgentId: pa.id,
          agent: pa.agent,
          groupRole: undefined as 'lead' | 'participant' | undefined,
          joinedAt: undefined as string | undefined,
          memory: getDefaultMemory(memories?.[pa.agent?.id]) || pa.memory || null,
          memories: memories?.[pa.agent?.id] || null,
        }));

  const currentMemberAgentIds = new Set(memberList.map(m => m.agent?.id).filter(Boolean));
  const projectAgentMap = new Map(projectAgents.map(pa => [pa.agent?.id, pa]));

  const availableAgents: InviteCandidate[] = useMemo(() => {
    const candidates: InviteCandidate[] = [];

    for (const pa of projectAgents) {
      if (!currentMemberAgentIds.has(pa.agent?.id)) {
        candidates.push({
          id: pa.agent?.id,
          agent: pa.agent,
          inProject: true,
          projectAgentId: pa.id,
        });
      }
    }

    for (const agent of allAgents) {
      if (!currentMemberAgentIds.has(agent.id) && !projectAgentMap.has(agent.id)) {
        candidates.push({
          id: agent.id,
          agent,
          inProject: false,
        });
      }
    }

    return candidates;
  }, [projectAgents, allAgents, currentMemberAgentIds]);

  const filteredAgents = useMemo(() => {
    if (!searchQuery.trim()) return availableAgents;
    const q = searchQuery.toLowerCase();
    return availableAgents.filter(c =>
      c.agent?.name?.toLowerCase().includes(q) ||
      c.agent?.description?.toLowerCase().includes(q)
    );
  }, [availableAgents, searchQuery]);

  const handleInvite = async (candidate: InviteCandidate) => {
    if (!groupId || !projectId) return;
    setInvitingId(candidate.id);
    try {
      let projectAgentId = candidate.projectAgentId;

      if (!candidate.inProject) {
        const result = await addAgentToProjectMutation.mutateAsync({
          projectId,
          agentId: candidate.id,
        });
        projectAgentId = result.id;
      }

      if (projectAgentId) {
        await addMemberMutation.mutateAsync({
          groupId,
          projectAgentId,
          role: 'participant',
        });
      }
    } finally {
      setInvitingId(null);
    }
  };

  const handleRemove = async () => {
    if (!removingMember || !groupId) return;
    await removeMemberMutation.mutateAsync({
      groupId,
      agentId: removingMember.projectAgentId,
    });
  };

  const handleToggleRole = (member: typeof memberList[0]) => {
    const newRole = member.groupRole === 'lead' ? 'participant' : 'lead';
    updateRoleMutation.mutate({ groupId, agentId: member.projectAgentId, role: newRole });
  };

  const handleSelectMember = (member: typeof memberList[0]) => {
    setSelectedAgent({
      agent: member.agent,
      groupRole: member.groupRole,
      joinedAt: member.joinedAt,
      memories: member.memories,
    });
  };

  const isInviting = invitingId !== null;

  return (
    <div data-cmp="MemberPanel" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-newspaper-bold text-foreground">成员</span>
        <button
          onClick={() => setShowInvite(!showInvite)}
          className="flex items-center gap-1 text-xs font-newspaper text-foreground/60 hover:text-foreground/80 underline-offset-2 hover:underline transition-all"
        >
          <PlusIcon className="w-3.5 h-3.5" />
          邀请
        </button>
      </div>

      {/* Human member */}
      <div className="flex items-center gap-2.5 p-2.5 border border-foreground/15">
        <div className="w-8 h-8 border border-foreground/20 flex items-center justify-center flex-shrink-0">
          <UserIcon className="w-4 h-4 text-foreground/60" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-newspaper-bold text-foreground">我（人类）</div>
          <div className="text-xs text-foreground/40 font-newspaper">项目发起者</div>
        </div>
      </div>

      {/* Agent members */}
      {memberList.map((member) => {
        const agent = member.agent;
        return (
          <div
            key={member.projectAgentId}
            className="flex items-center gap-2.5 p-2.5 border border-foreground/15 hover:border-foreground/30 transition-all group"
          >
            <button
              onClick={() => handleSelectMember(member)}
              className="flex items-center gap-2.5 flex-1 min-w-0 text-left"
            >
              <div className="w-8 h-8 border border-foreground/15 flex items-center justify-center text-sm flex-shrink-0">
                {agent?.avatar || '🤖'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-newspaper-bold text-foreground group-hover:text-foreground/80 transition-colors">
                    {agent?.name || 'Unknown'}
                  </span>
                  {member.groupRole === 'lead' && (
                    <span className="font-newspaper-bold opacity-70 text-[10px]">
                      负责人
                    </span>
                  )}
                </div>
              </div>
            </button>
            <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={(e) => { e.stopPropagation(); handleToggleRole(member); }}
                className={`p-1 transition-colors ${
                  member.groupRole === 'lead'
                    ? 'hover:bg-foreground/5 text-foreground/60'
                    : 'hover:bg-foreground/5 text-foreground/40'
                }`}
                title={member.groupRole === 'lead' ? '当前：负责人，点击设为成员' : '当前：成员，点击设为负责人'}
              >
                {member.groupRole === 'lead' ? (
                  <CrownIcon className="w-3.5 h-3.5" />
                ) : (
                  <ShieldCheckIcon className="w-3.5 h-3.5" />
                )}
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setRemovingMember(member); }}
                className="p-1 hover:bg-foreground/5 transition-colors"
                title="移除成员"
              >
                <TrashIcon className="w-3 h-3 text-foreground/40 hover:text-foreground/60" />
              </button>
            </div>
          </div>
        );
      })}

      {memberList.length === 0 && (
        <div className="text-xs font-newspaper text-foreground/40 py-2 text-center">暂无 Agent，点击邀请</div>
      )}

      {/* Invite panel */}
      <div className={`overflow-hidden transition-all duration-200 ${showInvite ? 'max-h-[480px]' : 'max-h-0'}`}>
        <div className="border border-foreground/15 p-3 mt-1">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-newspaper-bold text-foreground/60">可邀请的 Agent</span>
            <button
              onClick={() => setShowInvite(false)}
              className="p-0.5 hover:bg-foreground/5 transition-colors"
            >
              <XIcon className="w-3.5 h-3.5 text-foreground/40" />
            </button>
          </div>

          <div className="relative mb-2">
            <SearchIcon className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-foreground/30" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="搜索 Agent 名称、角色或描述..."
              className="w-full text-xs font-newspaper border border-foreground/15 bg-transparent pl-7 pr-2 py-1.5 focus:outline-none focus:border-foreground/30 placeholder:text-foreground/30"
            />
          </div>

          {filteredAgents.length === 0 ? (
            <div className="text-xs font-newspaper text-foreground/40 text-center py-3">
              {allAgents.length === 0
                ? '暂无可用 Agent，请先创建'
                : searchQuery.trim()
                  ? '没有匹配的 Agent'
                  : '所有 Agent 已在群内'}
            </div>
          ) : (
            <div className="flex flex-col gap-1.5 max-h-60 overflow-y-auto">
              {filteredAgents.map((candidate) => {
                const agent = candidate.agent;
                const isInvitingThis = invitingId === candidate.id;
                return (
                  <button
                    key={candidate.id}
                    onClick={() => handleInvite(candidate)}
                    disabled={isInviting}
                    className="flex items-center gap-2 p-2 hover:bg-foreground/5 transition-colors text-left disabled:opacity-50"
                  >
                    <div className="w-7 h-7 border border-foreground/15 flex items-center justify-center text-sm flex-shrink-0">
                      {agent?.avatar || '🤖'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-newspaper-bold text-foreground">{agent?.name || 'Unknown'}</span>
                        {!candidate.inProject && (
                          <span className="font-newspaper opacity-70 text-[10px]">
                            未加入项目
                          </span>
                        )}
                      </div>
                      {agent?.description && (
                        <div className="text-[11px] font-newspaper text-foreground/40 truncate mt-0.5">{agent.description}</div>
                      )}
                    </div>
                    {isInvitingThis ? (
                      <div className="w-3.5 h-3.5 border-2 border-foreground/40 border-t-transparent animate-spin flex-shrink-0" />
                    ) : (
                      <PlusIcon className="w-3.5 h-3.5 text-foreground/50 flex-shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Agent detail popup */}
      {selectedAgent && (
        <AgentCard
          agent={selectedAgent.agent}
          groupRole={selectedAgent.groupRole}
          joinedAt={selectedAgent.joinedAt}
          memories={selectedAgent.memories}
          onClose={() => setSelectedAgent(null)}
        />
      )}

      {/* Remove Member Confirmation */}
      <ConfirmDialog
        open={!!removingMember}
        onClose={() => setRemovingMember(null)}
        onConfirm={handleRemove}
        title="移除成员"
        description={`确定要将「${removingMember?.agent?.name}」从群聊中移除吗？`}
        confirmText="移除"
        destructive
      />
    </div>
  );
}

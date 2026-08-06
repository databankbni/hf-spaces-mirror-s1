import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MemberPanel from '../MemberPanel';
import type { GroupMember, Agent, ProjectAgent } from '../../types/agent';

let mockProjectAgents: ProjectAgent[] = [];
let mockAllAgents: Agent[] = [];

vi.mock('../../hooks/useGroups', () => ({
  useAddGroupMember: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
  useRemoveGroupMember: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
  useUpdateMemberRole: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
}));

vi.mock('../../hooks/useAgents', () => ({
  useProjectAgents: () => ({ data: { items: mockProjectAgents } }),
  useAgents: () => ({ data: { items: mockAllAgents } }),
  useAddAgentToProject: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock('../AgentCard', () => ({
  default: () => <div data-testid="agent-card">AgentCard</div>,
}));

vi.mock('../ConfirmDialog', () => ({
  default: ({ open }: { open: boolean }) =>
    open ? <div data-testid="confirm-dialog">ConfirmDialog</div> : null,
}));

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-1',
    name: 'TestAgent',
    // v2 P3: 删除 role 字段
    avatar: '🤖',
    description: 'A test agent',
    system_prompt: '',
    llm_config: { model: 'gpt-4' },
    capabilities: [],
    is_active: true,
    tools: [],
    skills: [],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

function makeMember(overrides: Partial<GroupMember> = {}): GroupMember {
  return {
    id: 'member-1',
    project_agent_id: 'pa-1',
    agent: makeAgent(),
    role: 'participant',
    joined_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('MemberPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockProjectAgents = [];
    mockAllAgents = [];
  });

  it('正确渲染成员列表', () => {
    const members = [
      makeMember({ id: 'm1', project_agent_id: 'pa1', agent: makeAgent({ id: 'a1', name: 'Alice' }), role: 'participant' }),
      makeMember({ id: 'm2', project_agent_id: 'pa2', agent: makeAgent({ id: 'a2', name: 'Bob' }), role: 'lead' }),
    ];

    renderWithProviders(<MemberPanel members={members} projectId="proj-1" groupId="grp-1" />);

    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('成员')).toBeInTheDocument();
  });

  it('点击"邀请"按钮展开邀请面板', () => {
    renderWithProviders(<MemberPanel members={[]} projectId="proj-1" groupId="grp-1" />);

    const inviteButton = screen.getByText('邀请');
    fireEvent.click(inviteButton);

    expect(screen.getByText('可邀请的 Agent')).toBeInTheDocument();
  });

  it('角色切换按钮显示正确的tooltip（负责人/成员）', () => {
    const leadMember = makeMember({
      id: 'm1',
      project_agent_id: 'pa1',
      agent: makeAgent({ id: 'a1', name: 'LeadAgent' }),
      role: 'lead',
    });
    const participantMember = makeMember({
      id: 'm2',
      project_agent_id: 'pa2',
      agent: makeAgent({ id: 'a2', name: 'ParticipantAgent' }),
      role: 'participant',
    });

    renderWithProviders(
      <MemberPanel members={[leadMember, participantMember]} projectId="proj-1" groupId="grp-1" />,
    );

    const leadTooltip = screen.getByTitle('当前：负责人，点击设为成员');
    expect(leadTooltip).toBeInTheDocument();

    const memberTooltip = screen.getByTitle('当前：成员，点击设为负责人');
    expect(memberTooltip).toBeInTheDocument();
  });

  it('所有agent已在群内时显示"所有 Agent 已在群内"', () => {
    const agent1 = makeAgent({ id: 'a1', name: 'Alice' });
    const agent2 = makeAgent({ id: 'a2', name: 'Bob' });

    mockAllAgents = [agent1, agent2];
    mockProjectAgents = [
      { id: 'pa1', agent: agent1, override_config: {}, memory: null, created_at: '2024-01-01T00:00:00Z' },
      { id: 'pa2', agent: agent2, override_config: {}, memory: null, created_at: '2024-01-01T00:00:00Z' },
    ];

    const members = [
      makeMember({ project_agent_id: 'pa1', agent: agent1, role: 'participant' }),
      makeMember({ project_agent_id: 'pa2', agent: agent2, role: 'participant' }),
    ];

    renderWithProviders(<MemberPanel members={members} projectId="proj-1" groupId="grp-1" />);

    fireEvent.click(screen.getByText('邀请'));

    expect(screen.getByText('所有 Agent 已在群内')).toBeInTheDocument();
  });
});

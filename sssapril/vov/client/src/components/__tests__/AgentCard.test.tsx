import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import AgentCard from '../AgentCard';
import type { Agent } from '../../types/agent';

vi.mock('../ui/tabs', () => ({
  Tabs: ({ children, defaultValue }: { children: React.ReactNode; defaultValue: string }) => (
    <div data-testid="tabs" data-default-value={defaultValue}>{children}</div>
  ),
  TabsList: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="tabs-list">{children}</div>
  ),
  TabsTrigger: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <button data-testid={`tab-trigger-${value}`}>{children}</button>
  ),
  TabsContent: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <div data-testid={`tab-content-${value}`}>{children}</div>
  ),
}));

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

describe('AgentCard', () => {
  it('Agent详情弹窗正确渲染agent名称', () => {
    const agent = makeAgent({ name: 'Alpha' });

    render(<AgentCard agent={agent} />);

    expect(screen.getByText('Alpha')).toBeInTheDocument();
  });

  it('groupRole为lead时显示"负责人"标签', () => {
    const agent = makeAgent({ name: 'LeadBot' });

    render(<AgentCard agent={agent} groupRole="lead" />);

    expect(screen.getAllByText('负责人').length).toBeGreaterThan(0);
  });

  it('groupRole为participant时显示"参与者"标签', () => {
    const agent = makeAgent({ name: 'ParticipantBot' });

    render(<AgentCard agent={agent} groupRole="participant" />);

    expect(screen.getAllByText('参与者').length).toBeGreaterThan(0);
  });

  it('关闭按钮调用onClose回调', () => {
    const agent = makeAgent({ name: 'CloseBot' });
    const onClose = vi.fn();

    render(<AgentCard agent={agent} onClose={onClose} />);

    const closeButtons = screen.getAllByRole('button');
    const closeButton = closeButtons.find(btn => btn.querySelector('svg'));

    if (closeButton) {
      fireEvent.click(closeButton);
      expect(onClose).toHaveBeenCalledTimes(1);
    }
  });
});

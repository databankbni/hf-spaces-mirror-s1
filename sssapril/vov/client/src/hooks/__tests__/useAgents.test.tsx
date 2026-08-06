import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAgents } from '../useAgents';

vi.mock('../../api', () => ({
  agentApi: {
    list: vi.fn().mockResolvedValue({
      data: {
        items: [
          { id: 'a1', name: 'Agent1' },
          { id: 'a2', name: 'Agent2' },
        ],
        total: 2,
      },
    }),
  },
  projectAgentApi: {},
  memoryApi: {},
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe('useAgents', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('返回正确的数据结构', async () => {
    const wrapper = createWrapper();

    const { result } = renderHook(() => useAgents(), { wrapper });

    await vi.waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.items).toHaveLength(2);
    expect(result.current.data?.items[0].name).toBe('Agent1');
    expect(result.current.data?.items[1].name).toBe('Agent2');
    expect(result.current.data?.total).toBe(2);
  });

  it('支持传入filters参数', async () => {
    const wrapper = createWrapper();

    const filters = { role: 'writer' as const };
    const { result } = renderHook(() => useAgents(filters), { wrapper });

    await vi.waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.items).toHaveLength(2);
  });
});

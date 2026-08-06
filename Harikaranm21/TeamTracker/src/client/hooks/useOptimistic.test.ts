import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useOptimistic } from './useOptimistic';

describe('useOptimistic', () => {
  it('initialises with the provided value', () => {
    const { result } = renderHook(() => useOptimistic([1, 2, 3]));
    expect(result.current.data).toEqual([1, 2, 3]);
  });

  it('applies optimistic value immediately', async () => {
    const { result } = renderHook(() => useOptimistic<number[]>([]));

    await act(async () => {
      await result.current.update([99], async () => {
        // simulate slow network
        await new Promise((r) => setTimeout(r, 10));
      });
    });

    expect(result.current.data).toEqual([99]);
  });

  it('rolls back to previous value on failure', async () => {
    const { result } = renderHook(() => useOptimistic<number[]>([1, 2]));

    await act(async () => {
      try {
        await result.current.update([99], async () => {
          throw new Error('network error');
        });
      } catch {
        // expected
      }
    });

    expect(result.current.data).toEqual([1, 2]);
  });

  it('uses returned value from action when provided', async () => {
    const { result } = renderHook(() => useOptimistic<number[]>([]));

    await act(async () => {
      await result.current.update([99], async () => [1, 2, 3]);
    });

    expect(result.current.data).toEqual([1, 2, 3]);
  });
});

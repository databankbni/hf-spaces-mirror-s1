/**
 * useOptimistic — lightweight optimistic update helper.
 * Applies an immediate local state change, calls the async action,
 * and rolls back to the previous state on failure.
 *
 * @module hooks/useOptimistic
 */
import { useState, useCallback } from 'react';

interface UseOptimisticReturn<T> {
  data: T;
  update: (optimisticValue: T, action: () => Promise<T | void>) => Promise<void>;
}

export function useOptimistic<T>(initial: T): UseOptimisticReturn<T> {
  const [data, setData] = useState<T>(initial);

  const update = useCallback(
    async (optimisticValue: T, action: () => Promise<T | void>): Promise<void> => {
      const previous = data;
      setData(optimisticValue);
      try {
        const result = await action();
        if (result !== undefined) setData(result as T);
      } catch (err) {
        setData(previous); // rollback
        throw err;
      }
    },
    [data]
  );

  return { data, update };
}

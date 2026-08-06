/**
 * 应用状态Hook
 *
 * 提供对应用全局状态的访问。
 * 使用Zustand store，自动订阅状态变化。
 */

import { useAppStore } from '../store/appStore';

/**
 * 应用状态Hook
 *
 * @returns 应用状态和操作方法
 *
 * @example
 * ```tsx
 * const { activeProjectId, setActiveProjectId } = useStore();
 * ```
 */
export function useStore() {
  return useAppStore();
}

export default useStore;

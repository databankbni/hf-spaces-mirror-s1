import { useState, useCallback, useRef, useEffect } from 'react';
import { chainApi } from '../api';
import type { ChainView, Chain } from '../types';

const MAX_CACHE_SIZE = 50;

interface UseChainViewsParams {
  groupId: string | undefined;
}

function evictLRU(cache: Record<string, ChainView>, accessOrder: string[]): Record<string, ChainView> {
  if (Object.keys(cache).length <= MAX_CACHE_SIZE) return cache;
  const newCache = { ...cache };
  let removed = 0;
  const target = Object.keys(cache).length - MAX_CACHE_SIZE;
  for (const key of accessOrder) {
    if (removed >= target) break;
    if (newCache[key]) {
      delete newCache[key];
      removed++;
    }
  }
  return newCache;
}

export function useChainViews({ groupId }: UseChainViewsParams) {
  const [taskChainViews, setTaskChainViews] = useState<ChainView[]>([]);
  const [chainViewCache, setChainViewCache] = useState<Record<string, ChainView>>({});
  const [chainsLoading, setChainsLoading] = useState(false);
  // v2 P2+: 用户从侧边栏点击 task 后, 需要把对应 chain 强制展开 + 滚动到
  // 这里记录需要 force expand 的 chainId 集合, ChatPanel 把它传给 ChainBlock.forceExpanded
  const [forceExpandedChainIds, setForceExpandedChainIds] = useState<Set<string>>(new Set());
  const cacheAccessOrder = useRef<string[]>([]);
  // 用 ref 跟踪 taskChainViews 的最新值，供 refreshLatestTaskChain 中判断缺失链
  const taskChainViewsRef = useRef<ChainView[]>([]);
  // 用 ref 跟踪 chainViewCache 的最新值，供 refreshLatestTaskChain / handleTaskClick 中判断 cache 是否命中
  const chainViewCacheRef = useRef<Record<string, ChainView>>({});

  const updateCache = useCallback((entries: Array<[string, ChainView]>) => {
    setChainViewCache(prev => {
      const next = { ...prev };
      const order = [...cacheAccessOrder.current];
      for (const [key, value] of entries) {
        next[key] = value;
        const idx = order.indexOf(key);
        if (idx >= 0) order.splice(idx, 1);
        order.push(key);
      }
      cacheAccessOrder.current = order;
      const evicted = evictLRU(next, order);
      chainViewCacheRef.current = evicted;
      return evicted;
    });
  }, []);

  // 包装 setTaskChainViews，同步更新 ref
  const updateTaskChainViews = useCallback((updater: ChainView[] | ((prev: ChainView[]) => ChainView[])) => {
    setTaskChainViews(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      taskChainViewsRef.current = next;
      return next;
    });
  }, []);

  const loadGroupChains = useCallback(async () => {
    if (!groupId) return;
    setChainsLoading(true);
    try {
      const treeRes = await chainApi.getGroupChains(groupId);
      const tree = treeRes.data;
      // taskChainViews 只存放顶层链（group chain）
      // task chain 通过 chainViewCache 在主链 packet 位置内联渲染
      const topViews: ChainView[] = [];
      const cacheEntries: Array<[string, ChainView]> = [];

      if (tree?.chain?.id) {
        try {
          const groupViewRes = await chainApi.getView(tree.chain.id, 1);
          if (groupViewRes.data) {
            topViews.push(groupViewRes.data);
            // 主链 sub_chains 摘要先入 cache (head/tail 摘要, 后面会被全量视图覆盖)
            for (const subSc of groupViewRes.data.sub_chains || []) {
              if (subSc.chain?.id) {
                cacheEntries.push([subSc.chain.id, subSc]);
              }
            }
          }
        } catch (err) {
          console.warn('[useChainViews] loadGroupChainView failed:', err);
        }
      }

      // 加载所有 task chain 的全量视图 → 入 chainViewCache (用于主链 packet 位置内联渲染)
      // 不再 push 到 taskChainViews, 避免任务链被堆到末尾
      if (tree?.sub_chains?.length) {
        for (const sc of tree.sub_chains) {
          const scId = sc?.id;
          if (!scId) continue;
          try {
            const taskViewRes = await chainApi.getView(scId, 1);
            if (taskViewRes.data) {
              cacheEntries.push([scId, taskViewRes.data]);
              for (const subSc of taskViewRes.data.sub_chains || []) {
                if (subSc.chain?.id) {
                  cacheEntries.push([subSc.chain.id, subSc]);
                }
              }
            }
          } catch (err) {
            console.warn('[useChainViews] loadTaskChainView failed:', scId, err);
          }
        }
      }

      if (cacheEntries.length > 0) {
        updateCache(cacheEntries);
      }
      updateTaskChainViews(topViews);
    } catch (err) {
      console.error('[useChainViews] loadGroupChains failed:', err);
      updateTaskChainViews([]);
    } finally {
      setChainsLoading(false);
    }
  }, [groupId, updateCache, updateTaskChainViews]);

  const refreshLatestTaskChain = useCallback(async (activeChainId?: string | null) => {
    if (!groupId) return;
    try {
      // 1. 优先刷新指定链的视图（流式完成的那条链）
      if (activeChainId) {
        const viewRes = await chainApi.getView(activeChainId, 1);
        if (viewRes.data) {
          const refreshedView = viewRes.data;
          const isTaskChain = refreshedView.chain.chain_type === 'task';
          const cacheEntries: Array<[string, ChainView]> = [];
          for (const subSc of refreshedView.sub_chains || []) {
            if (subSc.chain?.id) {
              cacheEntries.push([subSc.chain.id, subSc]);
            }
          }

          if (isTaskChain) {
            // task chain 全量视图 → 入 cache (主链 packet 位置内联渲染会取到最新内容)
            cacheEntries.push([refreshedView.chain.id, refreshedView]);
          } else {
            // group chain → 更新 taskChainViews (顶层链)
            updateTaskChainViews(prev => {
              const existIdx = prev.findIndex(v => v.chain.id === refreshedView.chain.id);
              if (existIdx >= 0) {
                const updated = [...prev];
                updated[existIdx] = refreshedView;
                return updated;
              }
              return [refreshedView, ...prev];
            });
          }

          if (cacheEntries.length > 0) {
            updateCache(cacheEntries);
          }
        }
      }

      // 2. 重新加载群链树，确保 group chain 视图和缺失的链视图都被更新
      const treeRes = await chainApi.getGroupChains(groupId);
      const tree = treeRes.data;

      // 刷新 group chain 视图（可能因新消息/rollover 而变化）
      if (tree?.chain?.id) {
        const groupViewRes = await chainApi.getView(tree.chain.id, 1);
        if (groupViewRes.data) {
          const groupView = groupViewRes.data;
          const cacheEntries: Array<[string, ChainView]> = [];
          for (const subSc of groupView.sub_chains || []) {
            if (subSc.chain?.id) {
              cacheEntries.push([subSc.chain.id, subSc]);
            }
          }
          if (cacheEntries.length > 0) {
            updateCache(cacheEntries);
          }
          updateTaskChainViews(prev => {
            const existIdx = prev.findIndex(v => v.chain.id === groupView.chain.id);
            if (existIdx >= 0) {
              const updated = [...prev];
              updated[existIdx] = groupView;
              return updated;
            }
            return [groupView, ...prev];
          });
        }
      }

      // 3. 加载 cache 中缺失的 task chain 全量视图（如新建任务/rollover 后新创建的链）
      if (tree?.sub_chains?.length) {
        for (const sc of tree.sub_chains) {
          const scId = sc?.id;
          if (!scId) continue;
          // cache 里没有, 或者只有摘要 (packet 数 < 实际), 都重新拉全量
          const cached = chainViewCacheRef.current[scId];
          const cachedPktCount = cached?.packets?.length ?? -1;
          const actualPktCount = sc.packet_count ?? 0;
          if (cached && cachedPktCount >= actualPktCount && cachedPktCount > 0) continue;
          try {
            const res = await chainApi.getView(scId, 1);
            if (res.data) {
              updateCache([[scId, res.data]]);
              const cacheEntries: Array<[string, ChainView]> = [];
              for (const subSc of res.data.sub_chains || []) {
                if (subSc.chain?.id) {
                  cacheEntries.push([subSc.chain.id, subSc]);
                }
              }
              if (cacheEntries.length > 0) {
                updateCache(cacheEntries);
              }
            }
          } catch (err) {
            console.warn('[useChainViews] loadMissingChainView failed:', scId, err);
          }
        }
      }
    } catch (err) {
      console.error(`[useChainViews] refreshLatestTaskChain failed for chain=${activeChainId ?? '(none)'}`, err);
    }
  }, [groupId, updateCache, updateTaskChainViews]);

  const handleLoadSubChain = useCallback(async (chainId: string) => {
    if (chainViewCache[chainId]) return;
    try {
      const res = await chainApi.getView(chainId, 1);
      if (res.data) {
        updateCache([[chainId, res.data]]);
      }
    } catch (err) {
      console.error('[useChainViews] loadSubChain failed:', err);
    }
  }, [chainViewCache, updateCache]);

  const handleTaskClick = useCallback(async (taskId: string) => {
    if (!groupId) return;
    try {
      const treeRes = await chainApi.getGroupChains(groupId);
      const tree = treeRes.data;
      if (!tree?.sub_chains?.length) return;

      const taskChain = tree.sub_chains.find((sc: Chain) => sc.task_id === taskId);
      if (!taskChain) {
        console.warn('[useChainViews] No chain found for task:', taskId);
        return;
      }

      // 并行拉取: task chain 全量视图 (入 cache 供内联渲染) + 主链视图 (确保 packet 含 sub_chain_id)
      const [taskViewRes, groupViewRes] = await Promise.all([
        chainApi.getView(taskChain.id, 1),
        tree.chain?.id ? chainApi.getView(tree.chain.id, 1) : Promise.resolve(null),
      ]);
      const cacheEntries: Array<[string, ChainView]> = [];
      if (taskViewRes.data) {
        cacheEntries.push([taskChain.id, taskViewRes.data]);
        for (const subSc of taskViewRes.data.sub_chains || []) {
          if (subSc.chain?.id) cacheEntries.push([subSc.chain.id, subSc]);
        }
      }
      if (groupViewRes?.data) {
        // 刷新主链视图, 确保内联渲染时能找到含 sub_chain_id 的 packet
        updateTaskChainViews(prev => {
          const existIdx = prev.findIndex(v => v.chain.id === groupViewRes.data!.chain.id);
          if (existIdx >= 0) {
            const updated = [...prev];
            updated[existIdx] = groupViewRes.data!;
            return updated;
          }
          return [groupViewRes.data!, ...prev];
        });
        for (const subSc of groupViewRes.data.sub_chains || []) {
          if (subSc.chain?.id) cacheEntries.push([subSc.chain.id, subSc]);
        }
      }
      if (cacheEntries.length > 0) {
        updateCache(cacheEntries);
      }

      // 标记为需要 force expand (内联 ChainBlock 渲染时强制展开)
      // 同时 ChatPanel 会监听 forceExpandedChainIds 变化, 滚动到对应 chain
      setForceExpandedChainIds(prev => {
        const next = new Set(prev);
        next.add(taskChain.id);
        return next;
      });
    } catch (err) {
      console.error('[useChainViews] handleTaskClick failed:', err);
    }
  }, [groupId, updateCache, updateTaskChainViews]);

  // 当群组切换时，清理上一个群的链视图状态
  useEffect(() => {
    taskChainViewsRef.current = [];
    chainViewCacheRef.current = {};
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional reset on group change
    setTaskChainViews([]);
    setChainViewCache({});
    cacheAccessOrder.current = [];
  }, [groupId]);

  return {
    taskChainViews,
    chainViewCache,
    chainsLoading,
    forceExpandedChainIds,  // v2 P2+: 传给 ChainBlock.forceExpanded
    loadGroupChains,
    refreshLatestTaskChain,
    handleLoadSubChain,
    handleTaskClick,
  };
}

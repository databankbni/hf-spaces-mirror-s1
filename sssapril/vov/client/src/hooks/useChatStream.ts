import { useState, useRef, useCallback, useEffect } from 'react';
import { toast } from 'sonner';
import { groupApi, chainApi } from '../api';
import { useSystemStatus } from './useSettings';
import type {
  ChainView,
  ChainEndData,
  Packet,
  WsServerMessage,
  TokenPayload,
  ToolCallPayload,
  ToolResultPayload,
  DonePayload,
  StreamErrorPayload,
} from '../types';

interface UseChatStreamParams {
  groupId: string | undefined;
  group: { id: string; members: any[] } | undefined;
  members: any[];
  agentList: Array<{ id: string; name: string; role?: string; avatar?: string }>;
  taskChainViews: ChainView[];
  /** 子链视图缓存 (task chain 全量视图存这里, 供 applySnapshot 查找) */
  chainViewCache: Record<string, ChainView>;
  refreshLatestTaskChain: (activeChainId?: string | null) => Promise<void>;
}

/**
 * 聊天流 hook (v2: WebSocket 架构)
 *
 * 核心变化 (相对 v1 SSE 版本):
 *   - handleSend / tryResumeStream 改为 POST, 立即返回 session 元信息
 *   - 流式事件 (token/tool_call/tool_result/chain_end/done 等) 通过 WebSocket 实时推送
 *   - handleStreamEvent: 统一的 WS 事件分发器, 由 ChatPage 的 WS onMessage 调用
 *   - 去掉 SSE 的 idle timeout / recovery 逻辑 (WebSocket 自带重连)
 *   - cancel 机制: 调 POST /chat/stream/cancel, 后端 task.cancel() 中断 LLM
 */
export function useChatStream({
  groupId,
  group,
  members,
  agentList,
  taskChainViews,
  chainViewCache,
  refreshLatestTaskChain,
}: UseChatStreamParams) {
  const [activeReplyChain, setActiveReplyChain] = useState<ChainView | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  // 当前正在 attach 追踪的 (chainId, packetId), 暴露给 ChatPanel 用于 ChainBlock 显示
  const [streamingChainId, setStreamingChainId] = useState<string | null>(null);
  const [streamingPacketId, setStreamingPacketId] = useState<string | null>(null);

  // LLM 配置状态 (React Query 缓存, staleTime=30s, 避免每次发消息都 RTT)
  const systemStatus = useSystemStatus();

  const activeChainIdRef = useRef<string | null>(null);
  const activePacketIdRef = useRef<string | null>(null);
  // 流式活跃标志 (guard: 防止 sending/resume 期间重复触发 resume effect)
  const activeStreamRef = useRef(false);
  // 去重: 同一 groupId+packetId 只 resume 一次
  const lastResumedKeyRef = useRef<string>('');
  // Token 批处理: 收集 token 并通过 rAF 批量刷新，避免每 token 触发重渲染
  const tokenBufferRef = useRef<string>('');
  const rafIdRef = useRef<number>(0);

  // ── 流式事件通用处理 (sending / resume 共用) ──

  /**
   * 应用 token 事件: 追加到 activeReplyChain 中最后一个 agent_text packet
   * 使用 rAF 批处理：收集 token，每帧批量应用一次
   */
  const flushTokens = useCallback(() => {
    rafIdRef.current = 0;
    const batch = tokenBufferRef.current;
    if (!batch) return;
    tokenBufferRef.current = '';
    setActiveReplyChain(prev => {
      if (!prev) return prev;
      const pkts = [...prev.packets];
      for (let i = pkts.length - 1; i >= 0; i--) {
        if (pkts[i].packet_type === 'agent_text') {
          pkts[i] = { ...pkts[i], content: pkts[i].content + batch };
          break;
        }
      }
      return { ...prev, packets: pkts };
    });
  }, []);

  const applyToken = useCallback((token: string) => {
    if (!token) return;
    tokenBufferRef.current += token;
    if (!rafIdRef.current) {
      rafIdRef.current = requestAnimationFrame(flushTokens);
    }
  }, [flushTokens]);

  /**
   * 应用 snapshot 事件: 用 taskChainViews / chainViewCache 中已加载的 chain view + snapshot 内的
   * 已有 content 构造 activeReplyChain. 若 cache 未命中则按需拉取 (resume 早于 chain view 加载完成的场景).
   */
  const applySnapshot = useCallback(async (data: {
    chain_id: string;
    packet_id: string;
    content: string;
    metadata?: Record<string, unknown>;
    is_streaming?: boolean;
    is_cancelled?: boolean;
  }) => {
    const { chain_id, packet_id, content, metadata } = data;
    // 先查 taskChainViews (group chain), 再查 chainViewCache (task chain 全量视图)
    let existing = taskChainViews.find(v => v.chain.id === chain_id)
      || chainViewCache[chain_id];
    if (!existing) {
      // cache 未命中 (resume 在 chain view 加载前触发), 按需拉取
      try {
        const res = await chainApi.getView(chain_id, 1);
        if (res.data) {
          existing = res.data;
        }
      } catch (err) {
        console.warn('[useChatStream] snapshot: chain view fetch failed', chain_id, err);
        return;
      }
    }
    if (!existing) {
      console.warn('[useChatStream] snapshot: chain view not found', chain_id);
      return;
    }

    // 找到 packet 同步 content / metadata / streaming 标记
    const pkts = existing.packets.map(p => {
      if (p.id !== packet_id) return p;
      return {
        ...p,
        content: content ?? p.content,
        metadata: {
          ...(p.metadata as Record<string, unknown> | null || {}),
          ...(metadata as Record<string, unknown> | undefined || {}),
          streaming: true,
        },
      };
    });

    // 强制 chain 状态为 active (resume 时, view 可能是 active/completed 任意状态)
    setActiveReplyChain({
      ...existing,
      chain: { ...existing.chain, status: 'active' },
      packets: pkts,
    });
    activeChainIdRef.current = chain_id;
    activePacketIdRef.current = packet_id;
    setStreamingChainId(chain_id);
    setStreamingPacketId(packet_id);
  }, [taskChainViews, chainViewCache]);

  /**
   * 应用 chain_end 事件
   */
  const applyChainEnd = useCallback((data: ChainEndData) => {
    setActiveReplyChain(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        chain: { ...prev.chain, status: data.status as ChainView['chain']['status'] },
      };
    });
  }, []);

  /**
   * 应用 tool_call 事件: 追加一个新的 tool_call packet
   */
  const applyToolCall = useCallback((callData: ToolCallPayload) => {
    setActiveReplyChain(prev => {
      if (!prev) return prev;
      const toolCallPktId = `pkt-tc-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const newPkt: Packet = {
        id: toolCallPktId,
        chain_id: prev.chain.id,
        prev_packet_id: prev.packets.length > 0 ? prev.packets[prev.packets.length - 1].id : null,
        packet_type: 'tool_call',
        sender_type: 'agent',
        sender_id: prev.chain.agent_id || 'agent',
        sender_name: '',
        content: JSON.stringify(callData.arguments),
        content_type: 'text',
        sub_chain_id: null,
        metadata: { tool_name: callData.tool_name, tool_call_id: callData.tool_call_id },
        created_at: new Date().toISOString(),
      };
      return { ...prev, packets: [...prev.packets, newPkt] };
    });
  }, []);

  /**
   * 应用 tool_result 事件: 追加 tool_result + 新的 agent_text packet (用于承接 render_spec/inject_js)
   */
  const applyToolResult = useCallback((resultData: ToolResultPayload) => {
    setActiveReplyChain(prev => {
      if (!prev) return prev;
      const toolResultPktId = `pkt-tr-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const resultStr = typeof resultData.result === 'string' ? resultData.result : JSON.stringify(resultData.result);
      const newPkt: Packet = {
        id: toolResultPktId,
        chain_id: prev.chain.id,
        prev_packet_id: prev.packets.length > 0 ? prev.packets[prev.packets.length - 1].id : null,
        packet_type: 'tool_result',
        sender_type: 'tool',
        sender_id: resultData.tool_name,
        sender_name: resultData.tool_name,
        content: resultStr.length > 2000 ? resultStr.substring(0, 2000) + '...' : resultStr,
        content_type: 'text',
        sub_chain_id: null,
        metadata: { tool_name: resultData.tool_name, tool_call_id: resultData.tool_call_id },
        created_at: new Date().toISOString(),
      };
      const agentPktId = `pkt-agent-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const agentMeta: Record<string, unknown> = {};
      if (resultData.render_spec) agentMeta.render_spec = resultData.render_spec;
      if (resultData.inject_js) {
        agentMeta.inject_js = resultData.inject_js;
        if (resultData.inject_description) {
          agentMeta.inject_description = resultData.inject_description;
        }
      }
      const agentPkt: Packet = {
        id: agentPktId,
        chain_id: prev.chain.id,
        prev_packet_id: toolResultPktId,
        packet_type: 'agent_text',
        sender_type: 'agent',
        sender_id: prev.chain.agent_id || 'agent',
        // 修复 sender_name 空字符串 bug:
        // 之前留空字符串导致 PacketRenderer 渲染"头像+空消息+空 sender_name"
        // 复用 prev.chain.description (@agent_name 格式) 或 prev.packets 中上一条 agent_text 的 sender_name
        sender_name: prev.chain.description?.replace(/^@/, '')
          || prev.packets.slice().reverse().find(p => p.sender_type === 'agent' && p.sender_name)?.sender_name
          || 'Agent',
        content: '',
        content_type: 'text',
        sub_chain_id: null,
        metadata: agentMeta,
        created_at: new Date().toISOString(),
      };
      return { ...prev, packets: [...prev.packets, newPkt, agentPkt] };
    });
  }, []);

  /**
   * 清空所有 streaming state (供 done / cancel / 群组切换复用, 避免散落重复代码)
   */
  const clearStreamingState = useCallback(() => {
    setActiveReplyChain(null);
    activeChainIdRef.current = null;
    activePacketIdRef.current = null;
    activeStreamRef.current = false;
    setStreamingChainId(null);
    setStreamingPacketId(null);
    setIsStreaming(false);
  }, []);

  // ── WebSocket 事件分发器 ──

  /**
   * 处理 WebSocket 推送的流式事件
   *
   * 由 ChatPage 的 WS onMessage 调用, 将 chat stream 相关事件 (token/tool_call/
   * tool_result/render_spec/chain_end/done/error) 分发到对应的 apply* 处理函数。
   *
   * 非流式事件 (agent_message/task_update 等) 由 ChatPage 自行处理, 不进入这里。
   */
  const handleStreamEvent = useCallback((message: WsServerMessage) => {
    const { type, payload } = message;
    switch (type) {
      case 'token': {
        const p = payload as TokenPayload;
        applyToken(p.content);
        break;
      }
      case 'tool_call': {
        applyToolCall(payload as ToolCallPayload);
        break;
      }
      case 'tool_result': {
        applyToolResult(payload as ToolResultPayload);
        break;
      }
      case 'chain_end': {
        applyChainEnd(payload as ChainEndData);
        break;
      }
      case 'done': {
        const p = payload as DonePayload;
        // 刷新剩余 token
        if (rafIdRef.current) {
          cancelAnimationFrame(rafIdRef.current);
          rafIdRef.current = 0;
        }
        if (tokenBufferRef.current) {
          flushTokens();
        }
        const chainId = p.chain_id || activeChainIdRef.current;
        refreshLatestTaskChain(chainId)
          .then(() => clearStreamingState())
          .catch(err => {
            console.error('[useChatStream] done: refreshLatestTaskChain failed:', err);
            clearStreamingState();
          });
        break;
      }
      case 'error': {
        const p = payload as StreamErrorPayload;
        // chat_service fatal error: { message } → toast + 清理 streaming state
        // StreamPushPlugin tool error: { chain_id, content } → 仅 log, 流继续
        if (p.message) {
          console.error('[useChatStream] stream fatal error:', p.message);
          toast.error(p.message);
          // 修复: fatal error 时后端可能不发 done (虽然后端已修, 但双保险)
          // 立即清理 streaming state, 避免发送按钮卡在暂停图标
          clearStreamingState();
        } else {
          console.warn('[useChatStream] tool error event:', p.content);
        }
        break;
      }
      case 'user_message':
      case 'chain_start':
        // handleSend 已在前端乐观构建 activeReplyChain, 这两个事件无需处理
        break;
    }
  }, [applyToken, applyToolCall, applyToolResult, applyChainEnd, flushTokens, refreshLatestTaskChain, clearStreamingState]);

  // ── 主动发送消息 (POST + WS) ──

  const handleSend = useCallback(async (
    text: string,
    targetAgentId: string | undefined,
    onSendingChange: (v: boolean) => void,
  ) => {
    if (!text || isStreaming || !group) return;

    // 检查 LLM 是否已配置 (使用 React Query 缓存, 避免每次发消息都 RTT)
    if (systemStatus.data && !systemStatus.data.llm_configured) {
      toast.error('请先配置 LLM API Key', {
        description: '点击首页右上角「设置」按钮进行配置',
        duration: 5000,
      });
      onSendingChange(false);
      return;
    }

    onSendingChange(true);
    setIsStreaming(true);
    activeStreamRef.current = true;

    try {
      const result = await groupApi.chatStream(group.id, text, targetAgentId);

      // no_agent 场景: 后端已广播 user_message + done, 前端刷新即可
      if (result.no_agent) {
        await refreshLatestTaskChain();
        clearStreamingState();
        return;
      }
      if (result.error) {
        toast.error(result.error);
        clearStreamingState();
        return;
      }

      activeChainIdRef.current = result.chain_id;
      activePacketIdRef.current = result.packet_id;
      setStreamingChainId(result.chain_id);
      setStreamingPacketId(result.packet_id);

      // 乐观构建 reply view (后续 token/tool_call 等通过 WS 事件更新)
      const agentName = result.agent_name
        || (targetAgentId ? agentList.find(a => a.id === targetAgentId)?.name : undefined)
        || members.find(m => m.role === 'lead')?.agent?.name
        || members[0]?.agent?.name
        || 'Agent';
      const userPktId = `pkt-user-${Date.now()}`;
      const replyView: ChainView = {
        chain: {
          id: result.chain_id,
          parent_chain_id: result.parent_chain_id,
          chain_type: result.chain_type as ChainView['chain']['chain_type'],
          group_id: group.id,
          task_id: null,
          agent_id: result.agent_id,
          status: 'active',
          head_packet_id: userPktId,
          tail_packet_id: result.packet_id,
          description: result.agent_name ? `@${result.agent_name}` : null,
          packet_count: 2,
          sub_chain_count: 0,
          completed_at: null,
          created_at: new Date().toISOString(),
        },
        packets: [
          {
            id: userPktId,
            chain_id: result.chain_id,
            prev_packet_id: null,
            packet_type: 'user_input',
            sender_type: 'user',
            sender_id: 'user',
            sender_name: '你',
            content: text,
            content_type: 'text',
            sub_chain_id: null,
            metadata: {},
            created_at: new Date().toISOString(),
          },
          {
            id: result.packet_id,
            chain_id: result.chain_id,
            prev_packet_id: userPktId,
            packet_type: 'agent_text',
            sender_type: 'agent',
            sender_id: result.agent_id || targetAgentId || 'agent',
            sender_name: agentName,
            content: '',
            content_type: 'text',
            sub_chain_id: null,
            metadata: {},
            created_at: new Date().toISOString(),
          },
        ],
        sub_chains: [],
      };
      setActiveReplyChain(replyView);
      // 后续事件 (token/tool_call/tool_result/chain_end/done) 通过 WebSocket 实时推送
      // → ChatPage.handleWsMessage → handleStreamEvent 处理
    } catch (err) {
      console.error('[useChatStream] send failed:', err);
      // POST 失败: fallback 到同步 chat
      try {
        await groupApi.chat(group.id, text, targetAgentId);
        await refreshLatestTaskChain();
      } catch {
        toast.error('消息发送失败，请重试');
      }
      clearStreamingState();
    } finally {
      onSendingChange(false);
    }
  }, [isStreaming, group, members, agentList, refreshLatestTaskChain, clearStreamingState, systemStatus.data]);

  // ── 主动停止 (cancel API + 清理前端状态) ──

  const handleStopStream = useCallback(() => {
    // 通知后端取消 LLM 调用 (task.cancel() → CancelledError)
    const chainId = activeChainIdRef.current;
    const packetId = activePacketIdRef.current;
    if (groupId) {
      groupApi.chatStreamCancel(groupId, packetId ?? undefined, chainId ?? undefined)
        .then(res => {
          if (!res.cancelled) {
            console.warn('[useChatStream] cancel: no active session to stop');
          }
        })
        .catch(err => {
          console.warn('[useChatStream] cancel request failed:', err);
        });
    }
    // 清理前端状态 (后端 done 事件可能仍会到达, 但状态已清空, done handler 是 no-op)
    clearStreamingState();
  }, [groupId, clearStreamingState]);

  // ── 自动恢复: page load / groupId 切换时, 查活跃流并 attach ──

  const tryResumeStream = useCallback(async (
    chainId: string,
    packetId: string,
    options?: { force?: boolean },
  ): Promise<boolean> => {
    if (!groupId) return false;
    const key = `${chainId}:${packetId}`;
    // force=true 时跳过去重 (status 检查恢复场景)
    if (!options?.force && lastResumedKeyRef.current === key) return false;
    lastResumedKeyRef.current = key;

    try {
      // POST attach: 获取当前快照
      const result = await groupApi.chatStreamAttach(groupId, packetId, chainId);
      if (!result.active) {
        // 后端无活跃流: DB 已有最终 content, 不需要恢复
        setIsStreaming(false);
        return false;
      }

      // 有活跃流: 标记 streaming, 应用快照, 后续事件通过 WebSocket 接收
      setIsStreaming(true);
      activeStreamRef.current = true;
      activeChainIdRef.current = result.chain_id || chainId;
      activePacketIdRef.current = result.packet_id || packetId;
      setStreamingChainId(result.chain_id || chainId);
      setStreamingPacketId(result.packet_id || packetId);

      await applySnapshot({
        chain_id: result.chain_id || chainId,
        packet_id: result.packet_id || packetId,
        content: result.content || '',
        metadata: result.metadata,
        is_streaming: result.is_streaming,
        is_cancelled: result.is_cancelled,
      });
      // 后续 token/tool_call/done 等事件通过 WebSocket 实时推送
      return true;
    } catch (e) {
      console.warn('[useChatStream] tryResumeStream failed:', e);
      clearStreamingState();
      return false;
    }
  }, [groupId, applySnapshot, clearStreamingState]);

  // 监听 groupId / taskChainViews 变化, 尝试 resume (从 DB 中 streaming=true 的 packet 恢复)
  useEffect(() => {
    if (!groupId) {
      console.debug('[useChatStream] resume: no groupId');
      return;
    }
    if (taskChainViews.length === 0) {
      console.debug('[useChatStream] resume: taskChainViews empty');
      return;
    }
    // 已经在流式 (sending 阶段) 则不 resume
    if (activeStreamRef.current) {
      console.debug('[useChatStream] resume: already streaming, skip');
      return;
    }

    // 找 streaming packet
    let streamPkt: Packet | null = null;
    let streamChainId: string | null = null;
    for (const view of taskChainViews) {
      for (const pkt of view.packets) {
        if (pkt.packet_type === 'agent_text'
            && (pkt.metadata as Record<string, unknown> | null)?.streaming) {
          streamPkt = pkt;
          streamChainId = view.chain.id;
          break;
        }
      }
      if (streamPkt) break;
    }

    if (!streamPkt || !streamChainId) {
      console.debug(
        '[useChatStream] resume: no streaming packet found in %d chain views',
        taskChainViews.length,
      );
      return;
    }

    const key = `${streamChainId}:${streamPkt.id}`;
    if (lastResumedKeyRef.current === key) {
      console.debug('[useChatStream] resume: already resumed for', key);
      return;
    }

    console.log(
      '[useChatStream] resume: found streaming packet, chain=%s packet=%s',
      streamChainId.slice(0, 8), streamPkt.id.slice(0, 8),
    );
    // 异步 resume, 不阻塞渲染
    void tryResumeStream(streamChainId, streamPkt.id);
  }, [groupId, taskChainViews, tryResumeStream]);

  // 群组切换: 清理上一个群的流状态
  useEffect(() => {
    setActiveReplyChain(null);
    setIsStreaming(false);
    activeStreamRef.current = false;
    activeChainIdRef.current = null;
    activePacketIdRef.current = null;
    setStreamingChainId(null);
    setStreamingPacketId(null);
    lastResumedKeyRef.current = '';
    // 清理 token 批处理
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = 0;
    }
    tokenBufferRef.current = '';
  }, [groupId]);

  // ★ 立即检查: groupId 变化时, 不等 taskChainViews 加载, 直接查 group 级活跃流
  // 解决: 刷新页面后 isStreaming 状态丢失, 在 taskChainViews 加载完前用户能发送消息的窗口期
  useEffect(() => {
    if (!groupId) return;
    if (activeStreamRef.current) return;

    let cancelled = false;
    groupApi.chatStreamStatus(groupId)
      .then(status => {
        if (cancelled) return;
        if (status.active && status.chain_id && status.packet_id) {
          console.log(
            '[useChatStream] group has active stream on load, blocking send + resuming (chain=%s packet=%s)',
            status.chain_id.slice(0, 8), status.packet_id.slice(0, 8),
          );
          // ★ 立即阻塞发送, 防止用户在 resume 完成前发消息
          setIsStreaming(true);
          // 直接用后端返回的 chain_id/packet_id 恢复, 不依赖 taskChainViews 加载
          void tryResumeStream(status.chain_id, status.packet_id);
        }
      })
      .catch(err => {
        console.warn('[useChatStream] initial group status check failed:', err);
      });

    return () => { cancelled = true; };
  }, [groupId, tryResumeStream]);

  return {
    activeReplyChain,
    isStreaming,
    streamingChainId,
    streamingPacketId,
    handleSend,
    handleStopStream,
    tryResumeStream,
    handleStreamEvent,
  };
}
